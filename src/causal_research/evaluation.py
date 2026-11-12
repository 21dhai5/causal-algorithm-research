"""留出因果估计与逐步预测评估；假设与局限随 JSON 输出一起保留。"""

import math
import numpy as np

from .ledger import DatasetMode, ObservationLedger, Provenance, Transition
from .models import (InsufficientEvidence, arrays, design, fit_outcome,
                     fit_propensity, predict_outcome, predict_propensity)


# 诊断经验动作支持和权重有效样本量；失败时拒绝输出因果数值。
def overlap_diagnostics(action: np.ndarray, probability: np.ndarray) -> dict:
    if (action.ndim != 1 or probability.shape != action.shape or len(action) < 40
            or not np.isfinite(probability).all() or not np.isin(action, [0, 1]).all()):
        raise InsufficientEvidence("overlap inputs are missing, nonfinite, or malformed")
    treated = int(np.sum(action == 1)) # 留出集接受动作 1 的样本数。
    control = int(np.sum(action == 0)) # 留出集接受动作 0 的样本数。
    reasons = [] # 关闭因果估计的具体原因，保留供审计。
    if treated < 20 or control < 20:
        reasons.append("minimum_arm_count_below_20")
    if np.min(probability) < 0.02 or np.max(probability) > 0.98:
        reasons.append("estimated_propensity_outside_[0.02,0.98]")
    effective = [] # 两个动作臂各自的逆概率权重有效样本量。
    for arm in (0, 1): # 分臂计算，避免多数臂掩盖少数臂支持不足。
        denominator = probability[action == arm] if arm == 1 else 1 - probability[action == arm] # 实际动作概率。
        if len(denominator) == 0 or np.any(denominator <= 0) or np.any(denominator > 1):
            effective.append(0.0)
        else:
            weights = 1 / denominator # 不裁剪权重，支持不足应拒绝。
            effective.append(float(np.sum(weights)**2 / np.sum(weights**2)))
    if min(effective) < max(10, len(action) * 0.05):
        reasons.append("effective_sample_size_too_small")
    return {
        "accepted": not reasons, # 仅是经验筛查通过，不是可识别性证明。
        "reasons": reasons, # 任何原因都会阻止结果发布为因果估计。
        "arm_counts": {"0": control, "1": treated}, # 原始动作支持。
        "propensity_min": float(np.min(probability)), # 全部留出样本的最小估计概率。
        "propensity_max": float(np.max(probability)), # 全部留出样本的最大估计概率。
        "ess_by_arm": {"0": effective[0], "1": effective[1]}, # 分臂权重有效样本量。
        "weights_clipped": False, # 裁剪不能恢复可识别性，本实现不以裁剪绕过门槛。
        "identification_proven": False, # 数据诊断不能验证无未测混杂假设。
    }


# 对固定干扰模型下的留出 AIPW 分数做移动块重采样，只给近似条件区间。
def block_interval(scores: np.ndarray, rng: np.random.Generator, *, draws: int,
                   block_length: int, alpha: float = 0.05) -> list[float]:
    if (scores.ndim != 1 or not np.isfinite(scores).all() or draws < 100
            or not 1 <= block_length <= len(scores) // 2 or not 0 < alpha < 1):
        raise InsufficientEvidence("invalid moving-block bootstrap configuration")
    blocks = math.ceil(len(scores) / block_length) # 每次重复覆盖完整留出序列所需块数。
    starts = rng.integers(0, len(scores) - block_length + 1, size=(draws, blocks)) # 连续块合法起点。
    indices = (starts[:, :, None] + np.arange(block_length)).reshape(draws, -1)[:, :len(scores)] # 连接块索引。
    differences = scores[indices].mean(axis=1) - scores.mean() # 重采样相对原均值的偏移。
    lower, upper = np.quantile(differences, [alpha / 2, 1 - alpha / 2]) # 条件分布的尾部分位数。
    return [float(scores.mean() - upper), float(scores.mean() - lower)]


# 只在训练段拟合结果与倾向模型，全部估计在最终测试段求平均。
def estimate_causal(train: tuple[Transition, ...], test: list[Transition], *, seed: int,
                    bootstrap_draws: int, block_length: int) -> dict:
    result = { # 先提供明确身份；若门槛失败，数值字段保持空值。
        "target": "HELDOUT_TEST_AVERAGE_ONE_STEP_EFFECT", # 干预当前动作对下一步的平均效应。
        "association_label": "ASSOCIATION_ONLY", # 朴素组间差异不称因果。
        "naive_treated_minus_untreated": None, # 仅描述测试段组间相关性。
        "g_computation": None, # 调整 x_t、y_t 后的线性标准化估计。
        "aipw": None, # 估计倾向下的增广逆概率估计。
        "aipw_ci": None, # 固定训练模型的依赖感知近似条件区间。
        "status": "REFUSED", # 未全部验证前一律关闭因果结果。
        "overlap": None, # 留出动作支持与权重诊断。
        "refusal_reason": None, # 输入或模型失败的可读原因。
        "evaluation_as_of": None, # 最终评分等待所有测试标签可用，不冒充测试终点在线指标。
        "label_maturity_protocol": "ALL_TEST_LABELS_MATURED", # 固定窗口完成统一成熟后才做最终评价。
    }
    try:
        x, y, action, outcome = arrays(test) # 留出段只用于最终估计，不参与模型拟合。
        arrays(train) # 两个集合都先验证类型、顺序、有限值和来源。
        if train[0].provenance != test[0].provenance:
            raise InsufficientEvidence("training and test provenance must match")
        if train[0].provenance != Provenance.SYNTHETIC_OBSERVATION:
            raise InsufficientEvidence("real-data identification is not implemented in this synthetic MVP")
        if train[-1].origin_time >= test[0].origin_time:
            raise InsufficientEvidence("training origins must strictly precede every test origin")
        if max(row.available_at for row in train) > test[0].origin_time:
            raise InsufficientEvidence("training labels must be available before the first test prediction")
        result["evaluation_as_of"] = max(row.available_at for row in test)
        if np.any(action == 0) and np.any(action == 1):
            result["naive_treated_minus_untreated"] = float(outcome[action == 1].mean()
                                                         - outcome[action == 0].mean())
        coefficients = fit_outcome(train) # 训练段固定结果模型。
        propensity = fit_propensity(train) # 训练段固定倾向模型。
        probability = predict_propensity(propensity, x, y) # 测试段动作概率，不做再拟合或裁剪。
        diagnostics = overlap_diagnostics(action, probability) # 因果估计发布前的支持门槛。
        result["overlap"] = diagnostics
        if not diagnostics["accepted"]:
            result["refusal_reason"] = "; ".join(diagnostics["reasons"])
            return result
        mean_zero = design(x, y, np.zeros(len(test))) @ coefficients # 当前动作置零的一步条件均值。
        mean_one = design(x, y, np.ones(len(test))) @ coefficients # 当前动作置一的一步条件均值。
        scores = (mean_one - mean_zero + action * (outcome - mean_one) / probability
                  - (1 - action) * (outcome - mean_zero) / (1 - probability)) # 留出 AIPW 分数。
        if not np.isfinite(scores).all():
            raise InsufficientEvidence("nonfinite AIPW scores")
        interval = block_interval(scores, np.random.default_rng(seed), draws=bootstrap_draws,
                                  block_length=block_length) # 固定模型的块区间。
        result.update({
            "g_computation": float(np.mean(mean_one - mean_zero)), # 测试状态分布上的标准化效应。
            "aipw": float(np.mean(scores)), # 留出增广估计。
            "aipw_ci": interval, # 不包含训练模型不确定性的近似区间。
            "status": "ESTIMATED_UNDER_SYNTHETIC_ASSUMPTIONS", # 成功仍依赖明确识别假设。
            "propensity_iterations": propensity[3], # 可复核的求解收敛次数。
            "nuisance_training_rows": len(train), # 固定干扰模型的训练规模。
            "heldout_rows": len(test), # 仅用于最终估计的测试规模。
        })
    except (ValueError, np.linalg.LinAlgError) as error:
        result["refusal_reason"] = str(error)
    return result


# 从绝对残差取保守经验分位数；序列相关下不承诺有限样本覆盖率。
def residual_quantile(residuals: np.ndarray, probability: float) -> float:
    if len(residuals) < 40 or not np.isfinite(residuals).all():
        raise InsufficientEvidence("calibration needs at least 40 finite true-feedback residuals")
    level = min(1, math.ceil((len(residuals) + 1) * probability) / len(residuals)) # 保守有限样本秩。
    return float(np.quantile(np.abs(residuals), level, method="higher"))


# 汇总单步真实反馈误差；区间与漂移阈值在校准后冻结。
def prediction_metrics(errors: np.ndarray, half_width: float) -> dict:
    return {
        "mae": float(np.mean(np.abs(errors))), # 平均绝对误差。
        "rmse": float(np.sqrt(np.mean(errors**2))), # 均方根误差。
        "empirical_interval_coverage": float(np.mean(np.abs(errors) <= half_width)), # 经验覆盖率。
        "interval_half_width": half_width, # 整个测试段固定的对称区间半宽。
        "rows": len(errors), # 真正完成预测再反馈的测试数量。
    }


# 逐时钟预测后评估；每次拟合只读取当时已可用的观测，预测不写入账本。
def evaluate_prequential(rows: list[Transition], train_end: int, test_start: int) -> dict:
    if not 40 <= train_end < test_start < len(rows):
        raise InsufficientEvidence("invalid chronological split or cold start")
    x, y, action, outcome = arrays(rows) # 一次校验全部观测，后续仅按可用时钟选取训练行。
    matrix = design(x, y, action) # 预先构造不参与参数拟合的只读特征矩阵。
    positions = {row.row_id: index for index, row in enumerate(rows)} # 账本标识到数组行号的映射。
    ledger = ObservationLedger(DatasetMode.SYNTHETIC) # 全部来源固定为合成观测。
    for row in rows: # 可预先保存未来记录，但训练入口只能读取时间过滤快照。
        ledger.add(row)
    model_errors = [] # 模型每一步在获得当前反馈前留下的预测残差。
    persistence_errors = [] # 持续性基线 y_t 的同期预测残差。
    forecast_records = [] # 只保留少量审计示例，不把预测回灌训练。
    for position, row in enumerate(rows[train_end:], start=train_end): # 位置用于切分，时钟取记录原值。
        available = ledger.snapshot(row.origin_time) # 决策原点上真正已知的标签。
        if any(observed.origin_time >= row.origin_time for observed in available):
            raise RuntimeError("future outcome leakage detected")
        if len(available) < 40:
            raise InsufficientEvidence("prequential cold start: fewer than 40 available labels")
        indices = [positions[observed.row_id] for observed in available] # 只有快照中的反馈可用于本次拟合。
        coefficients, _, rank, _ = np.linalg.lstsq(matrix[indices], outcome[indices], rcond=None) # 按已知反馈重拟合。
        if rank != 4 or not np.isfinite(coefficients).all():
            raise InsufficientEvidence("prequential outcome design is rank deficient")
        forecast = predict_outcome(coefficients, row) # 当前动作已知的一步预测。
        model_errors.append(row.outcome_y_next - forecast)
        persistence_errors.append(row.outcome_y_next - row.y_t)
        if position == test_start or position == len(rows) - 1:
            forecast_records.append({
                "origin_time": row.origin_time, # 预测发出时刻。
                "target_event_time": row.event_time, # 被预测结果的发生时刻。
                "label_available_at": row.available_at, # 当前结果最早可用于后续训练的时刻。
                "max_training_available_at": max(observed.available_at for observed in available), # 审计上界。
                "training_rows": len(available), # 延迟过滤后训练规模。
                "prediction": forecast, # 预测只存在于报告，绝不作为反馈。
                "current_row_in_training": row.row_id in {observed.row_id for observed in available}, # 泄漏检查。
            })
    calibration_count = test_start - train_end # 校准段长度，严格早于全部测试预测。
    known_calibration = np.array([row.available_at <= rows[test_start].origin_time
                                 for row in rows[train_end:test_start]]) # 测试开始前确实已到达的校准标签。
    calibration = np.asarray(model_errors[:calibration_count])[known_calibration] # 延迟未知标签不能校准。
    persistence_calibration = np.asarray(persistence_errors[:calibration_count])[known_calibration] # 相同反馈门槛。
    errors = np.asarray(model_errors[calibration_count:]) # 当前结果在预测后才参与测试评价。
    persistence = np.asarray(persistence_errors[calibration_count:]) # 同时段基线误差。
    width = residual_quantile(calibration, 0.9) # 90% 名义预测区间的冻结半宽。
    persistence_width = residual_quantile(persistence_calibration, 0.9) # 基线冻结区间。
    threshold = residual_quantile(calibration, 0.99) # 校准得到、测试期不更新的漂移告警阈值。
    alerts = np.abs(errors) > threshold # 基于残差尾部的诊断告警，不是因果结构判定。
    alert_indices = np.flatnonzero(alerts) # 首次测试告警位置，若无告警则为空。
    return {
        "forecast_label": "ACTION_CONDITIONED_ONE_STEP_FORECAST", # 当前动作已知，不能称自然演化预测。
        "natural_policy_mixture": "PLANNED_NOT_IMPLEMENTED", # 尚未实现对自然策略的动作边缘化。
        "model": prediction_metrics(errors, width), # 模型经验预测表现。
        "persistence_y_t": prediction_metrics(persistence, persistence_width), # y_t 持续性比较器。
        "interval_nominal_coverage": 0.9, # 校准目标不代表相关序列覆盖保证。
        "calibration_rows": len(calibration), # 冻结阈值所用的当时已知真实反馈数。
        "calibration_unavailable_rows": int(np.sum(~known_calibration)), # 因延迟从校准中排除的行数。
        "calibration_label_cutoff": rows[test_start].origin_time, # 校准结果必须在测试开始前可用。
        "evaluation_as_of": max(row.available_at for row in rows[test_start:]), # 回顾性指标等待固定测试窗全部标签成熟。
        "label_maturity_protocol": "ALL_TEST_LABELS_MATURED", # 不把尚未到达的尾部标签计入当时在线指标。
        "labels_unavailable_at_last_test_origin": sum(row.available_at > rows[-1].origin_time
                                                       for row in rows[test_start:]), # 测试末原点当时未知的标签数。
        "drift_monitor": {
            "label": "PREQUENTIAL_RESIDUAL_TAIL_MONITOR_NOT_CAUSAL_GRAPH_TRUTH", # 明确告警含义。
            "frozen_absolute_residual_threshold": threshold, # 所有测试点共用校准阈值。
            "alert_count": int(np.sum(alerts)), # 超阈值的测试数量。
            "alert_fraction": float(np.mean(alerts)), # 测试序列经验告警比例。
            "first_alert_origin": rows[test_start + int(alert_indices[0])].origin_time if len(alert_indices) else None, # 保留真实时钟，不以数组下标代替。
            "first_alert_available_at": rows[test_start + int(alert_indices[0])].available_at if len(alert_indices) else None, # 告警最早获知时刻。
        },
        "audit_examples": forecast_records, # 可复核的预测先于反馈记录。
    }
