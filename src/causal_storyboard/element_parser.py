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
