"""单条序列的已知混杂合成机制；真实疗效与现实可迁移性均不能由此验证。"""

import numpy as np

from .ledger import Provenance, Transition
from .models import expit


# 按状态、动作、结果顺序生成单条轨迹；shift_after 起增加结果均值供漂移实验。
def generate_trajectory(seed: int, samples: int, *, label_delay: int = 0,
                        shift_after: int | None = None, outcome_shift: float = 0) -> list[Transition]:
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("seed must be an integer in [0, 2**32)")
    if type(samples) is not int or samples < 200:
        raise ValueError("samples must be an integer >= 200")
    if type(label_delay) is not int or label_delay < 0:
        raise ValueError("label_delay must be a nonnegative integer")
    if shift_after is not None and (type(shift_after) is not int or not 0 <= shift_after < samples):
        raise ValueError("shift_after must be an origin within the trajectory")
    if not np.isfinite(outcome_shift):
        raise ValueError("outcome_shift must be finite")
    rng = np.random.default_rng(seed) # 单一固定随机流保证同配置可复现。
    rows = [] # 完整合成观测，仅在 available_at 以后允许模型使用。
    x_previous = 0.0 # 外生状态的初始值。
    y_current = 0.0 # 首次决策前的历史结果。
    for origin in range(samples): # 每个循环只产生一步真实生成机制反馈。
        x_current = float(0.6 * x_previous + rng.normal()) # 动作前 AR(1) 控制变量。
        propensity = float(np.clip(expit(np.array([0.8 * x_current - 0.2 * y_current]))[0],
                                   0.1, 0.9)) # 有界随机行为策略，仍受 x、y 混杂。
        action = int(rng.random() < propensity) # 本时刻已知状态下执行的二元动作。
        shift = outcome_shift if shift_after is not None and origin >= shift_after else 0 # 测试期漂移。
        y_next = float(0.5 * y_current + 0.8 * x_current + 1.5 * action
                       + rng.normal() + shift) # 动作效应固定为 1.5，噪声标准差为 1。
        rows.append(Transition(
            row_id=f"synthetic-{seed}-{origin}", # 同种子轨迹内的稳定标识。
            x_t=x_current, # 决策前已知外生变量。
            y_t=y_current, # 决策前已知历史结果。
            action=action, # 本步已执行动作。
            outcome_y_next=y_next, # 机制产生的一步结果，非模型输出。
            origin_time=origin, # 本次决策时刻。
            event_time=origin + 1, # 结果在下一时刻发生。
            available_at=origin + 1 + label_delay, # 固定延迟后方可入训练。
            provenance=Provenance.SYNTHETIC_OBSERVATION, # 禁止把轨迹当实测证据。
        ))
        x_previous = x_current
        y_current = y_next
    return rows
