"""显式原文、未知属性与有限绘画假设分开；不执行学习或因果效应推断。"""

from itertools import product
import re
from secrets import SystemRandom


MAX_PROMPT_CHARS = 4000  # 输入按 Unicode 字符计数，HTTP 另设字节上限。
MAX_VARIANTS = 648  # 四组面部设计与其余有限选项的最大组合数，保证穷举终止。
_DOMAINS = {  # 词汇只用于锁定相关属性，不把否定或未知描述改写成肯定事实。
    "face": r"脸型|面型|脸形|圆脸|方脸|长脸|鹅蛋脸|瓜子脸|下颌|颧骨|无脸|face|jaw|cheekbone",
    "eyes": r"眼|瞳|盲|eye|iris|pupil",
    "nose": r"鼻|nose|nostril",
    "mouth": r"嘴|唇|牙|口型|mouth|lip|teeth|tooth",
    "hair": r"发|髮|秃|辫|马尾|hair|bald|ponytail|braid",
    "expression": r"表情|神情|笑|哭|怒|悲|冷漠|严肃|情绪|闭眼|睁眼|眼神|嘴|唇|牙|expression|smil|laugh|cry|sad|angry|neutral|serious|closed eyes|open eyes|mouth|lip|teeth",
    "pose": r"姿|正面|侧面|侧脸|侧颜|转头|回头|低头|抬头|俯|仰|视角|角度|看向|朝向|凝视|背影|front|profile|pose|angle|looking|gaze|view|tilt|turned",
    "light": r"光|照明|阴影|亮|暗|曝光|light|shadow|illuminat|exposure|dark|bright",
    "background": r"背景|环境|场景|室内|室外|街|墙|海|山|森林|公园|background|setting|outdoor|indoor|studio|wall|street|forest|park",
}
_KNOWN_WORDS = (  # 仅完整覆盖这组有限词法时，才允许补充未锁定的外观；其余输入保守透传。
    r"face shape|oval face|round face|closed eyes|open eyes|long hair|short hair|black hair|brown hair|"
    r"left light|right light|front light|front view|left profile|right profile|"
    r"portrait|person|female|woman|women|male|man|men|girl|boy|young|adult|asian|"
    r"chinese|face|eyes|eye|nose|mouth|lips|hair|smile|neutral|realistic|natural|"
    r"black|brown|blue|green|red|white|long|short|round|oval|small|large|big|straight|"
    r"soft|hard|light|shadow|left|right|front|profile|background|plain|gray|grey|"
    r"with|without|not|no|and|a|an|the|of|from|only|"
    r"不要|不能|不得|没有|并非|不是|无需|避免|禁止|不|无|非|未|没|别|"
    r"一个|一位|一名|一张|人物|人像|肖像|人脸|头像|面部|脸部|女性|男性|女人|男人|女孩|男孩|少女|少年|女生|男生|"
    r"年轻|青年|成年|中年|老年|老人|儿童|亚洲人|中国人|东方人|漂亮|美丽|英俊|好看|自然|普通|写实|真实|摄影|插画|绘画|卡通|动漫|风格|"
    r"鹅蛋脸|瓜子脸|圆脸|方脸|长脸|脸型|面型|下颌|颧骨|大眼睛|小眼睛|杏眼|圆眼|丹凤眼|眼睛|眼型|瞳孔|双眼皮|单眼皮|"
    r"高鼻梁|低鼻梁|小鼻子|鼻梁|鼻子|厚唇|薄唇|嘴唇|嘴巴|牙齿|"
    r"黑色|深棕色|棕色|金色|白色|灰色|蓝色|绿色|红色|肤色|白皙|深肤色|浅肤色|"
    r"长发|短发|中长发|齐肩发|卷发|直发|黑发|金发|头发|刘海|秃头|光头|辫子|马尾|"
    r"微笑|大笑|笑容|平静|严肃|冷漠|哭泣|愤怒|表情|神情|闭眼|睁眼|闭嘴|张嘴|露齿|"
    r"正面|左侧面|右侧面|侧面|侧脸|侧颜|向左转头|向右转头|转头|低头|抬头|平视|俯视|仰视|视角|角度|"
    r"左侧|右侧|前方|左前方|右前方|柔光|硬光|侧光|逆光|顶光|自然光|打光|光线|光照|照明|阴影|"
    r"背景|纯色|简单|中性|浅灰|深灰|米白|室内|室外|摄影棚|"
    r"请|帮我|生成|画|绘制|描述|需要|想要|使用|采用|保持|带有|以及|和|与|的|地|得|是|为|有|从|在|以|用"
)
_NEGATION = re.compile(r"不要|不能|不得|没有|并非|不是|无需|避免|禁止|不|无|非|未|没|别|\b(?:no|not|without|avoid|never)\b", re.I)  # 否定分句不用于推导肯定光线或姿态。
_FACIAL_DESIGNS = (  # 每项是一组几何外观；锁定属性逐项剔除，不改动用户身份、年龄、族裔和肤色。
    {"face": "脸型偏椭圆，下颌轮廓柔和", "eyes": "眼型偏杏眼，眼裂比例适中", "nose": "鼻梁轮廓平缓，鼻尖圆润", "mouth": "唇形自然，上下唇厚度接近"},
    {"face": "脸型偏圆，面颊轮廓柔和", "eyes": "眼型偏圆，眼尾弧度柔和", "nose": "鼻部小巧，鼻翼轮廓收敛", "mouth": "唇形小巧，唇峰较柔和"},
    {"face": "脸型略方，下颌转折清楚", "eyes": "眼型略细长，眼尾平直", "nose": "鼻梁较直，鼻尖轮廓清楚", "mouth": "唇形饱满，唇峰清楚"},
    {"face": "脸型略长，下巴轮廓圆缓", "eyes": "眼型舒展，眼角弧度较平缓", "nose": "鼻梁宽度适中，鼻尖略窄", "mouth": "唇形较薄，唇线清楚"},
)
_CHOICES = {  # 有限呈现方案属于设计空间，不能冒充观察事实或无限生成能力。
    "hair": ("黑色短直发，发梢自然", "深棕色齐肩直发，发丝自然垂落", "黑色中长微卷发，轮廓蓬松"),
    "expression": ("神情平静，嘴唇自然闭合", "神情温和，双唇微闭且轻微微笑"),
    "pose": ("正面平视", "头部轻微转向画面左侧", "头部轻微转向画面右侧"),
    "light": ("画面左前方柔光", "画面右前方柔光", "前方均匀柔光"),
    "background": ("中性浅灰纯色背景", "低饱和米白纯色背景", "中性深灰纯色背景"),
}
_CONSERVATIVE_CHOICES = {  # 未理解原文时只变化制作侧重，不新增可能与原文冲突的五官数值。
    "focus": (
        "在原文允许且画面可见的范围内，优先刻画面部外轮廓的边缘节奏，不改变指定脸型。",
        "在原文允许且画面可见的范围内，优先刻画眼周线条的层次，不改变指定眼型与开闭状态。",
        "在原文允许且画面可见的范围内，优先刻画鼻部轮廓的衔接，不改变指定鼻型。",
        "在原文允许且画面可见的范围内，优先刻画唇部边缘的细节，不改变指定唇形与表情。",
        "在原文允许且画面可见的范围内，优先刻画头发与面部交界的层次，不添加原文未允许的头发。",
        "在原文允许且画面可见的范围内，优先刻画面颊与下颌的形体衔接，不改变年龄与指定外貌。",
    ),
    "finish": (
        "制作侧重：把原文风格允许的细节集中在视觉主体上，其余区域保持相对简洁。",
        "制作侧重：在原文风格内强调连续轮廓的清晰衔接，避免无依据的断裂。",
        "制作侧重：在原文风格内强调相邻面部区域的层次区分，服从指定光线与色彩。",
        "制作侧重：在原文风格内强调局部细节与整体比例的协调，服从指定构图。",
    ),
}


class FacePromptError(ValueError):
    """可直接展示给用户的输入或有限设计空间错误。"""


class VariationExhausted(FacePromptError):
    """当前原文的有限设计组合已全部登记，不伪造不同结果。"""


# 验证完整输入但不 strip 原文；拒绝无法保存为 UTF-8 的代理码点。
def validate_prompt(prompt: str) -> None:
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > MAX_PROMPT_CHARS:
        raise FacePromptError("提示词必须是 1 至 4000 字符的非空字符串。")
    try:
        prompt.encode("utf-8")
    except UnicodeEncodeError as error:
        raise FacePromptError("提示词包含无效的 Unicode 字符。") from error
    if "\x00" in prompt:
        raise FacePromptError("提示词不能包含空字符。")


# 用有限词法覆盖判断是否安全补齐；任何未知余文都会关闭全部外观及呈现随机补充。
def _understood(prompt: str) -> bool:
    if _NEGATION.search(prompt):
        return False  # 否定的作用域可能跨属性，整体透传比推断剩余自由度更可靠。
    remainder = re.sub(_KNOWN_WORDS, "", prompt, flags=re.I)  # 已覆盖的词汇只用于确认范围，不重写原文。
    remainder = re.sub(r"[\s，,。.!！、；;：:()（）\[\]【】\-]+", "", remainder)  # 允许不改变约束的分隔符。
    if remainder:
        return False
    # 全局限制、唯一性及数量限定存在时不自行选择剩余属性。
    return not re.search(r"只|仅|保持|不要添加|不得添加|不改变|不能改变|\bonly\b", prompt, re.I)


# 识别未被否定的简单光线或朝向；复杂或多义方向只保留原文，不推导新状态。
def _explicit_direction(prompt: str, domain: str) -> str | None:
    patterns = {  # 方向均使用画面坐标；分句中有否定时整句跳过，避免错误反转含义。
        "light": ((r"左(?:前)?(?:侧|方).*(?:光|打光)|left(?: front)? light", "left"),
                  (r"右(?:前)?(?:侧|方).*(?:光|打光)|right(?: front)? light", "right"),
                  (r"前方(?:均匀)?柔光|正面光|front light", "front")),
        "pose": ((r"正面|front view", "front"), (r"左侧面|向左转头|left profile", "left"),
                 (r"右侧面|向右转头|right profile", "right")),
    }
    found = set()  # 只在所有可识别分句方向一致时采用，不猜测冲突方向。
    for clause in re.split(r"[，,。.!！；;\n]", prompt):  # 分句用于控制否定作用范围。
        if _NEGATION.search(clause):
            continue
        for pattern, direction in patterns[domain]:  # 同句中多个方向也会触发保守退回。
            if re.search(pattern, clause, re.I):
                found.add(direction)
    return next(iter(found)) if len(found) == 1 else None


# 世界状态确定后才推导阴影及透视，推导本身明确标记为绘画假设。
def _dependencies(prompt: str, state: dict[str, str]) -> list[str]:
    effects = []  # 条件依赖只限制绘画一致性，不表示从数据学习的因果关系。
    light = state.get("light", "")  # 优先使用本轮已选择的呈现状态。
    direction = ("left" if "左" in light else "right" if "右" in light else "front" if light else _explicit_direction(prompt, "light"))  # 原文方向只采用有限肯定语法。
    if direction and not re.search(r"阴影|影子|shadow|无光|不.*光", prompt, re.I):
        if direction == "front":
            effects.append("光线与阴影一致性：亮面朝向前方光源，明暗过渡服从原文规定的光源范围与软硬程度，不额外增加单侧光源。")
        else:
            effects.append(f"光线与阴影一致性：亮面朝向画面{'左' if direction == 'left' else '右'}侧光源，背光侧保留相容的明暗过渡；柔硬程度服从原文。")
    pose = state.get("pose", "")  # 姿态与摄影机状态分开处理，不改动面部身份。
    direction = ("left" if "左" in pose else "right" if "右" in pose else "front" if pose else _explicit_direction(prompt, "pose"))  # 只推导已确定朝向对应的透视。
    if direction and not re.search(r"透视|远近|大小|perspective|foreshorten|flat|平面|立体|对称", prompt, re.I):
        if direction == "front":
            effects.append("姿态与透视一致性：五官以同一正面朝向组织，俯仰角度服从原文，不额外转成侧脸。")
        else:
            effects.append(f"姿态与透视一致性：转向画面{'左' if direction == 'left' else '右'}侧时，近远侧五官随同一转头角度产生相容的透视缩短，不把双眼强行排成正面等宽。")
    return effects


# 枚举最多 648 个设计状态；未知文本采用 24 组有条件的制作侧重。
def candidate_prompts(prompt: str) -> list[dict]:
    validate_prompt(prompt)
    locked = {name for name, pattern in _DOMAINS.items() if re.search(pattern, prompt, re.I)}  # 涉及属性即锁定，包括否定、未知修饰和显式值。
    understood = _understood(prompt)  # 只解析一次覆盖程度，未知语义不参与方向推导。
    options = [("face", ("",))]  # 第一维存储面部几何组合，不直接增添独立角色。
    if understood:
        facial = tuple(dict.fromkeys("；".join(value for name, value in design.items() if name not in locked) for design in _FACIAL_DESIGNS))  # 移除锁定属性后合并相同组合。
        options = [("face", facial)]
        options.extend((name, values if name not in locked else ("",)) for name, values in _CHOICES.items())
    else:
        options = list(_CONSERVATIVE_CHOICES.items())
    results = []  # 输出仅在内存中暂存；持久化账本只接收最终字符串的散列。
    for values in product(*(values for _, values in options)):  # 有限笛卡尔积不依赖随机重试终止。
        state = {name: value for (name, _), value in zip(options, values) if value}  # 显式原文与补充状态隔离，补充不覆盖原文。
        assumptions = [("未指定属性的绘画设计：" if understood else "可选制作建议：") + value for value in state.values()]  # 未知语义只建议条件允许的制作重点。
        assumptions.extend("条件一致性绘画假设：" + value for value in _dependencies(prompt if understood else "", state))
        if not understood:
            assumptions.insert(0, "存在否定、有限词法未覆盖或全局限定的描述；不自行添加外观、背景、光线或姿态，只变化原文允许范围内的制作侧重。若原文禁止补充，则忽略全部建议。")
        final = (  # 原文完整保留，包括首尾空格、换行和否定，不用随机编号伪造差异。
            "请生成人脸图像。以下完整用户原文具有最高优先级，包含其中的否定、数量、外观、风格、姿态及构图约束。\n"
            "【用户原文开始】\n" + prompt + "\n【用户原文结束】\n"
            "【可撤销的绘画设计假设】\n" + ("\n".join(assumptions) if assumptions else "没有增加原文之外的属性。") + "\n"
            "同一画面中的主体、光照与透视应保持一致；设计假设与原文冲突时，一律以原文为准。"
        )
        results.append({"prompt": final, "assumptions": assumptions, "mode": "rule_based_design"})
    SystemRandom().shuffle(results)  # 随机仅改变真实设计状态的尝试顺序，不进入输出文本。
    return results


# 默认进行纯内存生成；传入同一个 HistoryLedger 可跨请求保证不重复。
def generate_prompt(prompt: str, history=None) -> dict:
    from .history import HistoryLedger  # 延迟导入使无账本调用不依赖任何已有研究包。

    candidates = candidate_prompts(prompt)  # 先验证并生成有限候选，输入错误不创建持久化目录。
    if history is not None:
        return history.reserve(candidates)
    with HistoryLedger(":memory:") as ledger:  # 纯函数式调用不留下文件；唯一性范围限于显式共享账本。
        return ledger.reserve(candidates)
