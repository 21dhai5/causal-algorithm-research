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
