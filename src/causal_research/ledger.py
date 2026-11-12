"""反馈账本：拒绝声明为预测或反事实的输入，来源真实性仍依赖可信接入。

合成与真实数据严格分账。可用时间过滤不能解决信息性延迟、删失或隐匿混杂。
"""

from dataclasses import dataclass
from enum import StrEnum
from numbers import Real
import math


class Provenance(StrEnum):
    """声明记录来源；阻止误用来源类型，不代替外部来源认证。"""

    REAL_OBSERVATION = "real_observation" # 外部实测反馈；原型实验不产生此类记录。
    SYNTHETIC_OBSERVATION = "synthetic_observation" # 已知生成机制产生的合成观测。
    MODEL_PREDICTION = "model_prediction" # 模型输出，禁止作为反馈写入。
    COUNTERFACTUAL_SIMULATION = "counterfactual_simulation" # 反事实模拟，禁止作为反馈写入。


class DatasetMode(StrEnum):
    """指定整个账本允许的观测来源。"""

    REAL = "real" # 仅允许实测反馈。
    SYNTHETIC = "synthetic" # 仅允许合成观测。


@dataclass(frozen=True)
class Transition:
    """一步记录；状态先于动作，结果发生于 origin_time + 1，之后才能获知。"""

    row_id: str # 数据集内稳定标识；修订必须复用原标识。
    x_t: float # 动作前已知的外生状态。
    y_t: float # 动作前已知的历史结果。
    action: int # 已执行的二元动作，取值 0 或 1。
    outcome_y_next: float # 下一时刻实测或合成观测结果，不能填预测。
    origin_time: int # 特征与动作所属离散时刻。
    event_time: int # 结果发生时刻，严格等于 origin_time + 1。
    available_at: int # 结果首次可用或本次修订可用的时刻。
    provenance: Provenance # 明确反馈来源并匹配账本模式。

    # 校验数值、时钟与来源，缺失或歧义输入均拒绝。
    def validate(self, mode: DatasetMode) -> None:
        if not isinstance(self.row_id, str) or not self.row_id.strip():
            raise ValueError("row_id must be a nonempty string")
        for name in ("x_t", "y_t", "outcome_y_next"): # 所有连续字段必须为有限实数。
            value = getattr(self, name) # 当前字段原值，禁止字符串或布尔值隐式转换。
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise ValueError(f"{name} must be a finite real number")
        if type(self.action) is not int or self.action not in (0, 1):
            raise ValueError("action must be integer 0 or 1")
        for name in ("origin_time", "event_time", "available_at"): # 离散时钟不接受浮点取整。
            value = getattr(self, name) # 待验证的时钟字段。
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if self.event_time != self.origin_time + 1:
            raise ValueError("one-step outcome event_time must equal origin_time + 1")
        if self.available_at < self.event_time:
            raise ValueError("available_at must be at least event_time")
        expected = (Provenance.REAL_OBSERVATION if mode == DatasetMode.REAL
                    else Provenance.SYNTHETIC_OBSERVATION) # 模式唯一允许的观测来源。
        if not isinstance(self.provenance, Provenance) or self.provenance != expected:
            raise ValueError("provenance is forbidden for this observation ledger")


class ObservationLedger:
    """按原点时间追加；显式修订保留历史版本，保证过去快照不可被未来修订污染。"""

    # 建立单一来源账本；不持久化、不执行外部操作。
    def __init__(self, mode: DatasetMode):
        self._mode = DatasetMode(mode) # 整个实例固定采用的来源模式。
        self._revisions: dict[str, list[Transition]] = {} # 每行按可用时间保存完整修订历史。
        self._last_origin = -1 # 新记录必须严格晚于前一条新记录。

    # 只读暴露模式，防止正常调用方在入账过程中切换来源。
    @property
    def mode(self) -> DatasetMode:
        return self._mode

    # 原样重复幂等；冲突默认拒绝，显式修订只允许更新同一事件的反馈内容。
    def add(self, row: Transition, *, correction: bool = False) -> bool:
        if not isinstance(row, Transition):
            raise ValueError("only Transition observations can enter the ledger")
        row.validate(self.mode)
        revisions = self._revisions.get(row.row_id) # 已登记的同标识历史，若不存在则为新行。
        if revisions is not None:
            if row in revisions:
                return False
            previous = revisions[-1] # 最近一次已登记版本。
            if not correction:
                raise ValueError("conflicting duplicate requires explicit correction")
            if (row.origin_time, row.event_time, row.x_t, row.y_t, row.action) != (
                    previous.origin_time, previous.event_time, previous.x_t,
                    previous.y_t, previous.action):
                raise ValueError("correction cannot change identity, state, action or event time")
            if row.available_at <= previous.available_at:
                raise ValueError("correction availability must strictly increase")
            revisions.append(row)
            return True
        if correction:
            raise ValueError("correction requires an existing row_id")
        if row.origin_time <= self._last_origin:
            raise ValueError("new rows require strictly increasing origin_time")
        self._revisions[row.row_id] = [row]
        self._last_origin = row.origin_time
        return True

    # 返回查询时刻已知的最新观测版本；当前原点对应的未来结果一定不可见。
    def snapshot(self, as_of: int) -> tuple[Transition, ...]:
        if type(as_of) is not int or as_of < 0:
            raise ValueError("as_of must be a nonnegative integer")
        visible = [] # 查询时点已知、保持原点顺序的观测集合。
        for revisions in self._revisions.values(): # 字典保持首次追加的原点顺序。
            for row in reversed(revisions): # 从最近修订回退到当时已知版本。
                if row.available_at <= as_of:
                    visible.append(row)
                    break
        return tuple(visible)
