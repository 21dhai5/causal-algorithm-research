"""合成敏感性研究：遗漏混杂、无效特征、块长和标签延迟；不作现实有效性推论。"""

import json
from pathlib import Path
import sys

import numpy as np

# ROOT 只定位本独立项目，不读取其他项目或真实数据。
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from causal_research import run_experiment
from causal_research.models import arrays, design
from causal_research.synthetic import generate_trajectory


def regression_ablation():
    """在固定合成训练窗口比较完整调整、遗漏控制与独立噪声特征，不重选模型。"""
    # errors 保留相对已知真值的逐种子偏差；遗漏变量模型不能作因果解释。
    errors = {"full_adjustment": [], "omit_x_not_identified": [], "add_independent_noise": []}
    for seed in range(20261112, 20261132):
        # rows 和 training 与主实验具有相同的机制和 60% 训练边界。
        rows = generate_trajectory(seed, 1200)
        training = rows[:720]
        # x、y、action 均在动作或结果发生前规定，outcome 只用于已观测训练。
        x, y, action, outcome = arrays(training)
        # full 是正确线性结果模型，reduced 故意省略混杂 x。
        full = design(x, y, action)
        reduced = np.column_stack((np.ones(len(y)), y, action))
        # noise 与轨迹随机流独立，作为无效特征的消融对照。
        noise = np.random.default_rng(seed + 2**32).normal(size=len(y))
        augmented = np.column_stack((full, noise))
        for name, matrix, action_column in (("full_adjustment", full, 3),
                                            ("omit_x_not_identified", reduced, 2),
                                            ("add_independent_noise", augmented, 3)):
            # coefficients 是预先指定模型的拟合量，不按测试结果筛选特征。
            coefficients, _, rank, _ = np.linalg.lstsq(matrix, outcome, rcond=None)
            if rank != matrix.shape[1] or not np.isfinite(coefficients).all():
                raise ValueError("ablation design is rank deficient or nonfinite")
            errors[name].append(float(coefficients[action_column] - 1.5))
    return {name: {"bias_vs_synthetic_truth": float(np.mean(values)),
                   "rmse_vs_synthetic_truth": float(np.sqrt(np.mean(np.square(values)))),
                   "replications": len(values)} for name, values in errors.items()}


def run_sensitivity():
    """按固定探索性方案执行配对块长与延迟场景，完整保留支持拒绝数。"""
    # block_comparison 仅改变区间块长；样本、种子和固定拟合策略保持相同。
    block_comparison = []
    for length in (3, 6, 12):
        # result 的点估计不由块长改变；此处研究近似区间对块长的敏感性。
        result = run_experiment(seed=20261112, samples=1200, replications=20,
                                bootstrap_draws=400, block_length=length)
        block_comparison.append({"config": result["config"], "summary": result["summary"]})
    # delayed 另外演示固定延迟；它不覆盖依赖结果的到达或缺失状态问题。
    delayed = run_experiment(seed=20261212, samples=600, replications=10,
                             bootstrap_draws=400, label_delay=5)
    return {"schema_version": "synthetic-sensitivity-v1", "data_mode": "SYNTHETIC_ONLY",
            "study_type": "EXPLORATORY_NOT_PREREGISTERED_CONFIRMATORY",
            "regression_ablation": regression_ablation(),
            "ablation_scope": "20 training-window coefficient comparisons; omitted-x regression is not identified",
            "block_length_comparison": block_comparison,
            "fixed_delay_experiment": delayed,
            "not_tested": ["hidden_new_confounder", "outcome_dependent_censoring",
                           "structural_support_holes", "full_scoring_correction_replay",
                           "real_world_data", "long_term_policy_value"]}


if __name__ == "__main__":
    # output 固定为本项目下的新报告；独占创建避免覆盖已有研究结果。
    output = ROOT / "artifacts" / "sensitivity-v1.json"
    if output.exists() or output.is_symlink():
        raise SystemExit("report already exists; move the old report explicitly before rerunning")
    # report 仅含本机合成结果，不包含个人路径、凭据或外部资料。
    report = run_sensitivity()
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(report, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print("SYNTHETIC ONLY sensitivity report written: artifacts/sensitivity-v1.json")
