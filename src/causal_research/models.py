"""低维线性结果模型和稳定逻辑回归；仅支持有限值、二元动作与明确冷启动门槛。"""

import numpy as np

from .ledger import DatasetMode, Provenance, Transition


class InsufficientEvidence(ValueError):
    """输入、拟合或重叠不足时关闭估计，避免用数值结果掩盖证据缺口。"""


# 将按时间排序的观测转成列数组，返回 x、历史 y、动作与下一步结果。
def arrays(rows: tuple[Transition, ...] | list[Transition], *, minimum: int = 40):
    if len(rows) < minimum:
        raise InsufficientEvidence(f"cold start: need at least {minimum} observed rows")
    if any(not isinstance(row, Transition) for row in rows):
        raise InsufficientEvidence("every row must be a Transition")
    previous = -1 # 前一行原点，用于阻止乱序或同一时刻重复样本。
    mode = (DatasetMode.SYNTHETIC if rows[0].provenance == Provenance.SYNTHETIC_OBSERVATION
            else DatasetMode.REAL) # 数组也强制来源一致，防止绕过账本混合。
    for row in rows: # 在进入线性代数前完整验证数据。
        row.validate(mode)
        if row.origin_time <= previous:
            raise InsufficientEvidence("rows must have strictly increasing origins")
        previous = row.origin_time
    values = np.asarray([(r.x_t, r.y_t, r.action, r.outcome_y_next) for r in rows],
                        dtype=float) # 每行固定为动作前特征、动作、后续反馈。
    return tuple(values[:, column] for column in range(4))


# 构造带截距的结果设计矩阵；始终保留动作前 x 与 y。
def design(x: np.ndarray, y: np.ndarray, action: np.ndarray) -> np.ndarray:
    return np.column_stack((np.ones_like(x), x, y, action))


# 用最小二乘拟合一步结果；秩不足或非有限输出直接拒绝。
def fit_outcome(rows: tuple[Transition, ...] | list[Transition]) -> np.ndarray:
    x, y, action, outcome = arrays(rows) # 经校验的有标签历史。
    matrix = design(x, y, action) # 四参数线性结果模型。
    coefficients, _, rank, _ = np.linalg.lstsq(matrix, outcome, rcond=None) # 估计条件均值。
    if rank != 4 or not np.isfinite(coefficients).all():
        raise InsufficientEvidence("outcome design is rank deficient or nonfinite")
    return coefficients


# 预测单个已知动作的一步结果，不生成或写入任何反馈。
def predict_outcome(coefficients: np.ndarray, row: Transition) -> float:
    return float(np.dot([1, row.x_t, row.y_t, row.action], coefficients))


# 分支计算 sigmoid，避免极端输入时 exp 溢出。
def expit(values: np.ndarray) -> np.ndarray:
    output = np.empty_like(values, dtype=float) # 与输入形状相同的概率数组。
    positive = values >= 0 # 正负分支均只计算非正指数。
    output[positive] = 1 / (1 + np.exp(-values[positive]))
    exponent = np.exp(values[~positive]) # 负分支的安全指数。
    output[~positive] = exponent / (1 + exponent)
    return output


# 固定训练集拟合标准化逻辑回归；岭项稳定求解，迭代不收敛时拒绝。
def fit_propensity(rows: tuple[Transition, ...] | list[Transition]):
    x, y, action, _ = arrays(rows) # 倾向仅使用动作前状态和已观测动作。
    controls = np.column_stack((x, y)) # 两个前置混杂控制量。
    center = controls.mean(axis=0) # 只由训练集确定的标准化中心。
    scale = controls.std(axis=0) # 只由训练集确定的标准差。
    if np.any(scale < 1e-10) or min(np.sum(action == 0), np.sum(action == 1)) < 20:
        raise InsufficientEvidence("propensity needs variable controls and at least 20 per arm")
    matrix = np.column_stack((np.ones(len(rows)), (controls - center) / scale)) # 标准化设计矩阵。
    coefficients = np.zeros(3) # 三个逻辑回归参数，初始概率为二分之一。
    penalty = np.diag([0, 1e-6, 1e-6]) # 不惩罚截距，微弱惩罚斜率。
    for iteration in range(100): # 迭代上限避免分离数据无限求解。
        probability = expit(matrix @ coefficients) # 本轮条件动作概率。
        gradient = matrix.T @ (action - probability) - penalty @ coefficients # 对数似然梯度。
        hessian = matrix.T @ ((probability * (1 - probability))[:, None] * matrix) + penalty # 正信息阵。
        try:
            step = np.linalg.solve(hessian, gradient) # 牛顿增量。
        except np.linalg.LinAlgError as error:
            raise InsufficientEvidence("propensity information matrix is singular") from error
        current_loss = float(np.sum(np.logaddexp(0, matrix @ coefficients)
                                    - action * (matrix @ coefficients))
                             + coefficients @ penalty @ coefficients / 2) # 稳定的惩罚负对数似然。
        fraction = 1.0 # 回溯步长，必须降低目标值才接受。
        for backtrack in range(30): # 有限回溯次数保证失败可结束。
            candidate = coefficients + fraction * step # 待接受的下一组参数。
            logits = matrix @ candidate # 候选线性预测值。
            candidate_loss = float(np.sum(np.logaddexp(0, logits) - action * logits)
                                   + candidate @ penalty @ candidate / 2) # 候选稳定目标。
            if np.isfinite(candidate_loss) and candidate_loss <= current_loss + 1e-10:
                break
            fraction /= 2
        else:
            raise InsufficientEvidence("propensity line search failed")
        coefficients = candidate
        if np.max(np.abs(fraction * step)) < 1e-8:
            return coefficients, center, scale, iteration + 1
    raise InsufficientEvidence("propensity did not converge in 100 iterations")


# 将训练得到的标准化和系数原样应用到留出样本，禁止重新拟合。
def predict_propensity(model, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    coefficients, center, scale, _ = model # 固定训练参数及其迭代元数据。
    matrix = np.column_stack((np.ones(len(x)), (np.column_stack((x, y)) - center) / scale)) # 测试设计。
    return expit(matrix @ coefficients)
