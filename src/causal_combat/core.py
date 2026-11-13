"""仙侠战斗的规则设计模拟；不是统计因果估计、真实物理或通用文本抽取。"""

import math
import random

from causal_storyboard.core import validate_scene


DEFAULT_TEXT = "青衣剑修凝聚青色剑气，挥剑射向八米外的守卫；守卫举起金色灵盾，剑气与灵盾接触后，按剩余灵力决定格挡或破盾击退。"  # 默认创作参考，参数仍决定实际结果。
MODE = "RULE_BASED_DESIGN_SIMULATION"  # 与研究仓库中的统计因果估计器区分。
FPS = 30  # 固定采样频率，全部事件边界也位于这个时间网格。
MIN_CHARGE = 0.15  # 低于此比例时不释放攻击，也不扣除角色灵力。
CONTACT_RADIUS_M = 0.75  # 盾与身体共用的简化横向接触半径，单位米。
LOSS_PER_M = 0.8  # 虚构灵力单位/米；沿实际剑气路径线性衰减。
SHOCKWAVE_THRESHOLD = 20  # 只有命中且穿盾剩余灵力达到该值才产生冲击波。
NEGATIVE_PROMPT = "禁止未接触先受伤、未命中震屏、格挡扣血、无灵力发射、凭空碎石、身份漂移、额外角色、血腥、字幕、水印；不把本设计称为已生成图片或视频。"  # 全片的因果与呈现约束。


# 只接受确切的Python整数或浮点数，排除布尔值、字符串及非有限数。
def _number(name: str, value, lower: float, upper: float) -> float:
    if type(value) not in (int, float) or not lower <= value <= upper:
        raise ValueError(f"{name} 必须是 [{lower}, {upper}] 范围内的有限实数，不能是布尔值。")
    return float(value)


# 设计假设不借用原文当作已观察到的命中或损伤证据。
def _evidence(explanation: str) -> dict:
    return {"basis": "commonsense_assumption", "quote": "", "explanation": explanation}


# 小数只在显示位置等非判定字段中舍入；分支判定保留内部精度。
def _rounded(value: float) -> float:
    return round(value, 6)


# 根据参数建立几何与能量预算，所有数值都是明确声明的虚构设计。
def _resolve(charge: float, distance_m: float, shield: float, aim: float) -> dict:
    launched = charge >= MIN_CHARGE  # 低蓄力只演示失败收束。
    attack_energy = 100 * charge if launched else 0  # 角色初始灵力固定为100。
    target_x = distance_m - 0.6 if shield > 0 else distance_m  # 有盾时先在身体前方0.6米检测接触。
    start = [0.65, 1.2, 0]  # 剑尖发射点，y轴竖直向上。
    endpoint = [target_x, 1.2, aim]  # 横向偏移定义在本次检测平面。
    path_length = math.hypot(target_x - start[0], aim)  # 距离包含横向偏移。
    path_loss = LOSS_PER_M * path_length  # 达到检测平面需要消耗的灵力。
    reaches_plane = launched and attack_energy > path_loss  # 恰好耗尽也不能造成接触伤害。
    geometry_contact = abs(aim) <= CONTACT_RADIUS_M  # 固定高度下的圆形截面横向检测。
    contact = reaches_plane and geometry_contact  # 能量和几何必须同时满足。
    at_contact = attack_energy - path_loss if contact else 0  # 未接触时没有接触能量。
    absorbed = min(shield, at_contact) if contact else 0  # 盾最多吸收自身强度。
    residual = at_contact - absorbed if contact else max(0, attack_energy - path_loss)  # 落空余能最终消散。
    shield_remaining = shield - absorbed  # 未接触时盾强度保持原值。
    hit = contact and residual > 0  # 有穿盾余能才击中身体。
    damage = min(100, residual * 0.8) if hit else 0  # 生命值采用独立的虚构设计倍率。
    kind = "insufficient_energy" if not launched else "hit" if hit else "blocked" if contact else "miss"  # 唯一结果分支。
    labels = {"insufficient_energy": "蓄力不足，未释放剑气", "hit": "剑气命中，目标受击后退", "blocked": "灵盾吸收剑气，守卫无伤", "miss": "剑气偏离目标" if reaches_plane else "剑气途中耗尽"}  # 区分偏离与耗尽。
    travel_fraction = 1 if reaches_plane else min(1, attack_energy / path_loss) if launched else 0  # 耗尽时在目标前停止。
    travel_end = [start[index] + (endpoint[index] - start[index]) * travel_fraction for index in range(3)]  # 实际终点仍在同一直线上。
    return {
        "launched": launched, "contact": contact, "hit": hit, "kind": kind, "label": labels[kind],  # 离散结果。
        "attack_energy": attack_energy, "energy_at_contact": at_contact, "absorbed_energy": absorbed, "remaining_energy": residual,  # 统一的虚构灵力单位。
        "damage": damage, "shield_remaining": shield_remaining, "flight_loss": min(attack_energy, path_loss),  # 损耗不超过已发射能量。
        "start": start, "travel_end": travel_end, "path_length": path_length * travel_fraction,  # 连续直线轨迹。
        "collision_point_m": endpoint if contact else None, "speed_m_s": 12 + 12 * charge,  # 速度只改变时间，不绕过接触条件。
        "shockwave": hit and residual >= SHOCKWAVE_THRESHOLD,  # 碎石依赖同一次条件冲击波。
    }


# 为每个稳定身份生成独立素材；全部造型均明示为设计补充。
def _elements(text: str, parameters: dict, result: dict) -> list:
    rng = random.Random(parameters["seed"])  # 局部随机源不修改其他线程的随机状态。
    finish = rng.choice(("细密云纹", "断续流线纹", "回旋篆纹"))  # 种子控制剑身外观。
    fragments = rng.randint(7, 12)  # 帧特效和材质说明共用碎石数量。
    distance = parameters["distance_m"]  # 防守者脚下的x坐标，单位米。
    collision = result["collision_point_m"] or result["travel_end"]  # 未接触时仅为禁用素材的候选位置。
    summary = (f"蓄力{parameters['charge']:.2f}，间距{distance:g}米，瞄准横移{parameters['aim_offset_m']:g}米，"
               f"初始盾强{parameters['shield']:g}，结果：{result['label']}；剩余灵力{result['remaining_energy']:.2f}虚构单位")  # 每份素材携带权威参数和结果。
    specs = [  # 每项依次定义身份、类别、名称、所有者、原点、附着与触发数据、专属材质。
        ("attacker", "actor", "青衣剑修", None, [0, 0, 0], {"attachment_id": None, "height_m": 1.8, "trigger": "charge", "initial_energy": 100},
         "青衣剑修的衣摆呈分层轻纱，发冠和冷青轮廓光跨帧一致；只在释放时伸臂挥剑。"),
        ("defender", "actor", "执盾守卫", None, [distance, 0, 0], {"attachment_id": None, "height_m": 1.8, "hit_radius_m": CONTACT_RADIUS_M, "trigger": "hit 后才 recoil", "initial_hp": 100},
         "玄色护甲守卫站在目标截面后方；生命值减少后才后仰和位移，格挡与落空保持站姿。"),
        ("weapon", "weapon", "凝霜长剑", "attacker", result["start"], {"attachment_id": "attacker", "attachment_point": "right_hand", "length_m": 1, "surface_pattern": finish, "trigger": "charge -> release"},
         f"银白长剑带{finish}，青光沿剑脊向剑尖汇聚；能量不足时光纹回退而不脱离剑尖。"),
        ("skill", "skill", "青岚剑诀", "attacker", result["start"], {"attachment_id": "weapon", "trigger": f"charge >= {MIN_CHARGE} 才释放", "attack_energy": result["attack_energy"], "flight_loss": result["flight_loss"], "energy_unit": "虚构归一化灵力单位", "damage_multiplier": 0.8, "dissipation_energy": result["remaining_energy"]},
         "青岚剑诀是贴附剑身的青绿环形灵纹，蓄力比例控制光环密度，区分手中聚能与已经脱剑的飞行体。"),
        ("projectile", "projectile", "青色剑气", "attacker", result["start"], {"attachment_id": None, "source_attachment_id": "weapon", "height_m": 1.2, "radius_m": 0.12, "aim_offset_m": parameters["aim_offset_m"], "speed_m_s": result["speed_m_s"], "loss_per_m": LOSS_PER_M, "trigger": "release 完成后 flight", "enabled": result["launched"]},
         f"梭形青色剑气有亮白刃芯和透明青绿外焰，沿固定直线前进，每米衰减{LOSS_PER_M}灵力；尾迹只能跟随实际飞行位置。"),
        ("shield", "shield", "金色灵盾", "defender", [distance - 0.6, 1.2, 0], {"attachment_id": "defender", "attachment_point": "left_hand", "radius_m": CONTACT_RADIUS_M, "strength": parameters["shield"], "remaining_strength": result["shield_remaining"], "trigger": "verified collision 且 strength > 0", "enabled": parameters["shield"] > 0},
         "金色半透明灵盾带同心六边纹；接触后才从接触点扩散涟漪，耗尽时裂开；零强度时不显示盾面。"),
        ("impact", "impact", "接触光爆", None, collision, {"attachment_id": "shield" if parameters["shield"] > 0 else "defender", "trigger": "collision verified", "enabled": result["contact"], "requires_contact": True},
         "接触光爆是白青短促光斑与金色火星混合层，仅出现于已核验的接触点，落空时完全禁用。"),
        ("shockwave", "shockwave", "命中冲击波", None, [distance, 0.03, collision[2]], {"attachment_id": None, "trigger": f"hit 且 remaining_energy >= {SHOCKWAVE_THRESHOLD}", "enabled": result["shockwave"], "requires_contact": True, "max_radius_m": 1 + result["remaining_energy"] / 25 if result["shockwave"] else 0},
         "命中冲击波是贴地扩散的淡青圆环，透明度随半径增加而降低；只由足够余能的已命中事件触发。"),
        ("debris", "debris", "地面碎石", "ground", [distance, 0, collision[2]], {"attachment_id": "ground", "trigger": "shockwave 后 ground.cracked", "enabled": result["shockwave"], "requires_contact": True, "fragment_count": fragments, "seed": parameters["seed"]},
         f"地面碎石为{fragments}枚有灰白断面的小石块，从同一地面裂纹沿低抛物线跳起；没有冲击波就不出现。"),
        ("ground", "environment", "青石演武台", None, [distance / 2, 0, 0], {"attachment_id": None, "trigger": "debris 阶段才写入 cracked", "plane_y_m": 0, "material": "青灰石板"},
         "青石演武台由连续青灰石板组成，保留人物脚底接触阴影；裂纹只在条件冲击波触发后出现。"),
        ("environment", "environment", "山门薄雾", None, [distance / 2, 0, -4], {"attachment_id": None, "trigger": "全程静态背景", "wind_m_s": 0},
         "远处山门与淡蓝薄雾形成背景，雾层不遮挡剑气和灵盾的间距判断，不增加旁观者或机关。"),
        ("camera", "camera", "连续侧视机位", None, [distance / 2, 3.2, 10], {"attachment_id": None, "trigger": "hit 完成后的 recoil 才允许震屏", "requires_contact": True, "shake_enabled": result["hit"], "projection": "side_view"},
         "连续侧视机位保持剑修在左、守卫在右和地平线稳定；只在命中的反冲阶段施加有限衰减震动。"),
        ("sound", "sound", "剑鸣与碰撞声轨", None, [distance / 2, 1.2, 0], {"attachment_id": None, "trigger": "charge 剑鸣；release 破空；verified collision 短音；hit 受击重音", "collision_enabled": result["contact"]},
         "声音素材分为蓄力低鸣、释放破空、接触脆响和受击低频；没有接触禁用撞击声，没有命中禁用受击重音。"),
    ]
    elements = []  # 固定顺序供客户端按ID建立查找表。
    for identifier, kind, label, owner, position, data, description in specs:  # 配置变量一一对应契约字段。
        elements.append({
            "id": identifier, "kind": kind, "label": label, "owner_id": owner,  # 身份和所有权不因分支而漂移。
            "data": {"position_m": [_rounded(value) for value in position], "material": description, **data},  # 所有位置单位为米，每项显式携带材质与附着。
            "description": f"{description} 本次设计：{summary}。",  # 素材说明与本次结果相互约束。
            "material_prompt": f"仙侠交互特效素材：{label}。元素ID={identifier}；{description} 参数与触发：{summary}；{data}。创作参考：{text}。参考文字不覆盖规则结果。",  # 可复制使用，不调用模型。
            "negative_prompt": f"{label}专用约束：{NEGATIVE_PROMPT}",  # 每个条目可独立携带约束。
            "source": {"basis": "commonsense_assumption", "quote": ""},  # 不伪造原文抽取证据。
        })
    return elements


# 追加有持续时间的事件并推进规划状态；回放按同一更新规则重建。
def _add_event(events: list, state: dict, identifier: str, kind: str, label: str,
               participants: list, ticks: int, required: tuple, updates: dict,
               active: dict, trigger: str, moments: tuple) -> None:
    start_tick = round(events[-1]["end_s"] * FPS) if events else 0  # 整数tick避免相邻区间出现浮点缝隙。
    event = {
        "id": identifier, "kind": kind, "label": label,  # 一个ID只代表一次发生。
        "start_s": start_tick / FPS, "end_s": (start_tick + ticks) / FPS,  # 对外时间单位为秒。
        "depends_on": [], "participants": participants,  # 物理与设计依赖稍后独立设置，不把时间相邻当作因果。
        "preconditions": {key: state[key] for key in required}, "active_state": active, "updates": updates,  # 先核对既有状态，结束时写结果。
        "keyframes": dict(zip(("before", "during", "after"), moments)),  # 每项描述一个具体瞬间。
        "trigger": trigger, "description": label + "；" + trigger, "evidence": _evidence(trigger),  # 规则不是统计推断证据。
    }
    events.append(event)
    state.update(updates)


# 只建立成立的分支；格挡、落空、低蓄力不会包含受击、反冲或破坏事件。
def _plan(parameters: dict, result: dict) -> tuple:
    initial = {
        "attacker.energy": 100, "attacker.pose": "ready",  # 角色灵力只在释放完成时扣除。
        "defender.hp": 100, "defender.pose": "guard",  # 伤害和位移严格排在接触后。
        "skill.stored_energy": 0, "skill.status": "idle",  # 手中聚能与飞行体能量分开。
        "projectile.status": "absent", "projectile.energy": 0, "projectile.contact": False,  # 释放前没有独立飞行体。
        "shield.strength": parameters["shield"], "shield.status": "ready" if parameters["shield"] > 0 else "absent",  # 零强度无隐形格挡。
        "impact.confirmed": False, "impact.active": False, "impact.energy": 0,  # 接触历史、可见光爆与命中反馈余能分开。
        "shockwave.active": False, "debris.active": False, "ground.cracked": False,  # 环境反馈默认关闭。
        "camera.shake": 0, "sound.cue": "silent",  # 摄影和声轨与状态同源。
    }
    state = initial.copy()  # 最终状态的规划累积器，不共享给帧快照。
    events = []  # 所有时段均在30Hz网格上。
    requested = 100 * parameters["charge"]  # 低蓄力允许短暂聚光，但不消耗角色灵力。
    _add_event(events, state, "charge", "charge", "剑修凝聚剑诀", ["attacker", "weapon", "skill", "sound"],
               max(1, round((0.45 + 0.9 * parameters["charge"]) * FPS)), ("attacker.energy", "skill.status"),
               {"skill.stored_energy": requested, "skill.status": "charged", "attacker.pose": "charged", "sound.cue": "charge_end"},
               {"skill.status": "charging", "attacker.pose": "charging", "sound.cue": "charge"}, "蓄力参数控制剑身聚能，不代表已经发生攻击",
               ("剑尖尚无独立剑气", "青色灵纹向剑尖汇聚", "剑尖聚能达到本次蓄力比例"))
    if not result["launched"]:
        _add_event(events, state, "abort", "insufficient_energy", "蓄力不足，取消释放", ["attacker", "skill", "weapon"], 5,
                   ("skill.status", "skill.stored_energy"), {"skill.status": "cancelled", "skill.stored_energy": 0}, {},
                   f"charge < {MIN_CHARGE}：不创建飞行体、不扣除角色灵力、不检测伤害", ("微弱剑光停留在剑尖", "剑光向掌心回收", "没有剑气离剑"))
    else:
        _add_event(events, state, "release", "release", "剑气脱剑释放", ["attacker", "weapon", "skill", "projectile", "sound"], 4,
                   ("skill.status", "attacker.energy"), {"attacker.energy": 100 - result["attack_energy"], "attacker.pose": "released", "skill.stored_energy": 0,
                   "skill.status": "released", "projectile.status": "released", "projectile.energy": result["attack_energy"], "sound.cue": "release"},
                   {"attacker.pose": "releasing", "sound.cue": "release"}, f"charge >= {MIN_CHARGE}：发射{result['attack_energy']:.2f}虚构灵力单位",
                   ("剑气仍贴附剑尖", "挥剑推出青色刃光", "独立剑气离开剑尖"))
        _add_event(events, state, "flight", "flight", "剑气沿瞄准直线飞行", ["projectile", "defender", "shield"],
                   max(2, math.ceil(result["path_length"] / result["speed_m_s"] * FPS)), ("projectile.status", "projectile.energy"),
                   {"projectile.status": "arrived" if result["contact"] else "missed", "projectile.energy": max(0, result["attack_energy"] - result["flight_loss"])},
                   {"projectile.status": "flying"}, "沿路径每米消耗0.8虚构灵力；到达检测平面之前禁止接触反馈",
                   ("剑气刚离剑尖，目标尚未接触", "剑气沿1.2米高度接近目标", "剑气到达检测面或在途中耗尽"))
        if result["contact"]:
            _add_event(events, state, "collision", "collision", "几何与能量共同确认接触", ["projectile", "shield" if parameters["shield"] > 0 else "defender", "impact", "sound"], 1,
                       ("projectile.status", "projectile.energy", "projectile.contact"), {"projectile.contact": True, "impact.confirmed": True, "impact.active": True, "sound.cue": "contact"},
                       {"projectile.contact": True, "impact.confirmed": True, "impact.active": True, "sound.cue": "contact"},
                       f"已到达检测面且 |aim_offset_m| <= {CONTACT_RADIUS_M}、灵力 > 0；此时才允许接触光爆",
                       ("剑气与截面仍有微小间距", "剑气第一次触及目标截面", "接触已确认，尚未结算身体伤害"))
            if parameters["shield"] > 0:
                _add_event(events, state, "absorb", "shield_absorb", "灵盾按强度吸收剑气", ["shield", "projectile", "impact"], 6,
                           ("impact.confirmed", "projectile.contact", "shield.strength"), {"shield.strength": result["shield_remaining"], "projectile.energy": result["remaining_energy"],
                           "shield.status": "holding" if result["shield_remaining"] > 0 else "exhausted"}, {"shield.status": "absorbing"},
                           f"吸收 min(接触灵力, 盾强度) = {result['absorbed_energy']:.2f}；无穿盾余能不扣血",
                           ("灵盾保留接触前强度", "金色涟漪吞没部分青色刃光", "灵盾与剑气按同一吸收量减少能量"))
                if result["shield_remaining"] == 0:
                    _add_event(events, state, "shield_break", "shield_break", "灵盾耗尽并碎裂", ["shield", "projectile"], 3,
                               ("shield.strength", "shield.status", "impact.confirmed"), {"shield.status": "broken"}, {"shield.status": "breaking"},
                               "盾强度已为零才显示裂纹；恰好抵消全部剑气时破盾也不造成身体伤害",
                               ("耗尽的盾面开始失光", "金色盾面沿裂纹分离", "盾面消失，余能按吸收结算值继续"))
            if result["hit"]:
                _add_event(events, state, "hit", "hit", "剩余剑气命中守卫", ["projectile", "defender", "impact", "sound"], 2,
                           ("impact.confirmed", "projectile.energy", "defender.hp"), {"defender.hp": 100 - result["damage"], "defender.pose": "hit", "projectile.status": "spent", "projectile.energy": 0, "impact.energy": result["remaining_energy"], "sound.cue": "hit"},
                           {"impact.active": True, "sound.cue": "hit"}, f"接触已确认且穿盾余能 > 0；伤害 = min(100, 余能 × 0.8) = {result['damage']:.2f}",
                           ("余能剑气即将传给守卫", "青色刃光接触护甲", "生命值减少后才准备反冲"))
                _add_event(events, state, "recoil", "recoil", "守卫受击后退，镜头短促震动", ["defender", "camera"], 8,
                           ("defender.hp", "defender.pose", "impact.confirmed"), {"defender.pose": "recoiled", "camera.shake": 0}, {"defender.pose": "recoiling", "camera.shake": min(1, result["remaining_energy"] / 80)},
                           "只有hit已完成才产生反冲与震屏；格挡和落空没有该事件",
                           ("守卫已受到本次伤害", "守卫沿剑气方向后仰半步", "守卫站稳，镜头震动归零"))
                if result["shockwave"]:
                    _add_event(events, state, "shockwave", "shockwave", "命中余能向外扩散", ["shockwave", "ground", "impact"], 10,
                               ("impact.confirmed", "defender.hp", "impact.energy"), {"shockwave.active": False}, {"shockwave.active": True},
                               f"本次已命中且穿盾余能 >= {SHOCKWAVE_THRESHOLD}，生成一次贴地圆环",
                               ("命中余能仍集中在接触处", "淡青圆环沿石台扩散", "圆环衰减并到达局部石板"))
                    _add_event(events, state, "debris", "debris", "冲击波激起局部石屑", ["debris", "ground"], 12,
                               ("impact.confirmed", "ground.cracked"), {"ground.cracked": True, "debris.active": False}, {"ground.cracked": True, "debris.active": True},
                               "先发生条件冲击波才允许地面开裂与石屑抛起",
                               ("石板尚未开裂", "接触附近石板开裂，石屑跳起", "石屑落回台面并淡出"))
        else:
            _add_event(events, state, "miss", "miss", result["label"], ["projectile", "defender", "shield"], 4,
                       ("projectile.status", "impact.confirmed", "defender.hp", "shield.strength"), {"projectile.status": "missed"}, {},
                       "偏离接触截面或途中灵力耗尽；没有接触、碰撞声、伤害、震屏或碎石",
                       ("剑气尚未接触目标", "剑气侧方掠过或空中熄灭", "守卫生命与盾强度保持原值"))
    _add_event(events, state, "dissipate", "dissipate", "剑光和动态反馈消散", ["skill", "projectile", "impact", "shockwave", "debris", "sound"], 18,
               ("attacker.energy",), {"skill.status": "idle", "skill.stored_energy": 0, "projectile.status": "dissipated", "projectile.energy": 0, "projectile.contact": False,
               "impact.active": False, "impact.energy": 0, "shockwave.active": False, "debris.active": False, "camera.shake": 0, "sound.cue": "silent", "attacker.pose": "ready"},
               {"sound.cue": "fade"}, "余能仅用于渐隐，不追加攻击、伤害或环境事件",
               ("本次分支已结算", "剑光、尾迹与声音逐渐变淡", "动态反馈结束，保留生命、盾强与裂纹结果"))
    return initial, state, events


# 保存有界亮度、独立传播进度和位置副本；进度用于单调扩散，不随亮度回缩。
def _effect(effects: list, element_id: str, kind: str, strength: float, position: list, progress: float = 0) -> None:
    effects.append({"element_id": element_id, "kind": kind, "strength": _rounded(max(0, min(1, strength))), "position_m": [_rounded(value) for value in position], "progress": _rounded(max(0, min(1, progress)))})


# 按事件更新重放固定步长帧；不读取最终状态，避免提前显示未来伤害。
def _frames(initial: dict, events: list, elements: list, parameters: dict, result: dict) -> list:
    positions = {element["id"]: element["data"]["position_m"] for element in elements}  # 素材原点只读，运动保存在帧内。
    by_id = {event["id"]: event for event in events}  # 条件分支缺失的事件不会被误播放。
    end_tick = round(events[-1]["end_s"] * FPS)  # 最后一帧精确等于片段时长。
    frames = []  # 每帧持有独立字典，拖动回放不依赖历史播放方向。
    contact_time = by_id["collision"]["start_s"] if "collision" in by_id else None  # 所有接触反馈共用核验时间。
    for tick in range(end_tick + 1):  # 使用整数tick，避免累加误差遗漏端点。
        moment = tick / FPS  # 对外时间单位为秒。
        state = initial.copy()  # 每帧从初态重建。
        active = []  # 当前模型顺序执行，但契约使用列表。
        effects = []  # 未触发的视觉层不会自动出现。
        projectile = None  # 不存在或已消散的剑气不占据世界位置。
        for event in events:  # 只应用已完成事件更新和当前活动状态。
            if moment >= event["end_s"]:
                state.update(event["updates"])
            elif moment >= event["start_s"]:
                state.update(event["active_state"])
                active.append(event["id"])
        phase = by_id[active[0]]["kind"] if active else "complete"  # 阶段名直接对应实际事件。
        progress = 0  # 当前事件内0到1的时间比例。
        if active:
            event = by_id[active[0]]  # 一个顺序阶段内所有插值使用同一时间区间。
            progress = (tick - round(event["start_s"] * FPS)) / (round(event["end_s"] * FPS) - round(event["start_s"] * FPS))
        if phase == "charge":
            state["skill.stored_energy"] = 100 * parameters["charge"] * progress
            _effect(effects, "skill", "charge", parameters["charge"] * progress, positions["weapon"])
        elif phase == "release":
            _effect(effects, "skill", "charge", parameters["charge"] * (1 - progress), positions["weapon"])
        elif phase == "insufficient_energy":
            _effect(effects, "skill", "charge", parameters["charge"] * (1 - progress), positions["weapon"])
        if phase == "flight":
            projectile = [result["start"][index] + (result["travel_end"][index] - result["start"][index]) * progress for index in range(3)]  # 沿同一条几何轨迹连续运动。
            state["projectile.energy"] = max(0, result["attack_energy"] - result["flight_loss"] * progress)
            _effect(effects, "projectile", "trail", state["projectile.energy"] / 100, projectile)
        elif result["launched"] and phase in ("collision", "shield_absorb", "shield_break", "hit", "miss"):
            projectile = result["travel_end"].copy()  # 结算接触时停在已达到的截面，不穿盾显示。
            if phase == "shield_absorb":
                state["shield.strength"] = parameters["shield"] - result["absorbed_energy"] * progress
                state["projectile.energy"] = result["energy_at_contact"] - result["absorbed_energy"] * progress
            if phase == "hit":
                projectile[0] += (parameters["distance_m"] - projectile[0]) * progress  # 破盾后短距离传递至身体，伤害在本事件结束才写入。
                state["projectile.energy"] = result["remaining_energy"] * (1 - progress)
                state["impact.energy"] = result["remaining_energy"] * progress  # 剑气余能转入同一次命中反馈，不复制出第二份灵力。
            if phase == "miss":
                _effect(effects, "projectile", "trail", result["remaining_energy"] / 100 * (1 - progress), projectile)
        if contact_time is not None and moment >= contact_time and active and phase not in ("miss", "insufficient_energy", "dissipate"):
            if phase in ("collision", "shield_absorb", "shield_break", "hit", "recoil"):
                impact_position = [parameters["distance_m"], 1.2, parameters["aim_offset_m"]] if phase == "recoil" else projectile if phase == "hit" else positions["impact"]  # 破盾后的身体反馈与原盾面接触分开定位。
                _effect(effects, "impact", "impact", min(1, result["energy_at_contact"] / 100) * (1 - 0.7 * progress), impact_position)
            if phase in ("shield_absorb", "shield_break"):
                _effect(effects, "shield", "shield", (result["absorbed_energy"] / max(1, result["energy_at_contact"])) * (1 - 0.5 * progress), positions["shield"])
        if phase == "recoil":
            state["camera.shake"] *= 1 - progress  # 镜头震动只在受伤后的反冲阶段衰减。
            _effect(effects, "defender", "afterimage", result["damage"] / 100 * (1 - progress), positions["defender"])
        elif phase == "shockwave":
            _effect(effects, "shockwave", "shockwave", math.sin(math.pi * progress), positions["shockwave"], progress)
        elif phase == "debris":
            _effect(effects, "debris", "debris", math.sin(math.pi * progress), positions["debris"], progress)
        elif phase == "dissipate" and result["launched"]:
            _effect(effects, "projectile", "afterimage", min(0.3, result["remaining_energy"] / 100) * (1 - progress), result["travel_end"])
            state["impact.active"] = False  # 渐隐不再是新的接触或环境反馈。
        frames.append({
            "t_s": moment, "phase": phase, "projectile_position_m": [_rounded(value) for value in projectile] if projectile is not None else None,  # 公共时间和位置契约。
            "state": state, "active_event_ids": active, "effects": effects,  # 每帧完整状态与显式特效触发。
        })
    return frames


# 将有限文本作为创作简报，参数作为权威设计输入；不调用网络、模型、文件或统计估计器。
def build_combat(text: str = DEFAULT_TEXT, *, charge: float = 0.8, distance_m: float = 8,
                 shield: float = 50, aim_offset_m: float = 0, seed: int = 7) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError("text 必须是1至4000字符的非空字符串。")
    parameters = {
        "charge": _number("charge", charge, 0, 1),  # 蓄力比例，决定释放能量与蓄力时长。
        "distance_m": _number("distance_m", distance_m, 2, 24),  # 两角色脚下的水平距离，单位米。
        "shield": _number("shield", shield, 0, 120),  # 初始盾强度，单位为虚构归一化灵力。
        "aim_offset_m": _number("aim_offset_m", aim_offset_m, -5, 5),  # 目标检测平面处的z轴偏移，单位米。
        "seed": seed,  # 整数种子只控制可复现外观与碎石配置。
    }
    if type(seed) is not int or not 0 <= seed < 2 ** 32:
        raise ValueError("seed 必须是 [0, 2**32) 范围内的整数，不能是布尔值。")
    result = _resolve(parameters["charge"], parameters["distance_m"], parameters["shield"], parameters["aim_offset_m"])  # 同一输入无全局随机副作用。
    elements = _elements(text, parameters, result)  # 全部元素始终保留稳定身份，包括本次未触发的素材。
    initial, final, events = _plan(parameters, result)  # 初态、终态和事件一起生成，避免三者分支不一致。
    rules = [
        f"蓄力比例低于{MIN_CHARGE}不释放；否则发射能量=100×蓄力，并在释放完成时从角色灵力扣除。",
        f"剑气沿米制直线以1.2米高度飞行，每米消耗{LOSS_PER_M}虚构灵力；到达目标前不能产生接触反馈。",
        f"只有到达目标检测面、剩余灵力>0且横向偏移绝对值<={CONTACT_RADIUS_M}米才确认接触。",
        "接触后，灵盾吸收量=min(盾强度,接触灵力)；同量扣除双方能量，盾为零才显示破裂。",
        "接触已确认且穿盾余能>0才受击；伤害=min(100,余能×0.8)，hit完成后才反冲与震屏。",
        f"命中且穿盾余能>={SHOCKWAVE_THRESHOLD}才产生一次冲击波，随后才允许地面裂纹和碎石。",
        "偏离、途中耗尽、格挡和未释放都不扣血；未接触不碰撞、不震屏、不破坏地面。",
        "剩余灵力最终转换为反馈并消散；remaining_energy是吸收后的可用余能，不是最后一帧的飞行体能量。",
    ]  # 人类可读规则与帧、叙事、素材共享相同判定。
    assumptions = [
        _evidence("输入全文只作为自由创作简报保留；不声称通用自然语言抽取。角色、青色剑气和金色灵盾采用固定仙侠模板；数值参数覆盖简报中的距离、结果等描述。"),
        _evidence("坐标单位米，y轴向上、z轴为横向；剑修脚下[0,0,0]，守卫脚下[distance_m,0,0]，剑尖[0.65,1.2,0]。"),
        _evidence("有盾先在守卫前0.6米检测，无盾在身体位置检测；两者简化为半径0.75米的同高截面，忽略真实流体、人体和护甲求解。"),
        _evidence("角色灵力100、生命100，盾强与伤害采用虚构归一化单位；这是可解释的设计模拟，不是可验证现实定律或统计因果效应估计。"),
        _evidence("skill.stored_energy是角色已有灵力中的预留读数，不能与attacker.energy相加；释放后才扣除角色灵力。命中后飞行体余能转入impact.energy，供同一次反馈消散，不生成第二份能量。"),
        _evidence("以30Hz整数tick顺序调度；状态更新在事件完成时提交，持续飞行、吸收等只在活动帧内插值；最后一帧严格等于duration_s。"),
        _evidence("seed只控制固定素材纹样和石屑数量，不控制命中率；不生成图片、视频或音频文件。"),
    ]  # 明确区分设计补充与原文引文。
    dependencies = {
        "charge": ([], "enables"), "abort": (["charge"], "enables"),  # 蓄力是否达标由数值门槛决定。
        "release": (["charge"], "enables"), "flight": (["release"], "causes"),  # 脱剑为飞行提供实体和能量。
        "collision": (["flight"], "enables"), "miss": (["flight"], "enables"),  # 飞行结束后才可以核验几何与能量。
        "absorb": (["collision"], "causes"), "shield_break": (["absorb"], "causes"),  # 接触造成吸收，耗尽吸收造成破裂。
        "hit": (["collision"] + (["absorb", "shield_break"] if parameters["shield"] > 0 else []), "enables"),  # 有盾时还必须完成吸收并解除盾面。
        "recoil": (["hit"], "causes"), "shockwave": (["hit"], "causes"),  # 两个反馈都由命中触发，不把反冲误写成冲击波的原因。
        "debris": (["shockwave"], "causes"), "dissipate": ([events[-2]["id"]], "enables"),  # 碎石需要真实冲击波；渐隐等待本次分支结算。
    }
    relations = []  # 只输出本次实际存在的条件分支，不把顺序相邻直接转为因果。
    for event in events:  # depends_on与图边使用同一组显式依赖。
        parents, relation_kind = dependencies[event["id"]]  # 父事件身份及其规则关系类型。
        event["depends_on"] = parents.copy()
        for parent in parents:  # 一个事件可同时要求接触和破盾完成。
            relations.append({"source": parent, "target": event["id"], "relation": relation_kind, "rule": event["trigger"], "evidence": _evidence(event["trigger"])})
    scene = {
        "input_text": text, "entities": [{"id": element["id"], "label": element["label"], "evidence": _evidence("固定仙侠模板中的设计实体")} for element in elements],  # 复用已有实体引用校验。
        "world": {"coordinate_unit": "m", "mode": MODE}, "initial_state": initial, "assumptions": assumptions,  # 只包含有限JSON值。
        "continuity": {"design": "稳定ID、米制坐标、同一剑气和一次攻击"}, "events": events,  # 活动状态与关键帧使用现有故事板契约。
        "temporal_relations": [{"source": events[index - 1]["id"], "target": event["id"], "relation": "before", "evidence": _evidence("设计阶段依次播放，不由此推出因果")} for index, event in enumerate(events) if index],  # 顺序调度独立于因果边。
        "causal_relations": relations,  # 已声明规则因果DAG，不混入未知边。
    }
    validate_scene(scene)  # 复用已有证据、实体、状态前置与有向无环校验，不改变旧行为。
    frames = _frames(initial, events, elements, parameters, result)  # 状态回放只依据本次经过验证的事件。
    impact_time = next((event["start_s"] for event in events if event["id"] == "collision"), None)  # 落空和低蓄力没有接触时刻。
    outcome = {key: result[key] for key in ("kind", "label", "attack_energy", "energy_at_contact", "absorbed_energy", "remaining_energy", "damage", "shield_remaining", "hit", "collision_point_m")}  # 公开结果仅保留前端约定字段。
    outcome["impact_time_s"] = impact_time
    description = (f"规则设计模拟：{result['label']}。蓄力{parameters['charge']:.2f}、间距{parameters['distance_m']:g}米、"
                   f"瞄准横移{parameters['aim_offset_m']:g}米、盾强{parameters['shield']:g}。"
                   f"发射灵力{result['attack_energy']:.2f}，飞行衰减{result['flight_loss']:.2f}，接触灵力{result['energy_at_contact']:.2f}，"
                   f"灵盾吸收{result['absorbed_energy']:.2f}，剩余灵力{result['remaining_energy']:.2f}，伤害{result['damage']:.2f}，"
                   f"剩余盾强{result['shield_remaining']:.2f}。依次呈现：{' → '.join(event['label'] for event in events)}。"
                   "以上灵力均为虚构归一化单位；输入文字是创作参考，结果由参数与接触规则决定。")  # 叙事只陈述真正存在的事件链。
    return {
        "schema_version": "fantasy-combat-v1", "mode": MODE, "input_text": text, "parameters": parameters,  # 数据协议与原文完整保留。
        "duration_s": events[-1]["end_s"], "assumptions": assumptions, "elements": elements,  # 造型与世界补充显式声明。
        "events": events, "causal_relations": relations, "initial_state": initial, "final_state": final,  # 事件图和可重放状态。
        "outcome": outcome, "frames": frames, "description": description,  # 结果、固定步长轨迹和自动叙事。
        "full_prompt": f"连续仙侠特效短片设计，{MODE}。创作简报：{text}。权威数值与实际分支：{description} 素材：" + "；".join(element["description"] for element in elements) + "。只按事件时间顺序表现，未触发素材保持禁用。",  # 提示词不冒充成片。
        "negative_prompt": NEGATIVE_PROMPT, "interaction_rules": rules,  # 可单独审阅与复用的规则约束。
    }
