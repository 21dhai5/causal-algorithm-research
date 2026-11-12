"""仅合成研究原型：时序过滤不保证因果可识别，区间不保证相关序列覆盖率。

公开数据账本与实验入口；不选择或执行真实干预，不训练多步预测或强化学习。
"""

from .ledger import DatasetMode, ObservationLedger, Provenance, Transition
from .experiment import run_experiment

__all__ = [ # 限定原型公开入口，内部模型不承诺稳定接口。
    "DatasetMode", "ObservationLedger", "Provenance", "Transition", "run_experiment",
]
