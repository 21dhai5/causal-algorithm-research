"""可复现的合成研究实验；输出区分相关性、条件因果估计与一步预测。

仅验证已知机制上的实现行为，不验证现实无混杂、正值性、稳定性或真实干预收益。
"""

from dataclasses import replace
import platform
import numpy as np

from .evaluation import estimate_causal, evaluate_prequential, overlap_diagnostics
from .ledger import DatasetMode, ObservationLedger, Provenance, Transition
from .synthetic import generate_trajectory


# 汇总已接受重复的偏差与均方根误差；区间覆盖仅对有有效区间的重复计算。
def summarize_estimator(repetitions: list[dict], field: str, *, truth: float) -> dict:
    valid = [item["causal"][field] for item in repetitions if item["causal"][field] is not None] # 有限估计集合。
    errors = np.asarray(valid, dtype=float) - truth # 相对已知合成一步动作效应的误差。
    result = {
        "valid_replications": len(valid), # 被门槛接受并产生估计的重复数。
        "requested_replications": len(repetitions), # 实际运行的总重复数。
        "bias": float(np.mean(errors)) if len(errors) else None, # 合成真值上的平均偏差。
        "rmse": float(np.sqrt(np.mean(errors**2))) if len(errors) else None, # 合成真值上的均方根误差。
        "empirical_ci_coverage": None, # 只有 AIPW 提供近似条件区间。
    }
    if field == "aipw" and valid:
        result["empirical_ci_coverage"] = float(np.mean([
            item["causal"]["aipw_ci"][0] <= truth <= item["causal"]["aipw_ci"][1]
            for item in repetitions if item["causal"]["aipw_ci"] is not None
        ]))
    return result


# 用研究所需的负对照审计来源、缺失、修订和延迟行为，不引入独立测试脚手架。
def ledger_negative_controls() -> dict:
    original = Transition("audit-0", 0.2, 0.1, 1, 1.7, 0, 1, 3,
                          Provenance.SYNTHETIC_OBSERVATION) # 结果发生于 1、延迟到 3 才可见。
    ledger = ObservationLedger(DatasetMode.SYNTHETIC) # 只接受合成观测。
    ledger.add(original)
    checks = { # 以下布尔项全部必须为真，任何失败都终止实验。
        "current_origin_outcome_hidden": len(ledger.snapshot(0)) == 0, # 当前结果绝不可见。
        "delayed_outcome_hidden_at_event": len(ledger.snapshot(1)) == 0, # 已发生但未到达仍不可用。
        "delayed_outcome_visible_at_availability": ledger.snapshot(3) == (original,), # 恰在可用时出现。
        "exact_duplicate_idempotent": not ledger.add(original), # 重放不增加样本量。
    }
    forbidden = {
        "model_prediction_rejected": replace(original, row_id="prediction", provenance=Provenance.MODEL_PREDICTION), # 预测不是真值。
        "counterfactual_rejected": replace(original, row_id="counterfactual", provenance=Provenance.COUNTERFACTUAL_SIMULATION), # 模拟不是真值。
        "mixed_real_source_rejected": replace(original, provenance=Provenance.REAL_OBSERVATION), # 禁止混合真实与合成。
        "missing_outcome_rejected": replace(original, outcome_y_next=None), # 缺失结果不得转成零或预测。
        "nonfinite_outcome_rejected": replace(original, outcome_y_next=float("nan")), # 非有限值不得入账。
        "conflicting_duplicate_rejected": replace(original, outcome_y_next=2.1), # 冲突要求显式修订。
        "same_origin_new_id_rejected": replace(original, row_id="duplicate-origin"), # 不重复计算同一时点。
        "outcome_at_origin_rejected": replace(original, event_time=0), # 不允许将未来结果伪装为当前已知。
        "availability_before_event_rejected": replace(original, available_at=0), # 到达不能早于事件。
    }
    for name, row in forbidden.items(): # 每项必须触发明确的数据拒绝。
        try:
            ledger.add(row)
        except ValueError:
            checks[name] = True
        else:
            checks[name] = False
    correction = replace(original, outcome_y_next=2.1, available_at=5) # 新反馈只从修订到达时生效。
    ledger.add(correction, correction=True)
    checks["correction_preserves_historical_snapshot"] = ledger.snapshot(3) == (original,)
    checks["correction_visible_only_at_new_availability"] = ledger.snapshot(5) == (correction,)
    zero_delay = replace(original, row_id="zero-delay", available_at=1) # 即时反馈仍须等到下一时刻。
    fresh = ObservationLedger(DatasetMode.SYNTHETIC) # 独立验证零延迟时钟。
    fresh.add(zero_delay)
    checks["zero_delay_does_not_leak_at_origin"] = fresh.snapshot(0) == () and fresh.snapshot(1) == (zero_delay,)
    unsupported = overlap_diagnostics(np.zeros(60), np.full(60, 0.5)) # 缺少动作 1 的支持负对照。
    checks["absent_action_support_refuses_estimation"] = not unsupported["accepted"]
    if not all(checks.values()):
        raise RuntimeError(f"negative control failed: {[name for name, passed in checks.items() if not passed]}")
    return checks


# 执行连续种子的独立轨迹；不读取外部数据、不访问网络、不运行真实干预。
def run_experiment(*, seed: int = 42, samples: int = 1200, replications: int = 30,
                   bootstrap_draws: int = 400, block_length: int | None = None,
                   label_delay: int = 0) -> dict:
    if type(samples) is not int or not 200 <= samples <= 10000:
        raise ValueError("samples must be an integer in [200, 10000]")
    if type(replications) is not int or not 1 <= replications <= 200:
        raise ValueError("replications must be an integer in [1, 200]")
    if type(seed) is not int or not 0 <= seed <= 2**32 - replications:
        raise ValueError("seed and all replication seeds must be in [0, 2**32)")
    if type(bootstrap_draws) is not int or not 100 <= bootstrap_draws <= 2000:
        raise ValueError("bootstrap_draws must be an integer in [100, 2000]")
    train_end = samples * 3 // 5 # 最早 60% 的原点作为固定因果训练段。
    test_start = samples * 4 // 5 # 接下来的 20% 用于预测区间和告警阈值校准。
    if type(label_delay) is not int or not 0 <= label_delay <= min(train_end - 40, test_start - train_end - 40):
        raise ValueError("label_delay must leave at least 40 training and 40 calibration labels available")
    block = max(1, round((samples - test_start)**(1 / 3))) if block_length is None else block_length # 默认立方根块长。
    if type(block) is not int or not 1 <= block <= (samples - test_start) // 2:
        raise ValueError("block_length must be in [1, heldout_samples // 2]")
    controls = ledger_negative_controls() # 负对照在任何正式估计前执行。
    repetitions = [] # 每个种子的完整估计与预测表现，不隐藏拒绝的重复。
    shifted_result = None # 只在首个种子运行一次明确标记的漂移演示。
    for offset in range(replications): # 独立种子、每次一条串行轨迹。
        current_seed = seed + offset # 当前轨迹生成种子。
        rows = generate_trajectory(current_seed, samples, label_delay=label_delay) # 无漂移基准机制。
        ledger = ObservationLedger(DatasetMode.SYNTHETIC) # 用快照确定因果训练段可用标签。
        for row in rows[:train_end]: # 仅固定训练段的原始观测进入该训练账本。
            ledger.add(row)
        training = ledger.snapshot(train_end) # 在校准开始前已到达的训练结果，不从未来补齐。
        causal = estimate_causal(training, rows[test_start:], seed=current_seed + 2**32,
                                 bootstrap_draws=bootstrap_draws, block_length=block) # 测试段因果估计。
        prediction = evaluate_prequential(rows, train_end, test_start) # 时间顺序的一步预测评估。
        repetitions.append({
            "seed": current_seed, # 独立重复所用种子。
            "causal": causal, # 因果与相关性明确区分的结果。
            "prediction": prediction, # 动作已知的一步预测，含持续性基线。
        })
        if offset == 0:
            shifted_rows = generate_trajectory(current_seed, samples, label_delay=label_delay,
                                                shift_after=test_start, outcome_shift=3) # 测试期结果均值增加 3。
            shifted_result = evaluate_prequential(shifted_rows, train_end, test_start) # 同种子、同阈值的漂移对照。
    return {
        "schema_version": "synthetic-research-v1", # 稳定输出结构的版本。
        "provenance": {
            "data_mode": "SYNTHETIC_ONLY", # 所有研究数值来自本地机制生成。
            "efficacy_claim": "NO_REAL_WORLD_EFFICACY_CLAIM", # 不提供真实干预效果证据。
            "generator": "serial_ar1_confounding_v1", # 显式的可复现生成机制标识。
            "python_version": platform.python_version(), # 执行解释器版本。
            "numpy_version": np.__version__, # 数值依赖版本。
            "known_one_step_causal_effect": 1.5, # 生成机制给定的常数动作效应。
        },
        "config": {
            "seed": seed, # 首个轨迹种子。
            "samples": samples, # 每条串行轨迹的原点数。
            "replications": replications, # 连续独立种子数量。
            "bootstrap_draws": bootstrap_draws, # 每次条件块自助重采样次数。
            "block_length": block, # 每个连续重采样块长度。
            "label_delay": label_delay, # 结果发生后额外等待的离散步数。
            "split": {"train": [0, train_end], "calibration": [train_end, test_start],
                      "test": [test_start, samples]}, # 左闭右开，严格按原点时间划分。
            "nuisance_fit": "TRAIN_ONLY_FIXED", # 结果与倾向模型不使用校准或测试数据拟合因果参数。
            "forecast_fit": "PREQUENTIAL_AVAILABLE_OBSERVATIONS_ONLY", # 预测模型可在真实反馈到达后更新。
            "dgp": {
                "x_t": "0.6*x_previous + Normal(0,1)", # 动作前外生 AR(1) 状态。
                "action_probability": "clip(expit(0.8*x_t - 0.2*y_t), 0.1, 0.9)", # 有混杂的随机策略。
                "y_next": "0.5*y_t + 0.8*x_t + 1.5*action + Normal(0,1)", # 已知一步因果效应机制。
                "initial_x_previous": 0, # 固定外生初始条件。
                "initial_y_t": 0, # 固定历史结果初始条件。
                "state_availability": "x_t and y_t measured at origin even when feedback labels are delayed", # 延迟仅约束标签入口。
            },
        },
        "negative_controls": controls, # 可复现的来源、时钟与支持不足实验。
        "summary": {
            "association_only": summarize_estimator(repetitions, "naive_treated_minus_untreated", truth=1.5), # 与真值的差距不使相关性成为因果。
            "adjusted_g_computation": summarize_estimator(repetitions, "g_computation", truth=1.5), # 已接受的调整估计。
            "estimated_propensity_aipw": summarize_estimator(repetitions, "aipw", truth=1.5), # 有效重复上的 AIPW 指标。
            "coverage_denominator": "VALID_REPLICATIONS_ONLY; inspect refusals", # 不把拒绝重复算作成功覆盖。
        },
        "drift_synthetic_comparison": {
            "seed": seed, # 漂移演示仅对应首个种子。
            "outcome_mean_shift": 3, # 测试段开始后每一步的机制均值偏移。
            "shift_origin": test_start, # 漂移首次生效的动作原点。
            "baseline_false_alarm_monitor": repetitions[0]["prediction"]["drift_monitor"], # 无漂移基准中的经验误报。
            "shifted_monitor": shifted_result["drift_monitor"], # 漂移下告警，不证明结构变化。
            "shifted_prediction": shifted_result["model"], # 在线适应后的测试预测表现。
            "scope": "ONE_PAIRED_SYNTHETIC_SEED_DEMONSTRATION", # 不冒充多个场景的综合漂移验证。
        },
        "replications": repetitions, # 含所有拒绝情况的每次重复明细。
        "inference": {
            "ci_label": "APPROXIMATE_CONDITIONAL_MOVING_BLOCK_BOOTSTRAP_FIXED_NUISANCE", # 条件区间的准确身份。
            "ci_nominal_coverage": 0.95, # 名义覆盖，非有限样本承诺。
            "ci_scope": "HELDOUT_AIPW_SCORES_ONLY; excludes nuisance-fit uncertainty", # 不含全流程拟合不确定性。
            "causal_assumptions": ["consistency", "sequential_exchangeability_given_x_t_y_t", "positivity"], # 识别依赖外部假设。
            "limitations": [
                "SYNTHETIC ONLY: cannot establish real-world causal efficacy or external validity.",
                "Available-time filtering prevents label leakage but not informative delay or censoring bias.",
                "Delayed-label simulation assumes current x_t,y_t are separately measured at origin; it is not a missing-state model.",
                "Temporal dependence invalidates ordinary iid coverage arguments; reported intervals are approximate.",
                "Fixed-nuisance block intervals omit training uncertainty; empirical coverage is not a guarantee.",
                "Empirical overlap gates cannot prove population positivity or absence of hidden confounding.",
                "Clipping weights cannot restore identification; this implementation refuses inadequate support.",
                "The clipped generator policy is not exactly logistic; correct linear outcome model helps only in this DGP.",
                "Prequential action-conditioned forecasts use observed current action; natural-policy forecasts are not implemented.",
                "Drift alarms detect residual tails, not causal graph truth; online adaptation can reduce later alarms.",
            ], # 结果解释必须携带的已知限制。
        },
        "planned_not_implemented": ["natural_policy_mixture", "multi_step_forecasting", "reinforcement_learning",
                                    "real_intervention_selection_or_execution", "full_pipeline_inference"], # 明确未实现边界。
    }
