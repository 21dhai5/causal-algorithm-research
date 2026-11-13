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
