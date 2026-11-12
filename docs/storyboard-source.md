# 分镜 MVP 完整源码

以下为本版实际文件的逐字源码快照，没有省略号或伪代码。以仓库中的独立源文件为执行入口；离线分镜仅使用标准库，NumPy依赖属于项目原有的合成因果研究。

重新修改源文件时同步本汇编，避免说明与实现分离。

## src/causal_storyboard/__init__.py

```python
"""可替换解析器的纯 Python 事件分镜入口；导入不执行模型请求或文件操作。"""

from .core import DEFAULT_STYLE, RuleSceneParser, SceneParser, build_storyboard, validate_scene

__all__ = ["DEFAULT_STYLE", "RuleSceneParser", "SceneParser", "build_storyboard", "validate_scene"]  # 对外稳定入口。
```

## src/causal_storyboard/core.py

```python
"""用明确文本与可追溯假设构建分镜；不执行因果效应估计、文件或网络操作。"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Protocol

DEFAULT_STYLE = "简洁写实的连续性故事板，主体与场景外观保持一致"  # 默认呈现设计，不属于原文事实。
_BASES = {"explicit_text", "commonsense_assumption", "unknown"}  # 世界判断允许的证据来源。
_CLOTHING = r"(?:穿(?:红色|蓝色|白色|黑色|黄色|绿色|红|蓝|白|黑|黄|绿)?(?:上衣|外套|T恤|短袖|衬衫|球衣|衣服|衣)的)?"  # 有限衣着词法，不允许吞入其他角色和动词。


class SceneParser(Protocol):
    """解析器只返回可序列化场景；自定义实现可替换有限规则语法。"""

    # 读取原文，返回包含实体、状态、事件与两类关系的字典；失败抛出 ValueError。
    def parse(self, text: str) -> dict: ...


# 将证据来源与原文片段绑定；说明只解释规则或假设，不增加观察事实。
def _evidence(basis: str, quote: str, explanation: str = "") -> dict:
    return {"basis": basis, "quote": quote, "explanation": explanation}


# 统一构造一次事件发生，状态键采用 entity.attribute，值只使用 JSON 标量。
def _event(identifier: str, kind: str, label: str, participants: list,
           quote: str, preconditions: dict, updates: dict, active: dict,
           moments: tuple) -> dict:
    return {
        "id": identifier, "kind": kind, "label": label,  # 事件标识在整个脚本中只表示一次发生。
        "participants": participants, "evidence": _evidence("explicit_text", quote),
        "preconditions": preconditions, "updates": updates, "active_state": active,
        "keyframes": dict(zip(("before", "during", "after"), moments)),  # 单图分别使用一个时刻。
    }


class RuleSceneParser:
    """有限中文语法：踢球撞倒杯子、男孩跑步、猫坐窗边及两个独立分句。"""

    # 拒绝否定、条件、推测以及未建模语法，避免把文本反向解释成肯定事件。
    def parse(self, text: str) -> dict:
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("parse_error: text 必须是 1 至 4000 字符的非空字符串")
        text = text.strip()  # 保留完整原文；只有匹配时去掉两端空白。
        if re.search(r"没有|没|不|未|别|并非|如果|假如|除非|若|可能|也许|是否|[?？]", text):
            raise ValueError("parse_error: 当前规则不支持否定、条件、推测或疑问句")
        scene = {  # A 层场景事实与状态；B 层摄影参数由分镜规划器另行生成。
            "input_text": text, "entities": [], "world": {"setting": "unspecified"},
            "initial_state": {}, "assumptions": [],
            "continuity": {"source": "continuity_design", "design": "固定中性示意场景；原文外观优先，未指明部分简洁无图案",
                           "constraints": ["实体身份和已给外观跨镜不变", "采用同一世界坐标与支撑面", "状态只能在对应事件阶段变化", "同一 occurrence_id 不表示重复发生"]},
            "events": [], "temporal_relations": [], "causal_relations": [], "unresolved_causal_relations": [],
        }
        pattern = (  # 颜色及衣着作为原文描述保留，不推断未出现的服饰或颜色。
            rf"(?P<boy>(?:一个|一名)?{_CLOTHING}男孩)踢(?:了)?(?:一下|一次)?"
            r"(?P<ball>(?:一个|一只)?(?:[红蓝白黑黄绿]色)?足球)[，,]"
            r"(?P<again>(?:[红蓝白黑黄绿]色)?足球|它)滚向"
            r"(?P<table>(?:一张)?(?:低矮的?|低)?桌子)(?:并|[，,](?:然后|随后)?)"
            r"(?:足球|它)?撞倒(?:了)?(?:桌上(?:的)?|桌子上(?:的)?)"
            r"(?P<cup>(?:一个|一只)?(?:[红蓝白黑黄绿]色)?(?:水杯|杯子))[。.!！]?"
        )
        match = re.fullmatch(pattern, text)  # 完整句匹配防止遗漏会改变物理安排的修饰语。
        if match:
            if "色" in match["ball"] and "色" in match["again"] and match["ball"][-4:] != match["again"][-4:]:
                raise ValueError("parse_error: 同一足球出现不一致的颜色描述")
            self._football(scene, match)
        else:
            clauses = re.split(r"[，,；;]?(同时|然后|随后|接着)[，,；;]?", text.rstrip("。.!！"))  # 最多两句。
            if len(clauses) not in (1, 3):
                raise ValueError("parse_error: 只支持单句或带一个明确时间连接词的两个独立分句")
            self._simple(scene, clauses[0])
            if len(clauses) == 3:
                self._simple(scene, clauses[2])
                scene["temporal_relations"].append({
                    "source": "e1", "target": "e2", "relation": "overlaps" if clauses[1] == "同时" else "before",
                    "evidence": _evidence("explicit_text", clauses[1]),
                })
                scene["unresolved_causal_relations"].append({
                    "source": "e1", "target": "e2", "evidence": _evidence("unknown", clauses[1], "连接词只说明先后或同时，未提供因果依据，不加入因果 DAG"),
                })
        validate_scene(scene)
        return scene

    # 将词汇“撞倒”展开为接触和倾倒，并用显式几何假设使地面足球能接触桌上杯子。
    def _football(self, scene: dict, match: re.Match) -> None:
        for identifier in ("boy", "ball", "table", "cup"):  # 固定身份用于跨镜头连续性。
            # label 合并后文明确出现的颜色，不能丢弃同一实体的新外观信息。
            label = match["again"] if identifier == "ball" and "色" in match["again"] else match[identifier]
            scene["entities"].append({"id": identifier, "label": label, "evidence": _evidence("explicit_text", label)})
        scene["world"].update({
            "ground": "同一平整地面", "ball_radius_cm": 11, "tabletop_height_cm": 12,
            "cup_base_radius_cm": 4, "cup_front_overhang_cm": 2,
            "geometry_basis": "commonsense_assumption",  # 尺寸都是为消除缺失空间信息而补充的假设。
            "contact_constraint": "球沿无遮挡地面直接接触低桌前沿外伸的杯身；接触发生在桌缘阻挡之前，球不穿过桌体",
        })
        scene["assumptions"].append(_evidence("commonsense_assumption", "", "原文未给尺寸：采用约12厘米低桌、半径11厘米足球；杯底半径4厘米，前沿外伸2厘米且大部分受桌面支撑；被推倒后仍留在桌面"))
        scene["initial_state"] = {
            "boy.action": "ready_to_kick", "ball.motion": "stationary", "ball.location": "ground_before_table",
            "table.support": "stable", "cup.pose": "upright", "cup.location": "tabletop_front_edge", "cup.contact": "none",
        }
        scene["events"] = [
            _event("e1", "kick", "男孩踢一次足球", ["boy", "ball"], match["boy"] + "踢",
                   {"boy.action": "ready_to_kick", "ball.motion": "stationary"}, {"boy.action": "after_kick", "ball.motion": "rolling"},
                   {"boy.action": "kicking"}, ("脚将接触静止足球", "脚与足球接触的一瞬", "球刚离脚，男孩保持踢后的姿态")),
            _event("e2", "roll", "同一足球沿地面滚向桌前杯子", ["ball", "table"], match["again"] + "滚向" + match["table"],
                   {"ball.motion": "rolling"}, {"ball.location": "within_cup_reach"}, {"ball.location": "approaching_cup"},
                   ("球已离脚，杯子直立", "球在无遮挡地面上接近低桌前沿，尚未接触杯子", "球抵达外伸杯身之前，杯子仍直立")),
            _event("e3", "contact", "足球接触前沿外伸杯身", ["ball", "cup"], "撞倒",
                   {"ball.location": "within_cup_reach", "cup.pose": "upright"}, {"ball.location": "cup_contact_before_table", "ball.motion": "contact_motion_unspecified", "cup.contact": "ball"},
                   {"ball.location": "cup_contact_before_table", "ball.motion": "contact_motion_unspecified", "cup.contact": "ball"},
                   ("球与杯身之间尚有微小间距", "球刚接触外伸杯身，杯子尚未倾倒，接触点在桌缘阻挡之前", "球接触杯身，杯子尚未倾倒，球仍在桌体之外")),
            _event("e4", "tip", "同一水杯向桌面内侧倾倒并留在桌上", ["cup"], "撞倒",
                   {"cup.contact": "ball", "cup.pose": "upright"}, {"cup.pose": "tipped_on_table", "cup.contact": "unspecified_after_tip"}, {"cup.pose": "tilting_inward"},
                   ("杯子受球接触，开始失去直立平衡", "杯子向桌面内侧倾斜，仍与桌面接触", "杯子侧倒且仍留在桌面，足球在桌体外的接触位置")),
        ]
        for source, target in (("e1", "e2"), ("e2", "e3"), ("e3", "e4")):  # 时间顺序单独存放，不由时间自动推出因果。
            scene["temporal_relations"].append({"source": source, "target": target, "relation": "before", "evidence": _evidence("commonsense_assumption", "", "按动作阶段展开的时间安排")})
        scene["causal_relations"] = [
            {"source": "e1", "target": "e2", "relation": "causes", "evidence": _evidence("commonsense_assumption", "", "踢球后球滚动是规则补充，原文没有显式因果连接词")},
            {"source": "e2", "target": "e3", "relation": "enables", "evidence": _evidence("commonsense_assumption", "", "沿无遮挡路径接近杯身是接触的空间前提，不是充分原因")},
            {"source": "e3", "target": "e4", "relation": "causes", "evidence": _evidence("explicit_text", "撞倒", "结果补语明确绑定碰撞与倾倒")},
        ]

    # 仅建模已在进行的动作或静态姿态，不把“坐在”误造为新坐下动作。
    def _simple(self, scene: dict, clause: str) -> None:
        clause = clause.strip().rstrip("。.!！")  # 分句用于保留各自证据片段。
        if re.fullmatch(r"(?:一只)?猫坐在窗边", clause):
            identifier, state, label, moment = "cat", {"cat.pose": "sitting", "cat.location": "by_window"}, "猫持续坐在窗边", "猫坐在窗边的静止姿态"  # 静态事实不创造额外动作。
        elif re.fullmatch(rf"(?:一个|一名)?{_CLOTHING}男孩(?:跑起来|跑了起来)", clause):
            # 起始动词需要真实状态转移，不能在事件开始前就写入 running。
            # appearance 仅保留身份与衣着，避免把未来动作混进每张图片的主体外观。
            appearance = clause[:clause.index("男孩") + 2]
            scene["entities"].append({"id": "boy", "label": appearance, "evidence": _evidence("explicit_text", appearance)})
            if "boy.action" in scene["initial_state"]:
                raise ValueError("parse_error: 当前双分句语法要求两个独立主体")
            scene["initial_state"]["boy.action"] = "ready_to_run"
            scene["events"].append(_event(f"e{len(scene['events']) + 1}", "begin_run", "男孩开始跑步", ["boy"], clause,
                                         {"boy.action": "ready_to_run"}, {"boy.action": "running"}, {"boy.action": "starting_to_run"},
                                         ("男孩尚未开始跑步", "男孩刚开始迈出跑步步伐", "男孩已进入跑步状态")))
            return
        elif re.fullmatch(rf"(?:一个|一名)?{_CLOTHING}男孩(?:在跑步|跑步|奔跑|向前跑)", clause):
            identifier, state, label, moment = "boy", {"boy.action": "running"}, "男孩持续跑步", "男孩跑步过程中的一个步态瞬间"  # 连续动作只表示一次发生。
        else:
            raise ValueError("parse_error: 不支持该动作或空间修饰；支持踢球撞杯、男孩跑步、猫坐窗边")
        if any(entity["id"] == identifier for entity in scene["entities"]):
            raise ValueError("parse_error: 当前双分句语法要求两个独立主体")
        # appearance 与动作事件分开存储，使角色设定不会强迫每个关键帧重复动作。
        appearance = clause[:clause.index("猫") + 1] if identifier == "cat" else clause[:clause.index("男孩") + 2]
        scene["entities"].append({"id": identifier, "label": appearance, "evidence": _evidence("explicit_text", appearance)})
        scene["initial_state"].update(state)
        scene["events"].append(_event(f"e{len(scene['events']) + 1}", "ongoing", label, [identifier], clause, state, state, state, (moment, moment, moment)))


# 检查显式证据可回溯；常识假设允许无引文，但必须明确标记。
def _check_evidence(evidence: dict, text: str) -> None:
    if not isinstance(evidence, dict) or not isinstance(evidence.get("basis"), str) or evidence["basis"] not in _BASES or not isinstance(evidence.get("quote"), str):
        raise ValueError("scene_error: evidence 需要合法 basis 和字符串 quote")
    if evidence["basis"] == "explicit_text" and (not evidence["quote"] or (text and evidence["quote"] not in text)):
        raise ValueError("scene_error: explicit_text 的 quote 必须来自输入原文")


# 拓扑排序同时约束 before 与因果边；返回顺序，不依赖输入事件数组的排列。
def _ordered(scene: dict) -> list:
    pending = {event["id"]: event for event in scene["events"]}  # 未安排的事件保持解析器给出的稳定顺序。
    dependencies = {identifier: set() for identifier in pending}  # 每个事件尚需完成的前置事件。
    for relation in scene["temporal_relations"] + scene["causal_relations"]:  # 因果边也必须遵守先因后果。
        if relation.get("relation") != "overlaps":
            dependencies[relation["target"]].add(relation["source"])
    result = []  # 已完成拓扑排序的事件。
    while pending:
        ready = [identifier for identifier in pending if not dependencies[identifier]]  # 本轮无前置依赖的节点。
        if not ready:
            raise ValueError("scene_error: before / causal 关系存在有向环")
        for identifier in ready:  # 删除已处理依赖，最多处理有限数量的事件。
            result.append(pending.pop(identifier))
        for predecessors in dependencies.values():  # 更新剩余节点的前置集合。
            predecessors.difference_update(ready)
    return result


# 校验解析器输出、状态前置与 DAG；仅允许全程同时的独立事件，不猜测复杂并行调度。
def validate_scene(scene: dict) -> None:
    if not isinstance(scene, dict):
        raise ValueError("scene_error: parser 必须返回字典")
    try:
        json.dumps(scene, allow_nan=False)  # 包括世界和连续性附加字段在内，全部输出都必须能序列化。
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError("scene_error: 场景必须是有限且无循环引用的 JSON 数据") from error
    for key, expected in (("entities", list), ("world", dict), ("initial_state", dict), ("assumptions", list), ("continuity", dict), ("events", list), ("temporal_relations", list), ("causal_relations", list)):
        if not isinstance(scene.get(key), expected):
            raise ValueError(f"scene_error: 缺少或无效字段 {key}")
    if not scene["entities"] or not 1 <= len(scene["events"]) <= 120:
        raise ValueError("scene_error: 需要实体和 1 至 120 个事件")
    text = scene.get("input_text", "")  # 自定义解析器可由 build_storyboard 补入原文。
    if not isinstance(text, str):
        raise ValueError("scene_error: input_text 必须是字符串")
    identifiers = set()  # 实体身份集合，用于验证参与者与状态归属。
    for entity in scene["entities"]:  # 实体必须有可回溯证据。
        if not isinstance(entity, dict) or not isinstance(entity.get("id"), str) or not entity["id"] or entity["id"] in identifiers or not isinstance(entity.get("label"), str):
            raise ValueError("scene_error: entity 的 id / label 无效或 id 重复")
        identifiers.add(entity["id"])
        _check_evidence(entity.get("evidence"), text)
    event_ids = set()  # 事件身份与实体身份分开验证。
    for event in scene["events"]:  # 状态字段验证禁止嵌入不可序列化对象或未知实体。
        if not isinstance(event, dict) or not isinstance(event.get("id"), str) or not event["id"] or event["id"] in event_ids:
            raise ValueError("scene_error: event id 无效或重复")
        event_ids.add(event["id"])
        if not isinstance(event.get("label"), str) or not isinstance(event.get("kind"), str) or not isinstance(event.get("participants"), list) or not event["participants"] or any(not isinstance(participant, str) or participant not in identifiers for participant in event["participants"]):
            raise ValueError("scene_error: event label / kind / participants 无效")
        _check_evidence(event.get("evidence"), text)
        for key in ("preconditions", "updates", "active_state"):  # 活动状态只用于该事件进行期间的连续帧。
            if not isinstance(event.get(key), dict):
                raise ValueError(f"scene_error: event 缺少状态字段 {key}")
        if not isinstance(event.get("keyframes"), dict) or any(not isinstance(event["keyframes"].get(phase), str) or not event["keyframes"][phase] for phase in ("before", "during", "after")):
            raise ValueError("scene_error: keyframes 需要 before / during / after 单时刻描述")
    for state in [scene["initial_state"]] + [event[key] for event in scene["events"] for key in ("preconditions", "updates", "active_state")]:  # 状态不可指向未声明实体。
        if any(not isinstance(key, str) or "." not in key or key.split(".")[0] not in identifiers or not isinstance(value, (str, int, float, bool, type(None))) or isinstance(value, float) and not Decimal(str(value)).is_finite() for key, value in state.items()):
            raise ValueError("scene_error: 状态键必须是已声明实体的 entity.attribute，值为有限 JSON 标量")
    for assumption in scene["assumptions"]:  # 所有空间等补充假设都保留证据来源。
        _check_evidence(assumption, text)
    for relation in scene["temporal_relations"] + scene["causal_relations"]:  # 端点与证据先校验，再检查有向环。
        if not isinstance(relation, dict) or not isinstance(relation.get("source"), str) or not isinstance(relation.get("target"), str) or relation["source"] not in event_ids or relation["target"] not in event_ids or relation["source"] == relation["target"]:
            raise ValueError("scene_error: relation 端点无效")
        _check_evidence(relation.get("evidence"), text)
    if any(relation.get("relation") not in ("before", "overlaps") for relation in scene["temporal_relations"]):
        raise ValueError("scene_error: temporal relation 仅支持 before / overlaps")
    if any(relation.get("relation") not in (None, "causes", "enables") for relation in scene["causal_relations"]):
        raise ValueError("scene_error: causal relation 不能使用时间关系类型")
    if any(relation["evidence"]["basis"] == "unknown" for relation in scene["causal_relations"]):
        raise ValueError("scene_error: 未知因果只能保存为 unresolved_causal_relations，不能加入因果 DAG")
    # unresolved 只保存待确认关系，不参与拓扑约束或生成确定因果结论。
    unresolved = scene.get("unresolved_causal_relations", [])
    if not isinstance(unresolved, list):
        raise ValueError("scene_error: unresolved_causal_relations 必须为列表")
    for relation in unresolved:
        if (not isinstance(relation, dict) or not isinstance(relation.get("source"), str)
                or not isinstance(relation.get("target"), str) or relation["source"] not in event_ids or relation["target"] not in event_ids):
            raise ValueError("scene_error: 未知关系端点无效")
        _check_evidence(relation.get("evidence"), text)
    ordered = _ordered(scene)  # 验证与分镜规划共用一致的事件顺序。
    parallel = any(relation["relation"] == "overlaps" for relation in scene["temporal_relations"])  # 当前并行模型要求全部事件同时开始和结束。
    if parallel:
        pairs = {frozenset((relation["source"], relation["target"])) for relation in scene["temporal_relations"] if relation["relation"] == "overlaps"}  # 全并行需要覆盖每对事件。
        if scene["causal_relations"] or any(relation["relation"] == "before" for relation in scene["temporal_relations"]) or len(pairs) != len(ordered) * (len(ordered) - 1) // 2:
            raise ValueError("scene_error: 仅支持无因果边、无 before 边的完整同时分句")
        touched = set()  # 并行事件不能同时写同一状态键，避免合并顺序改变结果。
        for event in ordered:
            if touched.intersection(event["updates"] | event["active_state"]):
                raise ValueError("scene_error: 并行事件写入同一状态")
            touched.update(event["updates"] | event["active_state"])
    state = scene["initial_state"].copy()  # 按因果与时间顺序执行状态，不能提前获得未来结果。
    for event in ordered:
        current = scene["initial_state"] if parallel else state  # 并行事件都从共同初态读取前置条件。
        if any(key not in current or current[key] != value for key, value in event["preconditions"].items()):
            raise ValueError(f"scene_error: {event['id']} 前置状态不成立，可能引用未来动作结果")
        state.update(event["updates"])


# 在指定微观时刻计算全场景状态；结果只包含已完成更新及正在进行的阶段状态。
def _state_at(initial: dict, timeline: list, moment: Decimal) -> dict:
    state = initial.copy()  # 每次返回独立快照，避免镜头之间共享可变字典。
    for entry in timeline:  # 拓扑顺序处理已完成事件；未开始事件不修改状态。
        if moment >= entry["_end"]:
            state.update(entry["event"]["updates"])
        elif moment > entry["_start"]:
            state.update(entry["event"]["active_state"])
    return state


# 按有限持续时间分配同一批事件，并生成严格连续的固定数量镜头；不调用模型或读写文件。
def build_storyboard(text: str, duration: float = 6, shots: int = 3,
                     style: str = DEFAULT_STYLE, parser: SceneParser | None = None) -> dict:
    if isinstance(duration, bool) or not isinstance(duration, (int, float, Decimal)):
        raise ValueError("duration 必须是有限正数秒")
    try:
        total = Decimal(str(duration))  # Decimal 避免累加浮点误差；最后端点由原始总长直接计算。
    except InvalidOperation as error:
        raise ValueError("duration 必须是有限正数秒") from error
    if not total.is_finite() or not 0 < total <= 3600:
        raise ValueError("duration 必须在 (0, 3600] 秒内")
    if type(shots) is not int or not 1 <= shots <= 60:
        raise ValueError("shots 必须是 1 至 60 的整数")
    if not isinstance(style, str) or not style.strip() or len(style) > 2000:
        raise ValueError("style 必须是 1 至 2000 字符的非空字符串")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("parse_error: text 必须是 1 至 4000 字符的非空字符串")
    parsed = deepcopy((parser if parser is not None else RuleSceneParser()).parse(text))  # 不修改调用方的解析器缓存。
    if not isinstance(parsed, dict):
        raise ValueError("scene_error: parser 必须返回字典")
    parsed["input_text"] = text
    validate_scene(parsed)
    events = _ordered(parsed)  # 即使自定义解析器倒序返回，规划仍严格先因后果。
    if total < Decimal(max(shots, len(events))) / 1000000:
        raise ValueError("duration 太短：每个镜头和顺序事件至少需要 1 微秒")
    parallel = any(relation["relation"] == "overlaps" for relation in parsed["temporal_relations"])  # 完整并行沿共同时间区间运行。
    # units 仅分配呈现时长，不表示测得的物理耗时；接触和结果各占运动阶段的一半。
    units = [2 if event["kind"] in ("kick", "roll") else 1 for event in events]
    total_units = sum(units)  # 只计算一次总权重，避免每个事件重复求和。
    if not parallel and total < Decimal(total_units) / (min(units) * 1000000):
        raise ValueError("duration 太短：最短事件阶段至少需要 1 微秒")
    elapsed = 0  # 已分配的整数时间权重，避免反复累加小数。
    timeline = []  # 每个事件在故事时间上只发生一次；并行使用共同区间。
    for index, event in enumerate(events):
        timeline.append({"event": event, "_start": Decimal(0) if parallel else total * elapsed / total_units,
                         "_end": total if parallel or index == len(events) - 1 else total * (elapsed + units[index]) / total_units})
        elapsed += units[index]
    planned = []  # B 层镜头列表；摄影设计不回写世界状态。
    for index in range(shots):  # 共享分割公式保证相邻镜头端点完全一致。
        start = Decimal(0) if index == 0 else total * index / shots  # 起点直接固定零，内部共享同一分割公式。
        end = total if index == shots - 1 else total * (index + 1) / shots  # 最后端点直接使用原始总长，防止高精度舍入分叉。
        covered = [entry for entry in timeline if entry["_start"] < end and entry["_end"] > start]  # 严格相交避免边界上的伪覆盖。
        key = covered[-1]  # 单图选择本镜头最后涉及的事件时刻，不把多阶段动作拼在同一图。
        moment = min(end, key["_end"])  # 图像时刻不超出镜头；精确完成时使用事后状态。
        phase = "after" if moment >= key["_end"] else "during"  # 已完成事件绝不重新回到动作前状态。
        state = _state_at(parsed["initial_state"], timeline, moment)  # 图像世界状态独立于摄影机设计。
        presentation = {  # 摄影机与主体运动显式分开；声音和剪辑只作为元数据。
            "shot_size": "中景" if index else "全景", "height": "主体所在平面附近，能够看清已有支撑面", "pitch": "轻微俯视",
            "camera_movement": "固定机位", "composition": "保持主体、运动方向与空间关系清晰",
            "light_color": "中性柔光；保留原文指定颜色", "edit": "连续切换", "sound": "未指定",
        }
        refs = [  # 重复引用细分的是同一事件发生；不会创造第二次踢球。
            {"event_id": entry["event"]["id"], "occurrence_id": entry["event"]["id"],
             "stage": "whole" if start <= entry["_start"] and end >= entry["_end"] else "completion" if end >= entry["_end"] else "onset" if start <= entry["_start"] else "continuation"}
            for entry in covered
        ]
        descriptions = "；".join(entry["event"]["label"] for entry in covered)  # 脚本描述可涵盖多个动作阶段，单图提示词另选一个时刻。
        prompt = (f"风格：{style}。主体原文描述：{[entity['label'] for entity in parsed['entities']]}。连续性设计：{parsed['continuity']}。"
                  f"世界空间约束：{parsed['world']}。只画一个具体瞬间：{key['event']['keyframes'][phase]}。"
                  f"该瞬间完整状态：{state}。摄影设计：{presentation}。"
                  "原文只作为身份和外观依据；只展示上述时刻的姿态，不在单图内串联完整动作，不添加原文之外的泼洒、破碎、反应、跳跃或新角色。")
        planned.append({
            "id": f"s{index + 1:02d}", "start_s": float(start), "end_s": float(end),
            "event_ids": [entry["event"]["id"] for entry in covered], "event_refs": refs,
            "description": f"同一发生的阶段细分：{descriptions}", "start_state": _state_at(parsed["initial_state"], timeline, start),
            "end_state": _state_at(parsed["initial_state"], timeline, end), "keyframe": {"time_s": float(moment), "event_id": key["event"]["id"], "phase": phase, "state": state},
            "presentation": presentation, "image_prompt": prompt, "image": {"status": "not_requested", "path": None},
        })
    return {
        "schema_version": "1.0", "input_text": text, "duration_s": float(total),
        "overall_scene_description": text.strip() + " 统一空间和外观：" + str(parsed["continuity"].get("design", "保持已声明实体属性"))
                                     + "。" + "；".join(item.get("explanation", "") for item in parsed["assumptions"]),
        "modeling_scope": "RULE/TEXT 事件模型：显式文本、常识假设与未知分开；时间先后不自动构成因果；不作严格因果效应推断",
        "scene": {key: parsed[key] for key in ("entities", "world", "initial_state", "assumptions", "continuity")},
        "events": events, "temporal_relations": parsed["temporal_relations"], "causal_relations": parsed["causal_relations"],
        "unresolved_causal_relations": parsed.get("unresolved_causal_relations", []),
        "timeline": [{"event_id": entry["event"]["id"], "start_s": float(entry["_start"]), "end_s": float(entry["_end"])} for entry in timeline],
        "shots": planned,
    }
```

## src/causal_storyboard/images.py

```python
"""可选图像适配器：只接受验证过的 PNG，绝不下载响应中的 URL。"""

import base64
import binascii
from http.client import HTTPException
import json
import math
import os
from pathlib import Path
import re
import struct
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zlib

MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 单张 PNG 的压缩文件上限。
MAX_RESPONSE_BYTES = 30 * 1024 * 1024  # HTTP 响应的读取上限。
GENERATION_KIND = "STORYBOARD_STILL_IMAGES_NOT_CONTINUOUS_VIDEO"  # 明确产物为分镜静帧。
_DEPTHS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}  # PNG 合法色深。


class ImageGenerationError(ValueError):
    """保存可公开的固定错误信息，不携带服务凭据或响应正文。"""


class ImageProvider(Protocol):
    # 返回 PNG 字节；调用方仍会独立验证内容后才保存。
    def generate(self, prompt: str) -> bytes: ...


class _NoRedirect(HTTPRedirectHandler):
    # 禁止任何重定向，避免授权头与付费请求被转发。
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ImageGenerationError("图像服务重定向已拒绝。")


# 计算普通或 Adam7 PNG 的各扫描段，用于有界解压与逐行过滤器验证。
def _scanlines(width: int, height: int, depth: int, color: int, interlace: int) -> list[tuple[int, int]]:
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]  # 每像素通道数。
    passes = ((0, 0, 1, 1),) if not interlace else (  # Adam7 各遍的起点与步长。
        (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
        (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
    )
    rows = []  # 每段的行字节数与行数，不含行首过滤器字节。
    for x, y, dx, dy in passes:  # 当前遍的采样位置。
        columns = max(0, (width - x + dx - 1) // dx)  # 当前遍宽度。
        count = max(0, (height - y + dy - 1) // dy)  # 当前遍高度。
        if columns and count:
            rows.append(((columns * channels * depth + 7) // 8, count))
    return rows


# 校验像素数据并移除非像素辅助元数据，避免损坏元数据导致有效像素文件无法读取。
def _validate_png(data: bytes) -> bytes:
    if not isinstance(data, bytes) or len(data) > MAX_IMAGE_BYTES or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ImageGenerationError("图像不是大小受限的有效 PNG。")
    offset = 8  # 下一个 PNG 块的文件偏移。
    header = None  # 已验证的 IHDR 字段。
    palette = False  # 索引色必须在 IDAT 前提供调色板。
    idat_state = 0  # 0 未开始、1 连续读取中、2 数据块已经结束。
    compressed = bytearray()  # 所有连续 IDAT 组成的单一 zlib 流。
    chunks = 0  # 限制恶意碎片块数量。
    ended = False  # 只有末尾合法 IEND 才能完成验证。
    raster = bytearray(data[:8])  # 仅保留构成静态像素所需的块，不保留文本、色彩配置或动画元数据。
    palette_entries = 0  # 索引透明度长度不能超过调色板条目数。
    transparency = False  # 透明度块不能重复，且必须位于数据块之前。
    while offset + 12 <= len(data):
        size = struct.unpack_from(">I", data, offset)[0]  # 当前块负载长度。
        kind = data[offset + 4:offset + 8]  # 四字节 PNG 块名称。
        end = offset + 8 + size  # CRC 前的位置。
        chunks += 1
        if end + 4 > len(data) or chunks > 4096 or not kind.isalpha() or kind[2] & 32:
            raise ImageGenerationError("PNG 块结构无效。")
        payload = data[offset + 8:end]  # CRC 验证后的块负载。
        if zlib.crc32(data[offset + 4:end]) != struct.unpack_from(">I", data, end)[0]:
            raise ImageGenerationError("PNG 校验和无效。")
        if header is None and kind != b"IHDR":
            raise ImageGenerationError("PNG 缺少首部。")
        if kind == b"IHDR":
            if header is not None or size != 13:
                raise ImageGenerationError("PNG 首部无效。")
            header = struct.unpack(">IIBBBBB", payload)
            width, height, depth, color, compression, filtering, interlace = header  # 尺寸与编码参数。
            if not (0 < width <= 8192 and 0 < height <= 8192 and width * height <= 16777216):
                raise ImageGenerationError("PNG 尺寸超出限制。")
            if depth not in _DEPTHS.get(color, ()) or compression or filtering or interlace not in (0, 1):
                raise ImageGenerationError("PNG 编码参数无效。")
        elif kind == b"PLTE":
            if palette or idat_state or color in (0, 4) or not size or size % 3 or size > 768:
                raise ImageGenerationError("PNG 调色板无效。")
            if color == 3 and size // 3 > 2 ** depth:
                raise ImageGenerationError("PNG 调色板超出色深。")
            palette = True
            palette_entries = size // 3
        elif kind == b"tRNS":
            if transparency or idat_state or color not in (0, 2, 3):
                raise ImageGenerationError("PNG 透明度块顺序或颜色类型无效。")
            if ((color == 0 and size != 2) or (color == 2 and size != 6)
                    or (color == 3 and (not palette or not 0 < size <= palette_entries))):
                raise ImageGenerationError("PNG 透明度块长度无效。")
            if color in (0, 2) and any(value >= 2 ** depth for value in struct.unpack(">" + "H" * (size // 2), payload)):
                raise ImageGenerationError("PNG 透明度样本超出色深。")
            transparency = True
        elif kind == b"IDAT":
            if idat_state == 2 or color == 3 and not palette:
                raise ImageGenerationError("PNG 数据块顺序无效。")
            idat_state = 1
            compressed.extend(payload)
        elif kind == b"IEND":
            if size or not idat_state:
                raise ImageGenerationError("PNG 结束块无效。")
            ended = True
        elif not kind[0] & 32:
            raise ImageGenerationError("PNG 包含未知关键块。")
        if kind in (b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"):
            raster.extend(data[offset:end + 4])
        if kind != b"IDAT" and idat_state == 1:
            idat_state = 2
        offset = end + 4
        if ended:
            break
    if not ended or offset != len(data):
        raise ImageGenerationError("PNG 文件不完整。")
    rows = _scanlines(width, height, depth, color, interlace)  # 各遍应有的扫描行布局。
    expected = sum((size + 1) * count for size, count in rows)  # 解压后字节数上限。
    if expected > 64 * 1024 * 1024:
        raise ImageGenerationError("PNG 解压尺寸超出限制。")
    inflater = zlib.decompressobj()  # 只接受一个完整压缩流。
    try:
        raw = inflater.decompress(compressed, expected + 1)  # 多读一个字节以识别解压炸弹。
    except zlib.error:
        raise ImageGenerationError("PNG 压缩内容无效。") from None
    if len(raw) != expected or not inflater.eof or inflater.unused_data or inflater.unconsumed_tail:
        raise ImageGenerationError("PNG 扫描数据不完整或超出限制。")
    position = 0  # 当前扫描行过滤器的位置。
    for size, count in rows:  # 当前遍的行长与行数。
        for _ in range(count):
            if raw[position] > 4:
                raise ImageGenerationError("PNG 行过滤器无效。")
            position += size + 1
    return bytes(raster)


# 拒绝符号链接和 Windows 目录联接，调用方必须提供已存在的真实父目录。
def _check_directory_path(directory: Path) -> None:
    for part in (directory, *directory.parents):  # 逐级检查，避免解析时悄悄跟随链接。
        if part.is_symlink() or part.is_junction():
            raise ValueError("输出路径不能经过符号链接或目录联接。")


# 独占创建明确指定的新目录；已有目录和文件均拒绝，不清理用户数据。
def reserve_output_directory(directory: str | Path) -> Path:
    target = Path(directory).absolute()  # 保留待检查的路径，不先解析符号链接。
    _check_directory_path(target)
    target.mkdir(exist_ok=False)
    return target


class HttpImageProvider:
    # 仅保存私有配置；默认对象 repr 不显示端点、模型或密钥。
    def __init__(self, endpoint: str, model: str, key: str, *, timeout: float = 120):
        try:
            parsed = urlsplit(endpoint)  # 在创建请求前检查目标与凭据边界。
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None or "#" in endpoint
                    or any(character.isspace() or ord(character) < 32 for character in endpoint)
                    or parsed.scheme == "http" and parsed.hostname not in ("localhost", "127.0.0.1", "::1")):
                raise ValueError
            parsed.port  # 提前拒绝非法端口，避免请求时泄露目标字符串。
            if not model.strip() or not key.strip() or not math.isfinite(timeout) or not 0 < timeout <= 120:
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise ImageGenerationError("图像配置无效；远程端点必须使用 HTTPS，超时必须在 120 秒内。") from None
        self._endpoint = endpoint  # 用户显式指定的完整 POST 端点，不自动拼接路径。
        self._model = model  # 当前端点要求的模型标识。
        self._key = key  # 仅用于请求授权头，不进入输出或 repr。
        self._timeout = timeout  # 单次请求超时秒数，不自动重试以免重复计费。

    # 只有三个必需环境变量齐全才能创建实际服务适配器。
    @classmethod
    def from_env(cls) -> "HttpImageProvider":
        endpoint = os.environ.get("STORYBOARD_IMAGE_URL", "")  # 明确选定的 API 端点。
        model = os.environ.get("STORYBOARD_IMAGE_MODEL", "")  # 服务端模型标识。
        key = os.environ.get("STORYBOARD_IMAGE_KEY", "")  # 环境密钥，不接受命令行参数。
        if not endpoint or not model or not key:
            raise ImageGenerationError("缺少图像配置：需要 STORYBOARD_IMAGE_URL、STORYBOARD_IMAGE_MODEL、STORYBOARD_IMAGE_KEY。")
        return cls(endpoint, model, key)

    # 单次 POST 兼容约定的 JSON 架构；只读取 base64 PNG，不重试、不跟随 URL。
    def generate(self, prompt: str) -> bytes:
        body = json.dumps({"model": self._model, "prompt": prompt, "n": 1, "size": "1024x1024", "output_format": "png"}).encode("utf-8")  # 明确请求一张 PNG。
        try:
            request = Request(self._endpoint, data=body, headers={"Authorization": "Bearer " + self._key, "Content-Type": "application/json"}, method="POST")  # 密钥仅在授权头内传送。
            with build_opener(_NoRedirect()).open(request, timeout=self._timeout) as response:  # 禁止任何自动重定向。
                if not 200 <= response.getcode() < 300:
                    raise ImageGenerationError("图像服务未返回成功状态。")
                payload = response.read(MAX_RESPONSE_BYTES + 1)  # 不信任 Content-Length。
        except HTTPError as error:  # 只暴露合法状态码，不读取或打印错误正文。
            status = error.code if isinstance(error.code, int) and 100 <= error.code <= 599 else 0  # 安全状态码。
            error.close()
            raise ImageGenerationError(f"图像服务 HTTP 错误（状态 {status}）。") from None
        except (URLError, OSError, HTTPException, ValueError, UnicodeError):
            raise ImageGenerationError("图像服务请求失败。") from None
        if len(payload) > MAX_RESPONSE_BYTES:
            raise ImageGenerationError("图像服务响应超出大小限制。")
        try:
            encoded = json.loads(payload)["data"][0]["b64_json"]  # 仅支持内嵌 PNG，不处理响应 URL。
            if not isinstance(encoded, str) or len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
                raise ValueError
            image = base64.b64decode(encoded, validate=True)  # 严格解码并拒绝非 base64 数据。
        except (ValueError, KeyError, IndexError, TypeError, binascii.Error, RecursionError):
            raise ImageGenerationError("图像服务必须返回大小受限的 base64 PNG。") from None
        return _validate_png(image)


# 更新每个镜头的真实生成状态；独占保存成功后才公开相对路径，失败不阻断后续镜头。
def generate_images(board: dict, provider: ImageProvider, directory: str | Path) -> dict:
    target = Path(directory).absolute()  # 只能写入调用方显式提供的目录。
    _check_directory_path(target)
    if not target.is_dir():
        raise ValueError("图像输出目录必须预先保留。")
    board["generation_kind"] = GENERATION_KIND
    seen = set()  # 已处理镜头标识，拒绝重名以避免重复请求与覆盖。
    for shot in board["shots"]:  # 每个镜头单独生成、校验和保存。
        shot["image"] = {"status": "failed", "path": None, "error": "图像生成或保存失败。"}
        try:
            shot_id = shot["id"]  # 文件名只允许受约束的镜头标识。
            if not isinstance(shot_id, str) or not re.fullmatch(r"s[0-9]{2,6}", shot_id) or shot_id in seen:
                continue
            seen.add(shot_id)
            path = target / (shot_id + ".png")  # 不使用供应方提供的任何文件名或路径。
            if path.exists() or path.is_symlink():
                continue
            image = _validate_png(provider.generate(shot["image_prompt"]))  # 验证并规范化实际供应方返回的像素内容。
            _check_directory_path(target)  # 长时间请求后再次检查，拒绝期间被替换为链接的目录。
            with path.open("xb") as output:  # 独占创建，已有文件永不覆盖。
                output.write(image)
            shot["image"] = {"status": "generated", "path": path.name}
        except Exception:  # 不输出任意供应方异常，防止凭据及正文随错误泄露。
            continue
    return board
```

## src/causal_storyboard/cli.py

```python
"""标准库命令行：默认只规划分镜，图像请求必须由用户明确启用。"""

import argparse
import json
from pathlib import Path
import sys

from .images import GENERATION_KIND, HttpImageProvider, ImageGenerationError, generate_images, reserve_output_directory


# 解析输入、先完成规划和配置检查，再独占创建目录并保存结果；部分图像失败返回 3。
def main(argv: list[str] | None = None) -> int:
    # 标准输出固定为 UTF-8，使 Windows 管道中的中文 JSON 也能跨平台读取。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="生成因果分镜 JSON；可选择调用已配置的图像服务生成静帧。")  # 公开且不含密钥参数的接口。
    parser.add_argument("--text", required=True, help="要规划的短文本")
    parser.add_argument("--duration", type=float, default=6, help="总时长（秒），默认 6")
    parser.add_argument("--shots", type=int, default=3, help="镜头数量，默认 3")
    parser.add_argument("--style", help="可选风格描述，默认使用核心规划器风格")
    parser.add_argument("--output", type=Path, help="在已存在父目录中创建的新输出目录；已有目标会被拒绝")
    parser.add_argument("--generate-images", action="store_true", help="显式启用可能计费的图像请求；必须提供 --output 和三个图像环境变量")
    try:
        options = parser.parse_args(argv)  # argparse 的退出转换为可测试的整数返回值。
    except SystemExit as error:
        return int(error.code)
    if options.generate_images and options.output is None:
        print("错误：--generate-images 必须同时提供 --output。", file=sys.stderr)
        return 2
    try:
        from .core import build_storyboard  # 延迟导入，避免规划核心与可选图像适配器相互耦合。

        kwargs = {"duration": options.duration, "shots": options.shots}  # 核心参数保持单一来源。
        if options.style is not None:
            kwargs["style"] = options.style
        board = build_storyboard(options.text, **kwargs)  # 输入失败时尚未创建任何输出目录。
        board["generation_kind"] = GENERATION_KIND
        provider = HttpImageProvider.from_env() if options.generate_images else None  # 环境配置本身不会触发请求。
        if options.output is not None:
            directory = reserve_output_directory(options.output)  # 原子拒绝已有目标。
            if provider is not None:
                generate_images(board, provider, directory)
            with (directory / "storyboard.json").open("x", encoding="utf-8") as output:  # 即使部分镜头失败也保存状态。
                json.dump(board, output, ensure_ascii=False, indent=2, allow_nan=False)
                output.write("\n")
        else:
            print(json.dumps(board, ensure_ascii=False, indent=2, allow_nan=False))
        return 3 if any(shot["image"]["status"] == "failed" for shot in board["shots"]) else 0
    except ImageGenerationError:
        print("错误：图像配置无效；请检查 STORYBOARD_IMAGE_URL、STORYBOARD_IMAGE_MODEL、STORYBOARD_IMAGE_KEY 和 HTTPS 端点。", file=sys.stderr)
        return 2
    except ValueError:
        print("错误：文本无法解析、分镜参数不合法，或输出路径经过符号链接。", file=sys.stderr)
        return 2
    except OSError:
        print("错误：无法独占创建输出目录或写入结果；请使用已有父目录中的新目录。", file=sys.stderr)
        return 2
```

## src/causal_storyboard/__main__.py

```python
"""支持 python -m causal_storyboard，不在导入包时执行生成。"""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

## experiments/run_storyboard.py

```python
"""从源码直接运行分镜入口；离线规则模式不需要安装第三方依赖。"""

from pathlib import Path
import sys

# SOURCE 固定为当前独立项目的包目录，不读取旧项目或用户资料。
SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from causal_storyboard.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

## pyproject.toml

```toml
[build-system]
requires = ["setuptools>=75"] # 构建时使用标准 Python 包工具。
build-backend = "setuptools.build_meta"

[project]
name = "causal-algorithm-research"
version = "0.1.0"
description = "Synthetic-only chronological causal and prediction research prototype"
requires-python = ">=3.12"
dependencies = ["numpy>=2.0,<3"] # 仅依赖稳定的数组与线性代数接口。

[project.scripts]
causal-storyboard = "causal_storyboard.cli:main" # 可选安装后的分镜命令；源码入口不需要 NumPy。

[tool.setuptools.packages.find]
where = ["src"] # 源目录可直接通过 PYTHONPATH 导入。
```

## requirements.lock

```text
# 首版实验固定数值依赖；Python 版本仍需在每份运行报告中记录。
numpy==2.4.6
```

## .env.example

```dotenv
# 仅在显式使用 --generate-images 时读取；使用你信任的实际供应方地址。
STORYBOARD_IMAGE_URL=https://your-image-service.example/v1/images/generations
# 模型名由供应方决定；原型不假定任意模型支持此协议。
STORYBOARD_IMAGE_MODEL=your-model-id
# 在运行环境填写真实密钥；不要把 .env 或真实值加入 Git。
STORYBOARD_IMAGE_KEY=
```

## .gitignore

```gitignore
# 私人数据、凭据与本地环境始终留在设备上。
.env
.env.*
!.env.example
data/private/
*.pem
*.key
.venv/
venv/

# 研究结果由显式运行生成并保留；仅忽略可重建的中间文件。
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/
build/
node_modules/

# 本地代码索引与自动生成的代理入口不进入公开仓库。
.codegraph/
/AGENTS.md
```

## .github/workflows/research-checks.yml

```yaml
name: Research checks

on:
  push:
    branches: [main]
  pull_request:
  workflow_dispatch:

# 外部 PR 只使用只读权限，不接触仓库密钥或真实数据。
permissions:
  contents: read

jobs:
  synthetic-validation:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      # 官方动作固定到查验过的提交，避免浮动标签被替换。
      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: '3.12'
      - name: Install pinned numerical dependency
        run: python -m pip install --disable-pip-version-check -r requirements.lock
      - name: Run synthetic invariants and chronological experiment
        run: python -B experiments/run_synthetic.py --seed 7 --samples 400 --replications 3 --bootstrap-draws 100 --output "${{ runner.temp }}/synthetic-ci.json"
      - name: Plan causal-event storyboard without model credentials
        run: python -B experiments/run_storyboard.py --text "一个男孩踢了一下足球，足球滚向桌子并撞倒了桌上的水杯。" --output "${{ runner.temp }}/storyboard-example"
      - name: Verify storyboard coverage and offline provenance
        run: |
          python -B - <<'PY'
          import json
          import os
          from pathlib import Path
          # report 只读取本次 CI 离线生成的分镜，不访问凭据和真实数据。
          report = json.loads((Path(os.environ['RUNNER_TEMP']) / 'storyboard-example/storyboard.json').read_text(encoding='utf-8'))
          # shots 是依次播放的镜头；故事事件的并行关系另存。
          shots = report['shots']
          assert len(shots) == 3
          assert shots[0]['start_s'] == 0 and shots[-1]['end_s'] == 6
          assert all(left['end_s'] == right['start_s'] and left['end_state'] == right['start_state'] for left, right in zip(shots, shots[1:]))
          assert shots[-1]['end_state']['cup.pose'] == 'tipped_on_table'
          assert all(shot['image']['path'] is None and shot['image']['status'] == 'not_requested' for shot in shots)
          assert report['generation_kind'] == 'STORYBOARD_STILL_IMAGES_NOT_CONTINUOUS_VIDEO'
          PY
```
