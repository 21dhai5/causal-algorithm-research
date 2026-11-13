# 分镜 MVP 完整源码

以下为本版实际文件的逐字源码快照，没有省略号或伪代码。以仓库中的独立源文件为执行入口；离线分镜仅使用标准库，NumPy依赖属于项目原有的合成因果研究。

重新修改源文件时同步本汇编，避免说明与实现分离。

## src/causal_storyboard/__init__.py

```python
"""可替换解析器的纯 Python 事件分镜入口；导入不执行模型请求或文件操作。"""

from .core import DEFAULT_STYLE, RuleSceneParser, SceneParser, build_storyboard, validate_scene
from .element_parser import parse_element_scene
from .world import compile_element_scene, validate_element_scene

__all__ = ["DEFAULT_STYLE", "RuleSceneParser", "SceneParser", "build_storyboard", "validate_scene", "parse_element_scene", "compile_element_scene", "validate_element_scene"]  # 对外稳定入口。
```

## src/causal_storyboard/core.py

```python
"""用明确文本与可追溯假设构建分镜；不执行因果效应估计、文件或网络操作。"""

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Protocol

from .element_parser import parse_element_scene
from .world import compile_element_scene, validate_element_scene

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
    """有限中文语法：环境与器物动作，以及兼容原有踢球、跑步、猫坐窗边句型。"""

    # 拒绝否定、条件、推测以及未建模语法，避免把文本反向解释成肯定事件。
    def parse(self, text: str) -> dict:
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("parse_error: text 必须是 1 至 4000 字符的非空字符串")
        text = text.strip()  # 保留完整原文；只有匹配时去掉两端空白。
        if re.search(r"没有|没|不|未|别|并非|如果|假如|除非|若|可能|也许|是否|[?？]", text):
            raise ValueError("parse_error: 当前规则不支持否定、条件、推测或疑问句")
        element_scene = parse_element_scene(text)  # 环境语法必须先登记全部元素，再让世界引擎编译动作。
        if element_scene is not None:
            element_scene = compile_element_scene(element_scene)
            validate_scene(element_scene)
            return element_scene
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
        if event["kind"] in ("open_door", "close_door", "enter_room", "pick_up", "place_on", "move_object") and "element_model" not in scene:
            raise ValueError("scene_error: 环境器物动作必须声明 element_model 并通过世界编译校验")
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
    if "element_model" in scene:
        validate_element_scene(scene)  # 结构化新模型同样校验位置、关系传播和动作篡改。


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
        if "element_model" in parsed:
            prompt += (f"元素身份登记：{[(entity['id'], entity['kind'], entity['label']) for entity in parsed['entities']]}。"
                       "器物相对支撑、固定、手持关系和派生全局位置以该瞬间完整状态为准；初始关系仅描述初态，不能覆盖拿起或放下后的关系。"
                       "没有直接效果或关系传播的元素保持原位置、姿态与身份；人物动作不自动使墙画等器物移动。")
        planned.append({
            "id": f"s{index + 1:02d}", "start_s": float(start), "end_s": float(end),
            "event_ids": [entry["event"]["id"] for entry in covered], "event_refs": refs,
            "description": f"同一发生的阶段细分：{descriptions}", "start_state": _state_at(parsed["initial_state"], timeline, start),
            "end_state": _state_at(parsed["initial_state"], timeline, end), "keyframe": {"time_s": float(moment), "event_id": key["event"]["id"], "phase": phase, "state": state},
            "presentation": presentation, "image_prompt": prompt, "image": {"status": "not_requested", "path": None},
        })
    return {
        "schema_version": "1.1", "input_text": text, "duration_s": float(total),
        "overall_scene_description": text.strip() + " 统一空间和外观：" + str(parsed["continuity"].get("design", "保持已声明实体属性"))
                                     + "。" + "；".join(item.get("explanation", "") for item in parsed["assumptions"]),
        "modeling_scope": "RULE/TEXT 事件模型：显式文本、常识假设与未知分开；时间先后不自动构成因果；不作严格因果效应推断",
        "scene": {key: parsed[key] for key in ("entities", "world", "initial_state", "assumptions", "continuity", "element_model") if key in parsed},
        "events": events, "temporal_relations": parsed["temporal_relations"], "causal_relations": parsed["causal_relations"],
        "unresolved_causal_relations": parsed.get("unresolved_causal_relations", []),
        **({"element_trace": parsed["element_trace"]} if "element_trace" in parsed else {}),
        **({"state_dependencies": parsed["state_dependencies"]} if "state_dependencies" in parsed else {}),
        "timeline": [{"event_id": entry["event"]["id"], "start_s": float(entry["_start"]), "end_s": float(entry["_end"])} for entry in timeline],
        "shots": planned,
    }
```

## src/causal_storyboard/element_parser.py

```python
"""先登记环境与器物，再生成单人物动作骨架；这里只支持逐句完整匹配的有限中文语法。"""

import re

_SETTINGS = {"房间": "room", "屋子": "room", "房子": "house"}  # 同义场景归入同一实体类型。
_NOUNS = {"门": "door", "桌子": "table", "桌": "table", "水杯": "cup", "杯子": "cup",
          "画": "painting", "箱子": "box", "窗户": "window", "椅子": "chair", "墙": "wall"}  # 封闭器物词表。
_LABELS = {"door": "门", "table": "桌子", "cup": "水杯", "painting": "画", "box": "箱子",
           "window": "窗户", "chair": "椅子", "wall": "墙"}  # 标签只表示身份，不包含未来动作。
_PERSONS = {"男孩": "boy", "女孩": "girl", "人": "person"}  # 文本入口只允许一个人物身份。
_POSITIONS = {"左侧": "left", "右侧": "right", "中间": "center", "中央": "center"}  # 符号位置并非测量坐标。
_NEW_SYNTAX = r"门|房间|房子|屋子|墙|挂画|箱子|窗户|椅子|拿起|放回|放到|移到|移动"  # 不截获旧足球与猫窗边语法。


# 构造可回溯证据；假设没有伪造的原文引文。
def _evidence(basis: str, quote: str = "", explanation: str = "") -> dict:
    return {"basis": basis, "quote": quote, "explanation": explanation}


# 识别静态声明；所有剩余文本都必须由具体产生式完整消费。
def _declaration(clause: str) -> dict | None:
    body = clause  # 剥离场景前缀后仍需完整匹配器物声明。
    setting = None  # 没有场景名时后续只创建抽象空间。
    prefix = re.match(r"(房间|屋子|房子)(?:里|内)有", body)  # 有限场景声明前缀。
    if prefix:
        setting, body = prefix[1], body[prefix.end():]
    elif body.startswith("有"):
        body = body[1:]
    record = {"type": "declaration", "setting": setting, "quote": clause}  # 静态语法记录，不执行动作。
    match = re.fullmatch(r"(?:一扇)?(?:(关闭|关上|打开|锁上|上锁)的)?门", body)  # 门状态是初始声明。
    if match and (prefix or clause.startswith("有") or match[1]):
        record.update(kind="door", introduces=True)
        if match[1]:
            record["door_state"] = match[1]
        return record
    match = re.fullmatch(r"门(?:是)?(关闭|关上|打开|锁上|上锁)(?:的|着)?", body)  # 单独补充门初态。
    if match:
        record.update(kind="door", door_state=match[1])
        return record
    match = re.fullmatch(r"(?:一张)?桌子|(?:一个|一只)?(?:水杯|杯子|箱子)|(?:一扇)?窗户|(?:一把|一张)?椅子", body)  # 房间中列出的普通器物。
    if match and (prefix or clause.startswith("有")):
        noun = re.sub(r"^(?:一张|一个|一只|一扇|一把)", "", body)  # 数量词不属于身份标签。
        record.update(kind=_NOUNS[noun], introduces=True)
        return record
    match = re.fullmatch(r"桌(?:子)?上(?:放着|有)(?:一个|一只)?(水杯|杯子|箱子)", body)  # 支撑关系来自原文。
    if match:
        record.update(kind=_NOUNS[match[1]], supported_by="table", introduces=True)
        return record
    if re.fullmatch(r"墙上(?:挂着|挂有)(?:一幅)?画", body):
        record.update(kind="painting", attached_to="wall", introduces=True)
        return record
    match = re.fullmatch(r"(桌子|箱子)(?:在|位于)(房间|屋子|房子)?(左侧|右侧|中间|中央)", body)  # 明确位置只改变所述器物。
    if match:
        record.update(kind=_NOUNS[match[1]], setting=match[2] or setting, position=_POSITIONS[match[3]])
        return record
    return None


# 将一个人物动作完整编译为骨架，前置条件和传播由世界引擎负责。
def _action(clause: str) -> dict:
    body = clause  # 主语以外的整段必须是已支持的动作。
    connector = ""  # 只记录时间词，绝不将它提升为因果边。
    prefix = re.match(r"然后|随后|接着|再", body)  # 当前元素语法只支持顺序动作。
    if prefix:
        connector, body = prefix[0], body[prefix.end():]
    subject = re.match(r"(?:(一个|一名)?(男孩|女孩|人)|(他|她))", body)  # 代词只引用此前出现的唯一人物。
    person = subject[2] if subject and subject[2] else None  # 显式人物种类。
    pronoun = subject[3] if subject else None  # 后续需检查代词与人物一致。
    introduced = bool(subject and subject[1])  # 再次量化引入人物会产生身份歧义。
    if subject:
        body = body[subject.end():]
    record = {"type": "action", "quote": clause, "connector": connector,
              "person": person, "pronoun": pronoun, "introduced": introduced}  # 保留原句用于审计。
    match = re.fullmatch(r"(打开|关闭|关上)(?:了)?(?:一扇)?门", body)  # 不允许把尝试、否定或附加行为吞入匹配。
    if match:
        record.update(kind="open_door" if match[1] == "打开" else "close_door", target="door")
        return record
    match = re.fullmatch(r"走进(?:了)?(房间|屋子|房子)", body)  # 进门必须拥有真实入口门。
    if match:
        record.update(kind="enter_room", target="door", setting=match[1])
        return record
    match = re.fullmatch(r"拿起(?:了)?(桌(?:子)?上(?:的)?)?(?:一个|一只)?(水杯|杯子|箱子)", body)  # 拿起不会提前把结果放入初态。
    if match:
        record.update(kind="pick_up", target=_NOUNS[match[2]], supported_by="table" if match[1] else None)
        return record
    if re.fullmatch(r"拿起(?:了)?(?:墙上(?:的)?)?(?:一幅)?画", body):
        raise ValueError("parse_error: 当前模型不支持拿起画；墙上挂画具有固定关系")
    match = re.fullmatch(r"(?:把)?(水杯|杯子|箱子)放(?:回|到)(?:了)?(桌(?:子)?|箱子)上", body)  # 放置必须由世界引擎核验手持前置。
    if match:
        record.update(kind="place_on", target=_NOUNS[match[1]], destination=_NOUNS[match[2]])
        return record
    match = re.fullmatch(r"(平稳地?|准静态地?)?(?:把)?(桌子|箱子)移到(房间|屋子|房子)?(左侧|右侧|中间|中央)", body)  # 只支持同一场景内的符号平移。
    if match:
        if not match[1]:
            raise ValueError("parse_error: 移动桌子或箱子必须明确写出平稳或准静态方式")
        record.update(kind="move_object", target=_NOUNS[match[2]], setting=match[3], position=_POSITIONS[match[4]])
        return record
    raise ValueError(f"parse_error: 不支持的环境或动作分句：{clause}")


# 新语法不适用时返回 None；适用后任何残句、身份冲突或缺少入口都明确报错。
def parse_element_scene(text: str) -> dict | None:
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("parse_error: text 必须是 1 至 4000 字符的非空字符串")
    text = text.strip()  # 原文保留在输出中，所有显式证据均指向该字符串。
    if not re.search(_NEW_SYNTAX, text):
        return None
    if re.search(r"没有|没|不|未|别|并非|如果|假如|除非|若|可能|也许|是否|[?？]", text):
        raise ValueError("parse_error: 当前规则不支持否定、条件、推测或疑问句")
    clauses = re.split(r"[，,。.!！；;]", text)  # 标点只分句，不推导物理影响。
    if not clauses[-1].strip():
        clauses.pop()
    if not clauses or any(not clause.strip() for clause in clauses):
        raise ValueError("parse_error: 环境文本存在空分句或重复分隔符")
    records = []  # 第一遍只识别语法，尚不构造人物或动作状态。
    seen_action = False  # 动作后的静态描述不能倒灌为动作前的事实。
    for clause in clauses:
        clause = clause.strip()  # 两端空白不参与词法匹配。
        declaration = _declaration(clause)  # 静态声明优先识别。
        if declaration is not None and seen_action:
            raise ValueError("parse_error: 初始环境声明必须位于动作之前，不能把动作后的描述写入初态")
        seen_action = seen_action or declaration is None
        records.append(declaration if declaration is not None else _action(clause))
    scene = {
        "input_text": text, "entities": [], "world": {"setting": "unspecified"},
        "initial_state": {}, "assumptions": [],
        "continuity": {"source": "continuity_design", "design": "已登记环境与器物身份固定；未说明外观保持简洁中性",
                       "constraints": ["先环境、器物，再主体和动作", "只有动作及关系传播可以改变状态", "无关器物保留原有位置与姿态", "时间顺序不自动构成因果"]},
        "events": [], "temporal_relations": [], "causal_relations": [], "unresolved_causal_relations": [],
        "element_model": {"version": "1.0", "construction_order": ["environment", "objects", "subjects"],
                          "environment_ids": [], "object_ids": [], "subject_ids": [], "relations": [],
                          "relation_scope": "initial_state", "state_sources": {}, "action_conditions": []},
    }  # 新场景保持旧分镜器的基础结构。
    model = scene["element_model"]  # 元素登记和每个初始断言的证据来源。

    # 缺少必要条件时集中登记常识假设，不冒充原文事实。
    def assume(explanation: str) -> dict:
        evidence = _evidence("commonsense_assumption", explanation=explanation)  # 同一假设只登记一次。
        if evidence not in scene["assumptions"]:
            scene["assumptions"].append(evidence)
        return evidence

    # 写入扁平初态，并保留来源；相互矛盾的显式声明不能互相覆盖。
    def put(identifier: str, attribute: str, value, evidence: dict) -> None:
        key = f"{identifier}.{attribute}"  # 状态键供世界引擎与镜头快照共用。
        if key in scene["initial_state"] and scene["initial_state"][key] != value:
            raise ValueError(f"parse_error: 初始声明冲突：{key}")
        scene["initial_state"][key] = value
        model["state_sources"][key] = evidence

    settings = [(record["setting"], record["quote"]) for record in records if record.get("setting")]  # 包括动作中明确提到的目的场景。
    if len({_SETTINGS[name] for name, _ in settings}) > 1:
        raise ValueError("parse_error: 当前文本语法只支持一个房间或房子，不支持跨场景或多个场景")
    root = _SETTINGS[settings[0][0]] if settings else "space"  # 无场景描述时只登记最小抽象空间。
    root_label = settings[0][0] if settings else "未指定的抽象空间"  # 不补造房屋或装饰。
    root_source = _evidence("explicit_text", settings[0][0]) if settings else assume("原文没有具体环境，仅使用未指定的抽象空间组织已提到的元素，不添加房屋或道具")  # 场景身份来源。
    scene["world"]["setting"] = root_label
    scene["entities"].append({"id": root, "kind": root, "role": "environment", "label": root_label, "evidence": root_source})
    model["environment_ids"].append(root)
    put(root, "location", "scene", assume("场景根节点仅作空间登记，不表示新增可见物体"))
    put(root, "position", "unspecified", _evidence("unknown", explanation="原文未给场景根节点的符号位置"))
    objects = {}  # 按文本出现顺序登记唯一器物，人物尚未加入。

    # 动作才首次提到的器物也先登记；关系和门状态随后集中设定。
    def mention(kind: str, quote: str) -> None:
        if kind not in objects:
            objects[kind] = {"quote": quote, "attributes": {}}  # 同类器物在有限文本语法中只有一个身份。

    acted_targets = set()  # 只有某物首次动作中的来源修饰能补足其初始关系。
    introduced_objects = set()  # 再次存在声明可能引入另一器物，有限单物语法不能自动合并。
    for record in records:
        if record["type"] == "declaration":
            if record.get("introduces"):
                if record["kind"] in introduced_objects:
                    raise ValueError("parse_error: 同类器物被重复引入，身份不确定；当前文本语法只支持每类一个器物")
                introduced_objects.add(record["kind"])
            mention(record["kind"], record["quote"])
            for attribute in ("door_state", "supported_by", "attached_to", "position"):
                if attribute in record:
                    previous = objects[record["kind"]]["attributes"].get(attribute)  # 重复声明只能保持一致。
                    if previous is not None and previous[0] != record[attribute]:
                        raise ValueError(f"parse_error: {record['kind']} 的初始 {attribute} 声明冲突")
                    objects[record["kind"]]["attributes"][attribute] = (record[attribute], record["quote"])
            if record.get("supported_by"):
                mention(record["supported_by"], record["quote"])
            if record.get("attached_to"):
                mention(record["attached_to"], record["quote"])
        else:
            if record["kind"] != "enter_room":
                mention(record["target"], record["quote"])
            if record.get("destination"):
                mention(record["destination"], record["quote"])
            if record.get("supported_by"):
                mention(record["supported_by"], record["quote"])
                previous = objects[record["target"]]["attributes"].get("supported_by")  # 原文动作中的“桌上”也声明初始支撑。
                if previous is None and record["target"] not in acted_targets:
                    objects[record["target"]]["attributes"]["supported_by"] = (record["supported_by"], record["quote"])
            acted_targets.add(record["target"])
    actions = [record for record in records if record["type"] == "action"]  # 后续执行顺序完全保留原文顺序。
    if not actions:
        raise ValueError("parse_error: 环境声明后还需要一个受支持的单人物动作")
    if any(record["kind"] == "enter_room" for record in actions) and "door" not in objects:
        raise ValueError("parse_error: 走进房间需要明确登记入口门及其状态，当前语法不猜测入口或添加开门动作")
    if "wall" in objects:
        scene["entities"].append({"id": "wall", "kind": "wall", "role": "environment", "label": "墙", "evidence": _evidence("explicit_text", objects["wall"]["quote"])})
        model["environment_ids"].append("wall")
        put("wall", "location", root, assume("原文提到的墙属于同一已登记场景"))
        put("wall", "position", "unspecified", _evidence("unknown", explanation="未给墙的符号方位"))
    for kind, item in objects.items():
        if kind == "wall":
            continue
        source = _evidence("explicit_text", item["quote"])  # 器物身份来源可追溯至完整分句。
        attributes = item["attributes"]  # 显式位置、支撑、固定和门状态。
        scene["entities"].append({"id": kind, "kind": kind, "role": "object", "label": _LABELS[kind], "evidence": source})
        model["object_ids"].append(kind)
        relation = "supported_by" if "supported_by" in attributes else "attached_to" if "attached_to" in attributes else None  # 一物只允许一种位置约束。
        if "supported_by" in attributes and "attached_to" in attributes:
            raise ValueError(f"parse_error: {kind} 同时具有支撑与固定关系")
        parent = attributes[relation][0] if relation else root  # 支撑或固定位置由对应父实体定义。
        if "position" in attributes and parent != root:
            raise ValueError("parse_error: 受支撑器物的房间方位不能改写为支撑体局部方位；当前语法不进行坐标换算")
        location_source = _evidence("explicit_text", attributes[relation][1]) if relation else assume("未明确单独位置的器物位于同一已登记场景，具体位置保持未指定")  # 不虚构桌面或房子。
        put(kind, "location", parent, location_source)
        put(kind, "position", attributes["position"][0] if "position" in attributes else "unspecified",
            _evidence("explicit_text", attributes["position"][1]) if "position" in attributes else _evidence("unknown", explanation="未给器物的相对符号位置"))
        for attribute in ("supported_by", "attached_to", "held_by"):
            put(kind, attribute, parent if attribute == relation else None,
                location_source if attribute == relation else assume("未声明的支撑、固定和手持关系初始为空；不预置任何动作结果"))
        if relation:
            model["relations"].append({"source": kind, "target": parent, "relation": relation, "scope": "initial_state", "evidence": location_source})
        if kind in ("cup", "box"):
            put(kind, "pose", "upright", assume("未给姿态的水杯或箱子初始直立；不假设倾倒、破碎或泼洒"))
        elif kind == "painting" and relation == "attached_to":
            put(kind, "pose", "hanging", source)
        if kind in ("table", "box"):
            put(kind, "motion", "stationary", assume("器物在动作开始前静止，不把未来移动结果写入初态"))
            put(kind, "support", "stable", assume("已登记桌子或箱子作为稳定支撑体；不额外生成支撑面或器物"))
        if kind == "door":
            declared = attributes.get("door_state")  # 显式门初态优先，绝不为后续进门反推门已打开。
            door_actions = [record for record in actions if record["kind"] in ("open_door", "close_door", "enter_room")]  # 第一项只用于补足必要初态。
            if declared:
                status = "open" if declared[0] == "打开" else "closed"  # 上锁门也处于关闭状态。
                door_source = _evidence("explicit_text", declared[1])  # 初态并非来自未来开门事件。
            elif door_actions and door_actions[0]["kind"] != "enter_room":
                status = "closed" if door_actions[0]["kind"] == "open_door" else "open"  # 只补足反向开合所需初态。
                door_source = assume("原文未给门初态；首次开门前门关闭，或首次关门前门打开；这是必要前置假设")
            else:
                raise ValueError("parse_error: 进入房间前必须明确门已打开，不能静默补造开门或门状态")
            put(kind, "open", status, door_source)
            locked = bool(declared and declared[0] in ("锁上", "上锁"))  # 显式上锁不能被开门所需假设覆盖。
            needs_unlock = any(record["kind"] == "open_door" for record in actions)  # 只在开门需要时假设未锁。
            put(kind, "locked", True if locked else False if needs_unlock else None,
                _evidence("explicit_text", declared[1]) if locked else assume("原文没有上锁信息；为执行开门假设门未锁") if needs_unlock else _evidence("unknown", explanation="未说明锁状态，且动作不需要补足"))
            put(kind, "connects", root, assume("已提到的门作为同一场景的入口；不引入第二个房间"))
            model["relations"].append({"source": kind, "target": root, "relation": "connects", "scope": "initial_state", "evidence": model["state_sources"]["door.connects"]})
    person = None  # 第二阶段登记主体，动作尚未执行。
    appearance = None  # 唯一人物的显式身份引文。
    person_pronoun = None  # 泛指人物由首个代词建立一致性约束，不补造人物性别属性。
    for record in actions:
        if record["person"]:
            if person is not None and (person != record["person"] or record["introduced"]):
                raise ValueError("parse_error: 当前环境文本语法只支持一个人物，多人或再次引入人物不在范围内")
            person, appearance = record["person"], appearance or record["person"]
        if person is None:
            raise ValueError("parse_error: 第一个动作必须明确给出男孩、女孩或人，不能猜测省略主语")
        if record["pronoun"] and person != "人" and record["pronoun"] != ("他" if person == "男孩" else "她"):
            raise ValueError("parse_error: 人物代词与唯一主体不一致")
        if record["pronoun"] and person == "人":
            if person_pronoun is not None and record["pronoun"] != person_pronoun:
                raise ValueError("parse_error: 同一泛指人物出现互相冲突的代词")
            person_pronoun = record["pronoun"]
    actor = _PERSONS[person]  # 所有省略主语的续句共用同一身份。
    scene["entities"].append({"id": actor, "kind": "person", "role": "subject", "label": appearance, "evidence": _evidence("explicit_text", appearance)})
    model["subject_ids"].append(actor)
    outside = any(record["kind"] == "enter_room" for record in actions)  # 进入动作要求人物真实从场景外开始。
    put(actor, "location", "outside" if outside else root,
        assume("进入场景的人物初始位于入口外，入口可达；不允许穿越关闭的门") if outside else assume("人物与已提到的器物处于同一已登记场景，动作目标在可达范围内"))
    put(actor, "position", "unspecified", _evidence("unknown", explanation="未指定人物符号位置"))
    put(actor, "holding", None, assume("人物初始空手；拿起和放置必须满足实际状态前置，不能预置未来手持结果"))
    put(actor, "action", "idle", assume("动作开始前人物空闲；只在对应进行时展示动作姿态"))
    if outside:
        assume("入口外的人物可以触及已登记入口门；未说明的可达性仅作为必要动作假设")
    current_support = {kind: scene["initial_state"].get(kind + ".supported_by") for kind in objects}  # 只核验原句“桌上”来源，不代替世界引擎执行动作。
    actor_region = "outside" if outside else root  # 仅用于为各动作登记适用区域，不放宽实际状态前置。
    for index, record in enumerate(actions):
        identifier = f"e{index + 1}"  # 一个骨架对应一次真实发生。
        kind = record["kind"]  # 世界引擎按枚举编译前置、直接效果和传播。
        target = record["target"]  # 必须已在人物之前完成登记。
        action = {"actor": actor, "target": target}  # 操作参数与自然语言标签分离。
        if kind == "enter_room":
            action["destination"] = root
        elif "destination" in record:
            action["destination"] = record["destination"]
        if "position" in record:
            action["position"] = record["position"]
        reached = action.get("destination") if kind == "place_on" else target  # 放置时检查支撑体可达，其他动作检查自身目标。
        reach_condition = {"event_id": identifier, "kind": "reachable", "actor": actor, "target": reached, "from_location": actor_region,
                           "value": True, "evidence": assume(f"主体 {actor} 从 {actor_region} 可触及目标 {reached}；仅为该主体、目标和区域的必要可达假设")}  # 自由说明不参与布尔判断。
        if reach_condition not in model["action_conditions"]:
            model["action_conditions"].append(reach_condition)
        if kind == "enter_room":
            actor_region = root
        if kind == "move_object":
            action["transport_mode"] = "quasistatic"  # 平稳只描述本次移动，不能授权此前拿取或放置。
            support_condition = {"event_id": identifier, "kind": "support_preserved", "actor": actor, "target": target, "value": True,
                                 "evidence": assume(f"主体 {actor} 平稳移动 {target} 时采用准静态假设，保持支撑且无滑落；不保证真实物理过程")}  # 只对当前搬运目标生效。
            if support_condition not in model["action_conditions"]:
                model["action_conditions"].append(support_condition)
        if record.get("supported_by") and current_support[target] != record["supported_by"]:
            raise ValueError("parse_error: 拿起语句中的桌上来源与当前支撑关系冲突")
        if kind == "pick_up":
            current_support[target] = None
        elif kind == "place_on":
            current_support[target] = action["destination"]
        moments = {  # 每个描述只表示一个时刻，具体全场景状态来自世界引擎快照。
            "open_door": ("人物准备打开尚未打开的门", "人物正在打开同一扇门", "门已打开，人物位置由当前状态决定"),
            "close_door": ("人物准备关闭尚未关闭的门", "人物正在关闭同一扇门", "门已关闭"),
            "enter_room": ("人物在已打开的入口外", "人物正通过打开的门进入场景", "人物已进入场景，门保留此前状态"),
            "pick_up": ("人物空手并准备拿起目标器物", "人物正在拿起同一器物", "器物由人物持有，原支撑关系已解除"),
            "place_on": ("人物持有准备放置的器物", "人物正将器物放到目标支撑面", "器物受到目标支撑，人物已空手"),
            "move_object": ("目标器物尚在移动前位置", "人物正平稳移动目标器物，原有支撑保持", "器物已到明确目标位置，原有支撑保持"),
        }[kind]
        participants = list(dict.fromkeys([actor, target] + ([action["destination"]] if "destination" in action else [])))  # 参与者不能出现未登记引用。
        scene["events"].append({"id": identifier, "kind": kind, "label": record["quote"], "participants": participants,
                                "evidence": _evidence("explicit_text", record["quote"]), "action": action,
                                "keyframes": dict(zip(("before", "during", "after"), moments))})
        if index:
            temporal_source = _evidence("explicit_text", record["connector"]) if record["connector"] else assume("没有明确时间连接词的动作按叙述顺序安排；此顺序不构成因果证据")  # 标点只决定呈现顺序。
            scene["temporal_relations"].append({"source": f"e{index}", "target": identifier, "relation": "before", "evidence": temporal_source})
            scene["unresolved_causal_relations"].append({"source": f"e{index}", "target": identifier,
                                                        "evidence": _evidence("unknown", record["connector"], "动作先后不自动提供因果依据；世界引擎另外检查状态前置")})
    return scene
```

## src/causal_storyboard/world.py

```python
"""有限器物世界的可审计规则推演；不识别数据因果，不执行文件或网络操作。"""

from copy import deepcopy
import json
import math
import re

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,63}\Z")  # 标识不能注入状态属性路径。
_KINDS = {"room", "house", "space", "wall", "door", "table", "cup", "painting", "box", "window", "chair", "person"}  # 有限的登记类型。
_REGIONS = {"room", "house", "space"}  # 最近区域决定器物所属的全局空间。
_SENTINELS = {"outside", "unspecified", "scene"}  # 外部位置不创建额外实体。
_BASES = {"explicit_text", "commonsense_assumption", "unknown"}  # 证据与未知判断分开保存。
_HOLDABLE = {"cup", "box", "painting", "chair"}  # 当前单手模型允许操作的器物。
_MOVABLE = {"table", "box", "chair", "cup", "painting"}  # 不提供墙、门及区域的搬运规则。
_SUPPORTS = {"table", "box", "chair"}  # 放置动作只接受已登记的稳定支撑体。
_LINKS = ("supported_by", "attached_to", "held_by")  # 三种互斥的直接约束。
_RULES = {  # 规则说明随编译结果导出，不能被误称为统计识别结果。
    "open_door": "门未锁且可达时，由关闭转换为打开",
    "close_door": "门可达时，由打开转换为关闭",
    "enter_room": "仅从门外通过已打开且连接目的区域的门进入",
    "pick_up": "空手主体取走可达、未固定的器物，同时解除原支撑",
    "place_on": "把手持器物放到可达的稳定支撑体，保持原姿态",
    "move_object": "在同一区域内改变未固定器物的位置；支撑物传播需要明确平稳假设",
    "inherit_location": "按登记的位置链计算最近区域及位置；父元素变动传播到子元素",
    "action_complete": "动作结束后主体回到 idle，不扩展额外情节",
}


# 对有限 JSON 迭代检查深度、循环及节点总量，在 deepcopy 前拒绝恶意容器。
def _check_json(value: object) -> None:
    stack = [(value, 0, False)]  # 退出标记只用于当前祖先链，允许正常共享引用。
    ancestors = set()  # 当前容器祖先，识别循环而非重复使用的数据。
    count = 0  # 编译轨迹也受总量限制，避免无界扫描。
    while stack:
        current, depth, leaving = stack.pop()  # 一次处理一个 JSON 节点。
        if leaving:
            ancestors.remove(id(current))
            continue
        count += 1
        if count > 2_000_000 or depth > 32:
            raise ValueError("element_error: 场景超过 JSON 节点或深度限制")
        if type(current) in (dict, list):
            if count + len(stack) + len(current) > 2_000_000:
                raise ValueError("element_error: 场景容器超过 JSON 节点限制")
            if id(current) in ancestors:
                raise ValueError("element_error: 场景不能包含循环引用")
            ancestors.add(id(current))
            stack.append((current, depth, True))
            if type(current) is dict:
                if any(type(key) is not str for key in current):
                    raise ValueError("element_error: JSON 字典键必须是字符串")
                stack.extend((item, depth + 1, False) for item in current.values())
            else:
                stack.extend((item, depth + 1, False) for item in current)
        elif type(current) is int and current.bit_length() > 1024:
            raise ValueError("element_error: 整数超过 1024 位的序列化边界")
        elif type(current) not in (str, int, float, bool, type(None)) or type(current) is float and not math.isfinite(current):
            raise ValueError("element_error: 场景只能包含有限 JSON 数据")


# 所有显式证据必须能逐字回溯到原文，规则证据必须保留其来源类别。
def _check_evidence(evidence: object, text: str) -> None:
    if (not isinstance(evidence, dict) or not isinstance(evidence.get("basis"), str) or evidence["basis"] not in _BASES
            or not isinstance(evidence.get("quote"), str)
            or not isinstance(evidence.get("explanation", ""), str)):
        raise ValueError("element_error: evidence 需要 basis、quote 和字符串 explanation")
    if evidence["basis"] == "explicit_text" and (not evidence["quote"] or evidence["quote"] not in text):
        raise ValueError("element_error: 显式证据必须逐字来自 input_text")


# 生成带明确说明的规则证据，不把补全规则伪装成原文观察。
def _rule_evidence(explanation: str) -> dict:
    return {"basis": "commonsense_assumption", "quote": "", "explanation": explanation + "；仅为登记世界内的规则前向推演，不是数据识别因果"}


# 区分 bool、数值和 null，防止 False 与 0 在状态比较时被当作同一事实。
def _same(left: object, right: object) -> bool:
    return type(left) is type(right) and left == right


# 校验平铺状态键和值，属性数受实体数量约束，不能嵌入结构化副作用。
def _check_state(state: object, entities: dict) -> None:
    if not isinstance(state, dict) or len(state) > len(entities) * 40:
        raise ValueError("element_error: 状态必须是每实体最多 40 个属性的字典")
    for key, value in state.items():
        if (key.count(".") != 1 or key.split(".")[0] not in entities
                or not _IDENTIFIER.fullmatch(key.split(".")[1])
                or type(value) not in (str, int, float, bool, type(None))):
            raise ValueError("element_error: 状态需要已登记的 entity.attribute 和 JSON 标量")


# 按位置父链迭代计算全局坐标；最近区域内保留各层已知位置，避免局部坐标吞掉桌子移动。
def _derive(state: dict, entities: dict) -> dict:
    derived = {}  # 全实体派生属性，调用方决定如何记录其来源。
    for identifier in entities:
        chain = []  # 从当前元素到最近区域或外部哨兵的有界路径。
        seen = set()  # 每条路径单独查环，不递归展开器物关系。
        current = identifier  # 沿已登记 location 向上查找。
        while current in entities:
            if current in seen:
                raise ValueError("element_error: location 位置图存在环")
            seen.add(current)
            chain.append(current)
            if entities[current]["kind"] in _REGIONS:
                break
            current = state[current + ".location"]
        root = current  # 最近区域 id 或外部哨兵。
        positions = [item + "=" + (state.get(item + ".position") or "unspecified")
                     for item in reversed(chain) if item != root]  # 保留每层身份及未知位置，不能把局部左侧冒充房间左侧。
        derived[identifier + ".root_location"] = root
        derived[identifier + ".world_position"] = root + ":" + ("/".join(positions) if positions else "unspecified")
    return derived


# 位置图整体查环不能遇到区域就停止，否则会漏掉区域间的恶意循环引用。
def _check_locations(state: dict, entities: dict) -> None:
    complete = set()  # 已验证的父链可被后续元素复用。
    for identifier in entities:
        path = set()  # 当前链内重复意味着位置循环。
        current = identifier  # 最多经过实体数量个父节点。
        while current in entities and current not in complete:
            if current in path:
                raise ValueError("element_error: location 位置图存在环")
            path.add(current)
            parent = state.get(current + ".location")  # 缺失与 null 不能成为隐式区域。
            if not isinstance(parent, str) or parent not in entities and parent not in _SENTINELS:
                raise ValueError(f"element_error: {current}.location 需要登记父实体或位置哨兵")
            current = parent
        complete.update(path)


# 每一帧检查位置、互斥关系和单手双向约束；未知无关属性原样保留。
def _check_invariants(state: dict, entities: dict) -> None:
    _check_state(state, entities)
    _check_locations(state, entities)
    carried = {}  # 同一主体至多持有一个器物。
    for identifier, entity in entities.items():
        position = state.get(identifier + ".position", "unspecified")  # 缺失局部位置只表示未指定。
        if position is not None and (not isinstance(position, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", position)):
            raise ValueError("element_error: position 需要无路径分隔符的符号或 null")
        links = [(name, state.get(identifier + "." + name)) for name in _LINKS]  # 未登记字段不引入约束边。
        active = [(name, target) for name, target in links if target is not None]  # 实际存在的直接约束。
        if len(active) > 1:
            raise ValueError(f"element_error: {identifier} 不能同时受支撑、固定或手持")
        for name, target in active:
            if not isinstance(target, str) or target not in entities or target == identifier:
                raise ValueError(f"element_error: {identifier}.{name} 引用了无效实体")
            if state[identifier + ".location"] != target:
                raise ValueError(f"element_error: {identifier}.{name} 必须与 location 一致")
            if name == "held_by":
                if entity["role"] != "object" or entities[target]["kind"] != "person" or target in carried:
                    raise ValueError("element_error: 手持需要单一主体及单一器物")
                carried[target] = identifier
                if state.get(target + ".holding") != identifier:
                    raise ValueError("element_error: held_by 与 holding 必须双向一致")
            elif name == "supported_by" and entities[target]["kind"] not in _SUPPORTS:
                raise ValueError("element_error: supported_by 需要登记支撑体")
        if entity["kind"] == "person":
            holding = state.get(identifier + ".holding")  # null 表示明确空手，缺失不用于取物前提。
            if holding is not None and (not isinstance(holding, str) or holding not in entities or state.get(holding + ".held_by") != identifier):
                raise ValueError("element_error: holding 与 held_by 必须双向一致")
        elif entity["role"] == "object" and state[identifier + ".location"] in entities:
            parent = state[identifier + ".location"]  # 器物跟随主体必须由手持关系说明。
            if entities[parent]["kind"] == "person" and state.get(identifier + ".held_by") != parent:
                raise ValueError("element_error: 器物位于主体处需要明确 held_by")
        if entity["kind"] == "door":
            if state.get(identifier + ".open") not in ("closed", "open"):
                raise ValueError("element_error: door.open 只允许 closed 或 open")
            if type(state.get(identifier + ".locked")) not in (bool, type(None)):
                raise ValueError("element_error: door.locked 只允许 bool 或 null")
            destination = state.get(identifier + ".connects")  # 门只连接已登记区域，不能生成目的房间。
            if not isinstance(destination, str) or destination not in entities or entities[destination]["kind"] not in _REGIONS:
                raise ValueError("element_error: door.connects 需要登记的区域")


# 校验模型输入及初始关系断言，并补齐仅用于呈现的位置派生量。
def _prepare(scene: dict) -> tuple[dict, dict]:
    model = scene.get("element_model")  # 元素世界必须显式声明自己的建模版本。
    if not isinstance(model, dict) or model.get("version") != "1.0" or model.get("construction_order") != ["environment", "objects", "subjects"]:
        raise ValueError("element_error: element_model 需要 version 1.0 及先环境、器物、主体的登记顺序")
    if not isinstance(scene.get("input_text"), str) or not 1 <= len(scene["input_text"]) <= 4000:
        raise ValueError("element_error: input_text 需要 1 至 4000 字符")
    if not isinstance(scene.get("entities"), list) or not 1 <= len(scene["entities"]) <= 128:
        raise ValueError("element_error: 需要 1 至 128 个登记实体")
    entities = {}  # 身份索引同时用于检查全部状态和动作引用。
    for entity in scene["entities"]:
        if (not isinstance(entity, dict) or not isinstance(entity.get("id"), str)
                or not _IDENTIFIER.fullmatch(entity["id"]) or entity["id"] in entities or entity["id"] in _SENTINELS
                or not isinstance(entity.get("kind"), str) or entity["kind"] not in _KINDS or entity.get("role") not in ("environment", "object", "subject")
                or not isinstance(entity.get("label"), str) or not entity["label"]):
            raise ValueError("element_error: 实体 id、label、kind、role 无效或重复")
        if (entity["kind"] == "person") != (entity["role"] == "subject") or entity["kind"] in _REGIONS and entity["role"] != "environment":
            raise ValueError("element_error: 区域必须为环境，person 必须为主体")
        _check_evidence(entity.get("evidence"), scene["input_text"])
        entities[entity["id"]] = entity
    order = []  # 登记输出按环境、器物、主体组织，不受原实体数组顺序影响。
    for field, role in (("environment_ids", "environment"), ("object_ids", "object"), ("subject_ids", "subject")):
        group = model.get(field)  # 每个实体只能出现在与其 role 对应的登记组。
        if (not isinstance(group, list) or any(not isinstance(identifier, str) for identifier in group)
                or len(group) != len(set(group)) or set(group) != {identifier for identifier in entities if entities[identifier]["role"] == role}):
            raise ValueError(f"element_error: {field} 必须完整且唯一地登记对应 role")
        order.extend(group)
    scene["entities"] = [entities[identifier] for identifier in order]
    entities = {identifier: entities[identifier] for identifier in order}  # 统一后续轨迹快照的登记顺序。
    state = scene.get("initial_state")  # 直接在场景副本内补充派生量。
    _check_state(state, entities)
    sources = model.get("state_sources")  # 每个初态事实均保留独立来源。
    if not isinstance(sources, dict) or set(sources) != set(state):
        raise ValueError("element_error: state_sources 必须与 initial_state 属性一一对应")
    for evidence in sources.values():
        _check_evidence(evidence, scene["input_text"])
    assumptions = scene.get("assumptions")  # 可达及平稳运动的假设不能藏在程序分支内。
    if not isinstance(assumptions, list) or len(assumptions) > 512:
        raise ValueError("element_error: assumptions 必须是有限列表")
    for evidence in assumptions:
        _check_evidence(evidence, scene["input_text"])
    conditions = model.get("action_conditions", [])  # 可达与支撑保持使用有对象范围的布尔断言，不读取说明文字作开关。
    if not isinstance(conditions, list) or len(conditions) > 512:
        raise ValueError("element_error: action_conditions 必须为有界列表")
    condition_keys = set()  # 同一事件作用域不能出现重复或相互矛盾的断言。
    event_data = scene.get("events")  # 在提取条件作用域前先检查容器类型，所有输入错误统一为 ValueError。
    if not isinstance(event_data, list) or not 1 <= len(event_data) <= 120:
        raise ValueError("element_error: 需要 1 至 120 个动作")
    event_ids = {event.get("id") for event in event_data if isinstance(event, dict) and isinstance(event.get("id"), str)}  # 条件不能指向不存在的未来或外部动作。
    for condition in conditions:
        if (not isinstance(condition, dict) or condition.get("kind") not in ("reachable", "support_preserved")
                or set(condition) - {"event_id", "kind", "actor", "target", "from_location", "value", "evidence"}
                or not isinstance(condition.get("event_id"), str) or condition["event_id"] not in event_ids
                or type(condition.get("value")) is not bool):
            raise ValueError("element_error: 动作条件需要受支持的 kind 和布尔 value")
        actor, target = condition.get("actor"), condition.get("target")  # 条件只适用于这一对已登记元素。
        if (not isinstance(actor, str) or actor not in entities or entities[actor]["kind"] != "person"
                or not isinstance(target, str) or target not in entities or actor == target):
            raise ValueError("element_error: 动作条件需要登记主体与目标")
        location = condition.get("from_location")  # 可达性必须限定起始区域或入口外。
        if condition["kind"] == "reachable":
            if not isinstance(location, str) or location != "outside" and (location not in entities or entities[location]["kind"] not in _REGIONS):
                raise ValueError("element_error: reachable 需要已登记区域或 outside 的 from_location")
        elif "from_location" in condition:
            raise ValueError("element_error: support_preserved 不使用 from_location")
        _check_evidence(condition.get("evidence"), scene["input_text"])
        if condition["evidence"]["basis"] == "unknown":
            raise ValueError("element_error: 未知证据不能确认动作条件")
        identity = (condition["event_id"], condition["kind"], actor, target, location)  # 作用域身份不依赖自由说明文本。
        if identity in condition_keys:
            raise ValueError("element_error: 动作条件作用域重复")
        condition_keys.add(identity)
    _check_invariants(state, entities)
    relations = model.get("relations")  # 这些边只断言初态，不能在动作后重新强加原支撑。
    if not isinstance(relations, list) or len(relations) > len(entities) * 4:
        raise ValueError("element_error: 元素关系需要有限列表")
    seen = set()  # 重复断言没有新信息，且可能隐藏相互冲突的关系。
    for relation in relations:
        if not isinstance(relation, dict):
            raise ValueError("element_error: 元素关系必须是字典")
        source, target, kind = relation.get("source"), relation.get("target"), relation.get("relation")  # 初态断言的两个端点。
        if (not isinstance(source, str) or not isinstance(target, str) or source not in entities or target not in entities
                or source == target or kind not in ("supported_by", "attached_to", "inside", "connects")
                or relation.get("scope", "initial_state") != "initial_state" or (source, kind) in seen):
            raise ValueError("element_error: 元素关系类型、端点或 initial_state 范围无效")
        seen.add((source, kind))
        _check_evidence(relation.get("evidence"), scene["input_text"])
        key = source + "." + ("location" if kind == "inside" else kind)  # inside 是初始位置声明，不是永久绑定。
        if state.get(key) != target:
            raise ValueError(f"element_error: 初始关系 {source}.{kind} 与 initial_state 冲突")
    for key, value in _derive(state, entities).items():
        if key in state and not _same(state[key], value):
            raise ValueError(f"element_error: 派生初态 {key} 与位置链冲突")
        state[key] = value
        sources[key] = _rule_evidence("从已登记的 location 与 position 链计算 " + key)
    return entities, state


# 只按有证据的 before 与因果边拓扑排序，未定序和并行的富世界动作明确拒绝。
def _ordered(scene: dict) -> list:
    events = scene.get("events")  # 数组只承载事件身份，不提供隐式时间顺序。
    if not isinstance(events, list) or not 1 <= len(events) <= 120:
        raise ValueError("element_error: 需要 1 至 120 个动作")
    pending = {}  # 尚未完成的唯一事件。
    for event in events:
        if (not isinstance(event, dict) or not isinstance(event.get("id"), str) or not _IDENTIFIER.fullmatch(event["id"])
                or event["id"] in pending or not isinstance(event.get("kind"), str) or event["kind"] not in _RULES or event["kind"] in ("inherit_location", "action_complete")):
            raise ValueError("element_error: 动作 id 重复或 kind 不受支持")
        if not isinstance(event.get("label"), str) or not isinstance(event.get("participants"), list):
            raise ValueError("element_error: 动作需要 label 和 participants")
        if not isinstance(event.get("keyframes"), dict) or any(not isinstance(event["keyframes"].get(phase), str) or not event["keyframes"][phase] for phase in ("before", "during", "after")):
            raise ValueError("element_error: 动作需要三个非空 keyframes")
        _check_evidence(event.get("evidence"), scene["input_text"])
        if event["evidence"]["basis"] == "unknown":
            raise ValueError("element_error: 未知动作不能作为已发生事件执行")
        pending[event["id"]] = event
    dependencies = {identifier: set() for identifier in pending}  # 只记录已支持的时间与因果前置。
    for field in ("temporal_relations", "causal_relations", "unresolved_causal_relations"):
        relations = scene.get(field, [] if field == "unresolved_causal_relations" else None)  # 未判定关系可为空，不能混入 DAG。
        if not isinstance(relations, list) or len(relations) > 120 * 120:
            raise ValueError("element_error: 事件关系必须是有界列表")
        for relation in relations:
            if not isinstance(relation, dict):
                raise ValueError("element_error: 事件关系必须是字典")
            source, target = relation.get("source"), relation.get("target")  # 关系端点只引用事件，不能引用器物。
            if not isinstance(source, str) or not isinstance(target, str) or source not in pending or target not in pending or source == target:
                raise ValueError("element_error: 事件关系端点无效")
            _check_evidence(relation.get("evidence"), scene["input_text"])
            if field == "unresolved_causal_relations":
                continue
            if relation["evidence"]["basis"] == "unknown":
                raise ValueError("element_error: 未知关系不能确定动作顺序")
            if field == "temporal_relations" and relation.get("relation") != "before":
                raise ValueError("element_error: 富世界暂不支持 overlaps 并行动作")
            if field == "causal_relations" and (relation.get("relation") not in (None, "causes", "enables") or relation["evidence"]["basis"] == "unknown"):
                raise ValueError("element_error: 未知或无效因果关系不能加入 DAG")
            dependencies[target].add(source)
    ordered = []  # 每一步必须具有唯一可执行动作，拒绝从数组猜测顺序。
    while pending:
        ready = [identifier for identifier in pending if not dependencies[identifier]]  # 当前所有拓扑前沿。
        if not ready:
            raise ValueError("element_error: before / causal 关系存在有向环")
        if len(ready) != 1:
            raise ValueError("element_error: 富世界动作次序未定或并行；需要明确 before 关系")
        identifier = ready[0]  # 唯一下一动作，和输入数组排列无关。
        ordered.append(pending.pop(identifier))
        for predecessors in dependencies.values():
            predecessors.discard(identifier)
    return ordered


# 只读取匹配主体、目标、区域的肯定断言；“不可达”等说明文字不会获得执行权限。
def _condition(scene: dict, event_id: str, kind: str, actor: str, target: str, location: str | None = None) -> dict:
    for condition in scene["element_model"].get("action_conditions", []):
        if (condition["event_id"] == event_id and condition["kind"] == kind and condition["actor"] == actor and condition["target"] == target
                and condition.get("from_location") == location and condition["value"] is True):
            return deepcopy(condition)
    raise ValueError(f"element_error: 缺少明确的 {kind} 动作条件")


# 验证两个元素同处登记区域，具体可达性另由结构化条件确认。
def _same_root(scene: dict, state: dict, actor: str, target: str) -> None:
    root = state[actor + ".root_location"]  # 行为主体当前区域，不从未来目的地取值。
    if root != state[target + ".root_location"] or not any(entity["id"] == root and entity["kind"] in _REGIONS for entity in scene["entities"]):
        raise ValueError("element_error: 主体和目标需要处于同一已知可达区域，不能用未知位置偷过前置")


# 判断器物是否位于移动父体的位置子树；该有界查询也覆盖多层盒子及桌面器物。
def _descends(state: dict, entities: dict, identifier: str, ancestor: str) -> bool:
    current = state[identifier + ".location"]  # 从父开始，不把元素自己算作后代。
    for unused in range(len(entities)):  # 位置图已查环，数量界限避免任意长链。
        if current == ancestor:
            return True
        if current not in entities:
            return False
        current = state[current + ".location"]
    return False


# 从当前全场状态编译一个动作的直接变化与进行时差量，所有前置在真正修改前检查。
def _apply(scene: dict, event: dict, state: dict, entities: dict) -> tuple[dict, dict, dict, list, list]:
    action = event.get("action")  # 结构化动作必须由解析器给出，不从 label 猜测。
    fields = {"actor", "target"}  # 每类动作只接受自身使用的参数，避免忽略无效修饰。
    if event["kind"] in ("enter_room", "place_on"):
        fields.add("destination")
    if event["kind"] == "move_object":
        fields.add("position")
    if event["kind"] in ("enter_room", "pick_up", "place_on", "move_object"):
        fields.add("transport_mode")
    if not isinstance(action, dict) or set(action) - fields or "transport_mode" in action and action["transport_mode"] != "quasistatic":
        raise ValueError("element_error: action 包含该动作不支持的参数或搬运方式")
    actor, target = action.get("actor"), action.get("target")  # 操作主体与目标身份。
    if (not isinstance(actor, str) or not isinstance(target, str) or actor not in entities or target not in entities
            or entities[actor]["kind"] != "person" or actor == target):
        raise ValueError("element_error: action 需要已登记 person 主体和不同目标")
    if (not event["participants"] or any(not isinstance(item, str) or item not in entities for item in event["participants"])
            or actor not in event["participants"] or target not in event["participants"]):
        raise ValueError("element_error: participants 需要包含已登记的 actor 和 target")
    kind = event["kind"]  # 本轮只应用一条受支持规则。
    preconditions = {}  # 仅记录实际读取的状态条件，不将无关画作变成动作原因。
    direct = {actor + ".action": "idle"}  # 动作完成只恢复主体空闲，不虚构后续反应。
    active = {}  # 进行时从本轮 before 派生，不能提前拿取或放开器物。
    unresolved = []  # 未建模物理影响作为限制返回，不自动生成结果。
    conditions = []  # 保存本动作实际依赖的结构化假设，供审计读取。

    # 一致地读取有定义前置；缺失键不能被当作已知空手或未锁。
    def require(key: str, expected: object) -> None:
        if key not in state or not _same(state[key], expected):
            raise ValueError(f"element_error: {event['id']} 前置 {key}={expected!r} 不成立")
        preconditions[key] = state[key]

    # 可达性读取的局部和全局位置都进入审计前置。
    def reachable(other: str) -> None:
        _same_root(scene, state, actor, other)
        conditions.append(_condition(scene, event["id"], "reachable", actor, other, state[actor + ".root_location"]))
        for identifier in (actor, other):
            for attribute in ("location", "root_location"):
                preconditions[identifier + "." + attribute] = state[identifier + "." + attribute]

    # 入口必须位于所连接区域，且从外部到该入口有明确可达条件。
    def entry_reachable() -> None:
        require(actor + ".location", "outside")
        require(target + ".root_location", state[target + ".connects"])
        conditions.append(_condition(scene, event["id"], "reachable", actor, target, "outside"))

    # 所有会搬运器物的动作共用支撑后代检查，不能绕过平稳无滑落的条件。
    def transport_payload(carrier: str) -> None:
        for identifier in entities:
            preconditions[identifier + ".location"] = state[identifier + ".location"]  # 位置拓扑也决定“没有载荷”，移除载荷的动作不能从依赖审计中消失。
        dependents = [identifier for identifier in entities if _descends(state, entities, identifier, carrier)]  # 包括深层支撑器物。
        for identifier in dependents:
            if identifier + ".supported_by" in state:
                preconditions[identifier + ".supported_by"] = state[identifier + ".supported_by"]  # 明确记录有或没有支撑的读取。
        supported = [identifier for identifier in dependents if state.get(identifier + ".supported_by") is not None]  # 沿位置链保留的支撑需要额外保证。
        if supported:
            if action.get("transport_mode") != "quasistatic":
                raise ValueError("element_error: 本次搬运动作缺少明确的准静态方式，不能借用未来动作")
            conditions.append(_condition(scene, event["id"], "support_preserved", actor, carrier))
            for identifier in supported:
                preconditions[identifier + ".supported_by"] = state[identifier + ".supported_by"]
            unresolved.append({"entity": carrier, "rule_id": "conditional_support", "evidence": {
                "basis": "unknown", "quote": "", "explanation": "支撑后代仅在结构化平稳无滑落条件下保持；未进行动力学验证"}})

    if kind in ("open_door", "close_door", "enter_room"):
        if entities[target]["kind"] != "door":
            raise ValueError("element_error: 开关门或入室目标必须是 door")
        if kind == "enter_room":
            destination = action.get("destination")  # 门连接的已登记区域才可作为目的地。
            if not isinstance(destination, str) or destination not in entities or entities[destination]["kind"] not in _REGIONS:
                raise ValueError("element_error: enter_room 需要登记的区域 destination")
            entry_reachable()
            require(target + ".connects", destination)
            require(target + ".open", "open")
            if state.get(actor + ".holding") is not None:
                transport_payload(state[actor + ".holding"])
            direct[actor + ".location"] = destination
            direct[actor + ".position"] = "unspecified"  # 入口外的局部左右位置不能继承为房间内的位置。
            active[actor + ".action"] = "entering"
        else:
            if state[actor + ".root_location"] == "outside":
                entry_reachable()
            else:
                reachable(target)
            require(target + ".open", "closed" if kind == "open_door" else "open")
            if kind == "open_door":
                require(target + ".locked", False)
            direct[target + ".open"] = "open" if kind == "open_door" else "closed"
            active[actor + ".action"] = "opening" if kind == "open_door" else "closing"
    elif kind == "pick_up":
        if entities[target]["kind"] not in _HOLDABLE or entities[target]["role"] != "object":
            raise ValueError("element_error: pick_up 只支持登记的可持器物")
        reachable(target)
        require(actor + ".holding", None)
        require(target + ".held_by", None)
        require(target + ".attached_to", None)
        transport_payload(target)
        if target + ".supported_by" not in state:
            raise ValueError("element_error: pick_up 需要明确原 supported_by（无支撑用 null）")
        preconditions[target + ".supported_by"] = state[target + ".supported_by"]
        direct.update({target + ".supported_by": None, target + ".held_by": actor, target + ".location": actor,
                       target + ".position": "unspecified", actor + ".holding": target})  # 新父体下的位置没有依据时退回未指定。
        active[actor + ".action"] = "reaching"
    elif kind == "place_on":
        destination = action.get("destination")  # 支撑体必须已经登记，动作不能临时生成桌子。
        if not isinstance(destination, str) or destination not in entities or entities[destination]["kind"] not in _SUPPORTS or destination in (actor, target):
            raise ValueError("element_error: place_on 需要不同的登记支撑体 destination")
        reachable(destination)
        require(actor + ".holding", target)
        require(target + ".held_by", actor)
        require(destination + ".motion", "stationary")
        require(destination + ".support", "stable")
        transport_payload(target)
        direct.update({target + ".held_by": None, target + ".supported_by": destination, target + ".location": destination,
                       target + ".position": "unspecified", actor + ".holding": None})
        active[actor + ".action"] = "placing"
    elif kind == "move_object":
        position = action.get("position")  # 当前只建模区域内离散左右中位置，不提供跨房间传送。
        if entities[target]["kind"] not in _MOVABLE or entities[target]["role"] != "object" or position not in ("left", "right", "center") or "destination" in action:
            raise ValueError("element_error: move_object 只允许可移动器物在当前区域内移动到 left/right/center")
        reachable(target)
        require(target + ".attached_to", None)
        require(target + ".held_by", None)
        require(target + ".supported_by", None)
        require(target + ".location", state[actor + ".root_location"])
        require(target + ".motion", "stationary")
        transport_payload(target)
        direct[target + ".position"] = position
        active.update({actor + ".action": "moving_object", target + ".motion": "moving", target + ".position": "in_transit"})
        unresolved.append({"entity": target, "rule_id": "unmodeled_physics", "evidence": {"basis": "unknown", "quote": "", "explanation": "未给风、震动、摩擦或加速度数据；不判定额外滑落、倾倒、泼洒或破碎。支撑保持仅在明确平稳假设范围内成立"}})
    after = state | direct  # 完成态只改规则直接输出，不把进行时动作残留到后续。
    after.update(_derive(after, entities))
    during = state | active  # 取物进行时仍保留支撑和手持前态。
    during.update(_derive(during, entities))
    _check_invariants(after, entities)
    _check_invariants(during, entities)
    return preconditions, after, during, unresolved, conditions


# 为每项实际变化附上前后值、规则与来源；未变属性不伪造为效果。
def _effects(before: dict, after: dict, event: dict) -> tuple[list, list]:
    direct = []  # 动作直接改变的登记属性。
    propagated = []  # 由位置闭包计算的全局属性变化。
    for key, value in after.items():
        if key in before and _same(before[key], value):
            continue
        identifier, attribute = key.split(".")  # 效果引用精确实体及单个属性。
        rule = "inherit_location" if attribute in ("root_location", "world_position") else "action_complete" if attribute == "action" else event["kind"]  # 位置传播不冒充直接操作。
        evidence = deepcopy(event["evidence"]) if rule == event["kind"] else _rule_evidence(_RULES[rule])  # 保留原动作引文并说明其适用规则。
        evidence["explanation"] = evidence.get("explanation", "") + "；" + _RULES[rule] + "；规则推演不代表数据识别因果"
        effect = {"entity": identifier, "property": attribute, "before": before.get(key), "after": value, "rule_id": rule, "evidence": evidence}  # 缺失初值由 before:null 表示，同时完整快照保留缺失信息。
        (propagated if rule == "inherit_location" else direct).append(effect)
    return direct, propagated


# 在独立副本上编译动作，返回所有元素的每步快照及兼容旧分镜器的状态差量。
def compile_element_scene(scene: dict) -> dict:
    _check_json(scene)
    if not isinstance(scene, dict):
        raise ValueError("element_error: scene 必须是字典")
    compiled = deepcopy(scene)  # 外部解析器缓存与调用方输入不能被本函数修改。
    entities, initial = _prepare(compiled)  # 初态先完成全场登记及一致性检查。
    ordered = _ordered(compiled)  # 排序由 DAG 决定，不依赖动作数组顺序。
    state = initial.copy()  # 每个动作都读取上一个动作真正完成的世界状态。
    trace = []  # 完整轨迹以新字典保存，禁止后续动作回写前一帧。
    writers = {}  # 每个状态属性最近一次写入的事件；初态不伪造事件节点。
    dependencies = []  # 在当前规则内满足后续前置的状态依赖，与统计因果关系区分。
    for event in ordered:
        preconditions, after, during, unresolved, conditions = _apply(compiled, event, state, entities)  # 行为前置失败即中止，不能跳过动作。
        direct, propagated = _effects(state, after, event)  # 每项变化保留来源与规则。
        event["preconditions"] = preconditions
        event["required_conditions"] = conditions
        event["updates"] = {key: value for key, value in after.items() if key not in state or not _same(state[key], value)}
        event["active_state"] = {key: value for key, value in during.items() if key not in state or not _same(state[key], value)}
        sources = {}  # 按前置的最近写入事件合并依赖，避免从纯先后关系构造因果。
        for key in preconditions:
            if key in writers:
                sources.setdefault(writers[key], []).append(key)
        for source, keys in sources.items():
            dependencies.append({"source": source, "target": event["id"], "relation": "enables_under_rules", "state_keys": keys,
                                 "evidence": _rule_evidence("前一动作的状态输出满足本动作读取的前置或载荷拓扑条件；这是规则执行依赖，不承诺为最小因果集合")})
        writers.update({key: event["id"] for key in event["updates"]})
        changed = {effect["entity"] for effect in direct + propagated}  # 只读参与者不会因此被误记为发生状态变化。
        trace.append({"event_id": event["id"], "before": state.copy(), "after": after.copy(),
                      "direct_effects": direct, "propagated_effects": propagated,
                      "unchanged_entities": [identifier for identifier in entities if identifier not in changed],
                      "unresolved_effects": unresolved})
        state = after
    compiled["events"] = ordered
    compiled["element_trace"] = trace
    compiled["state_dependencies"] = dependencies
    compiled["element_model"]["rule_catalog"] = {identifier: {"description": description, "basis": "rule_based_not_data_identified"} for identifier, description in _RULES.items()}
    compiled["element_model"]["relation_scope"] = "initial_state"
    _check_json(compiled)
    try:
        json.dumps(compiled, allow_nan=False)  # 完整输出必须可编码，包括非核心附加元数据。
    except (ValueError, TypeError, OverflowError, RecursionError) as error:
        raise ValueError("element_error: 编译结果不能序列化为 JSON") from error
    return compiled


# 独立重编译并比较所有派生输出，拒绝手改更新、进行态、快照、效果或规则说明。
def validate_element_scene(scene: dict) -> None:
    _check_json(scene)
    if not isinstance(scene, dict) or not isinstance(scene.get("element_trace"), list):
        raise ValueError("element_error: 元素场景需要先经过 compile_element_scene 编译")
    expected = compile_element_scene(scene)  # 使用同一纯函数规则恢复可审计的唯一结果。
    for key in ("entities", "initial_state", "events", "element_trace", "element_model", "state_dependencies"):
        if json.dumps(scene.get(key), sort_keys=True, allow_nan=False) != json.dumps(expected[key], sort_keys=True, allow_nan=False):
            raise ValueError(f"element_error: {key} 与规则编译结果不一致，可能被篡改")
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

```text
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
      - name: Verify environment-first element propagation
        run: |
          python -B - <<'PY'
          import sys
          from pathlib import Path
          # 直接加载源码，检查环境器物登记、规则前置和完整场景快照。
          sys.path.insert(0, str(Path('src').resolve()))
          from causal_storyboard import build_storyboard
          # room 是显式开门、入室、平稳移桌链；没有请求任何模型。
          room = build_storyboard('房间里有一扇关闭的门，墙上挂着一幅画，桌上放着一个水杯。一个男孩打开门，然后走进房间，再平稳地把桌子移到房间右侧。')
          assert room['scene']['element_model']['construction_order'] == ['environment', 'objects', 'subjects']
          assert room['element_trace'][0]['after']['door.open'] == 'open'
          assert room['element_trace'][1]['after']['boy.location'] == 'room'
          assert room['element_trace'][2]['after']['cup.world_position'] == 'room:table=right/cup=unspecified'
          assert all('painting' in step['unchanged_entities'] for step in room['element_trace'])
          assert room['state_dependencies'][0]['state_keys'] == ['door.open']
          assert all(left['end_state'] == right['start_state'] for left, right in zip(room['shots'], room['shots'][1:]))
          # picked 复核拿取与放回时支撑、持有关系必须成对变更。
          picked = build_storyboard('房间里有一张桌子，桌上放着一个水杯，墙上挂着一幅画。一个男孩拿起水杯，然后把水杯放回桌上。')
          assert picked['element_trace'][0]['after']['cup.held_by'] == 'boy'
          assert picked['element_trace'][0]['after']['cup.supported_by'] is None
          assert picked['element_trace'][1]['after']['cup.supported_by'] == 'table'
          assert picked['element_trace'][1]['after']['boy.holding'] is None
          assert {entity['id'] for entity in build_storyboard('男孩打开门。')['scene']['entities']} == {'space', 'door', 'boy'}
          try:
              build_storyboard('房间里有一扇关闭的门。男孩走进房间。')
          except ValueError:
              pass
          else:
              raise AssertionError('closed door must prevent entry')
          PY
```
