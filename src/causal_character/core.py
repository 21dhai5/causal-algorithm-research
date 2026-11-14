"""人物多视图提示词的显式因果设计；只编排文本，不调用模型或进行三维重建。"""

import hashlib
import json
import math
import re


MODE = "RULE_BASED_CAUSAL_DESIGN"  # 规则设计模式，不宣称从数据识别因果效应。
SCHEMA_VERSION = "character-multiview-v1"  # 网页、命令行与调用方共用的输出版本。
DEFAULT_DESCRIPTION = (  # 单个成年角色及四个明确归属身体表面的非对称标记。
    "一位成年旅行者，黑色齐肩直发，平静表情，穿灰绿色长袖外套、深灰长裤和黑色短靴。"
    "外套正面胸口有一枚圆形铜色徽章，背面有白色山形刺绣，人物自身左袖外侧有蓝色方形布贴，"
    "人物自身右腰侧挂棕色小包。保持同一套服饰、发型和自然站姿。"
)
DEFAULT_STYLE = "克制的写实角色设定图，干净浅灰背景，柔和均匀光照，材质清晰，避免夸张透视。"  # 默认表达风格。
DEFAULT_VIEWS = ("front", "right", "back", "left")  # 默认四个正交方位，按此顺序输出。
DEFAULT_FEATURES = (  # 作者显式指定的身份地标；左右均为人物解剖学方向。
    {"id": "chest_badge", "label": "正面胸口的圆形铜色徽章", "surface": "front"},
    {"id": "back_embroidery", "label": "外套背面的白色山形刺绣", "surface": "back"},
    {"id": "left_patch", "label": "人物自身左袖外侧的蓝色方形布贴", "surface": "left"},
    {"id": "right_pouch", "label": "人物自身右腰侧的棕色小包", "surface": "right"},
)
AVAILABLE_VIEWS = (  # 方位角从人物正面朝人物自身右侧递增，单位为度。
    {"id": "front", "label": "正面", "azimuth_deg": 0},
    {"id": "front_right", "label": "人物右前方四分之三视图", "azimuth_deg": 45},
    {"id": "right", "label": "人物右侧面", "azimuth_deg": 90},
    {"id": "back_right", "label": "人物右后方四分之三视图", "azimuth_deg": 135},
    {"id": "back", "label": "背面", "azimuth_deg": 180},
    {"id": "back_left", "label": "人物左后方四分之三视图", "azimuth_deg": 225},
    {"id": "left", "label": "人物左侧面", "azimuth_deg": 270},
    {"id": "front_left", "label": "人物左前方四分之三视图", "azimuth_deg": 315},
)
AVAILABLE_SURFACES = (  # 表面标注是几何可见性规则的输入，而非对自由原文的解析结果。
    {"id": "front", "label": "人物正面"},
    {"id": "back", "label": "人物背面"},
    {"id": "left", "label": "人物自身左侧"},
    {"id": "right", "label": "人物自身右侧"},
    {"id": "all", "label": "全周共同特征"},
)
SURFACE_AZIMUTH = {"front": 0, "right": 90, "back": 180, "left": 270}  # 表面朝外法线的方位角，单位为度。
SURFACE_LABELS = {surface["id"]: surface["label"] for surface in AVAILABLE_SURFACES}  # 身体表面的中文名称。
VIEW_BY_ID = {view["id"]: view for view in AVAILABLE_VIEWS}  # 固定视角的常数时间查找表。
CAMERA_TEXT = {  # 每个视角独立描述相机与画面方向，避免将身体左右当成画面左右。
    "front": "相机位于人物正前方；人物自身右侧在画面左边，人物自身左侧在画面右边。",
    "front_right": "相机位于人物自身右前方，同时看到正面与自身右侧；正面朝向画面右边，自身右侧朝向画面左边。",
    "right": "相机位于人物自身正右侧；人物面朝画面右边，背部朝画面左边。",
    "back_right": "相机位于人物自身右后方，同时看到背面与自身右侧；背面朝向画面左边，自身右侧朝向画面右边。",
    "back": "相机位于人物正后方；人物自身左侧在画面左边，人物自身右侧在画面右边。",
    "back_left": "相机位于人物自身左后方，同时看到背面与自身左侧；背面朝向画面右边，自身左侧朝向画面左边。",
    "left": "相机位于人物自身正左侧；人物面朝画面左边，背部朝画面右边。",
    "front_left": "相机位于人物自身左前方，同时看到正面与自身左侧；正面朝向画面左边，自身左侧朝向画面右边。",
}
CONSISTENCY_RULES = (  # 同一身份在相机干预下保持不变的作者约束。
    "所有视图是同一个人物；相机方位变化不得改写身份原文、发型、服饰、比例及地标归属。",
    "左与右始终指人物自身的解剖学左右；相机环绕人物，不做镜像翻转，不交换左右地标。",
    "结构化地标的表面归属是可见性计算依据；自由原文逐字保留，不自动解析或消解冲突，作者须核对两者是否一致。",
    "背向表面的地标仍属于同一身份，但不得透过身体绘出，也不得移动到当前可见表面。",
    "掠射边界地标只允许在真实边缘有依据时局部露出，不能据此推定完整可见；全周特征仍须遵守真实遮挡。",
    "保持直立自然站姿、双臂稍离躯干、全身入画、水平相机、相同取景尺度与均匀光照；只改变相机方位。",
    "各单视图提示词均可独立使用；规则仅约束提示词文本，不保证图像模型的人物一致性，也不构成完整三维重建。",
)
BASE_NEGATIVE = (  # 各视角共享的禁止项，防止身份漂移与穿透绘制。
    "不同人物，身份漂移，服饰或发型改变，左右镜像，交换人物自身左右，新增或复制地标，"
    "把背向地标移到可见面，透过身体绘制隐藏地标，掠射地标完整平铺，身体透明，"
    "额外人物，多余肢体，姿态变化，极端透视，裁切身体，文字水印"
)


class CharacterPromptError(ValueError):
    """以可直接展示的中文消息报告输入不符合字符、类型或结构约束。"""


# 检查有限长度的原文；返回原始字符串，不修剪、改写或推断其语义。
def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CharacterPromptError(f"{field}必须是非空字符串。")
    if len(value) > limit:
        raise CharacterPromptError(f"{field}不能超过{limit}字符。")
    try:
        value.encode("utf-8")  # 拒绝不能作为UTF-8输出的孤立代理字符。
    except UnicodeEncodeError:
        raise CharacterPromptError(f"{field}必须是有效的Unicode文本。") from None
    return value


# 校验并复制地标；按稳定ID排序，输入排列不改变规范身份或散列。
def _features(features: object) -> list[dict]:
    if not isinstance(features, list) or len(features) > 40:
        raise CharacterPromptError("features必须是最多40项的数组。")
    canonical = []  # 返回给本次调用的地标副本，不修改调用方持有的数据。
    seen = set()  # 本次身份内已使用的地标ID。
    for feature in features:  # 每项仅允许ID、标签和表面归属三个字段。
        if not isinstance(feature, dict) or set(feature) != {"id", "label", "surface"}:
            raise CharacterPromptError("每个地标必须且只能包含id、label、surface。")
        identifier = feature["id"]  # 使用ASCII安全字符的稳定地标ID，最多64字符。
        if not isinstance(identifier, str) or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) is None:
            raise CharacterPromptError("地标id须为1至64个英文字母、数字、下划线或连字符。")
        if identifier in seen:
            raise CharacterPromptError("地标id不能重复。")
        label = _text(feature["label"], "地标label", 300)  # 逐字保留作者地标名称。
        surface = feature["surface"]  # 只允许五种已定义的身体表面。
        if not isinstance(surface, str) or surface not in SURFACE_LABELS:
            raise CharacterPromptError("地标surface只支持front、back、left、right、all。")
        seen.add(identifier)
        canonical.append({"id": identifier, "label": label, "surface": surface})
    return sorted(canonical, key=lambda feature: feature["id"])


# 为CLI和HTTP共同拒绝重复JSON字段，避免不同解析器采用不同值。
def _unique_fields(pairs: list) -> dict:
    fields = {}  # 仅持有当前JSON对象的唯一字段。
    for name, value in pairs:  # 解码器依原始顺序交付的字段名称和值。
        if name in fields:
            raise CharacterPromptError("JSON字段不能重复。")
        fields[name] = value
    return fields


# 标准JSON不允许NaN或Infinity，明确拒绝而非转换为字符串。
def _invalid_constant(value: str) -> None:
    raise CharacterPromptError("JSON不能包含NaN或Infinity。")


# 数字指数溢出也必须拒绝，不能让标准数字文本变成非有限Python浮点数。
def _finite_float(value: str) -> float:
    number = float(value)  # JSON数字解码结果，只允许有限值。
    if not math.isfinite(number):
        raise CharacterPromptError("JSON数字必须是有限值。")
    return number


# 只解码标准UTF-8 JSON；解析错误统一为中文且不包含作者数据或文件位置。
def strict_json_loads(raw: bytes) -> object:
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields, parse_constant=_invalid_constant, parse_float=_finite_float)
    except CharacterPromptError:
        raise
    except (ValueError, UnicodeError, OverflowError, RecursionError):
        raise CharacterPromptError("内容必须是有效的UTF-8标准JSON。") from None


# 按相机与表面法线夹角的余弦划分朝向；边界不伪装为确定可见或确定隐藏。
def _visibility(features: list[dict], azimuth: int) -> tuple[list, list, list]:
    visible = []  # 朝向相机的地标，仍受真实物体局部遮挡影响。
    hidden = []  # 背向相机的地标，不得透体绘出。
    grazing = []  # 法线点积近零的轮廓边界地标。
    for feature in features:  # 规范身份中的每个地标恰好进入一个集合。
        if feature["surface"] == "all":
            visible.append(dict(feature))
            continue
        facing = math.cos(math.radians(azimuth - SURFACE_AZIMUTH[feature["surface"]]))  # 单位法线与观察方向的点积。
        if facing > 1e-9:
            visible.append(dict(feature))
        elif facing < -1e-9:
            hidden.append(dict(feature))
        else:
            grazing.append(dict(feature))
    return visible, hidden, grazing


# 将地标归属连同原始标签写入提示词；空清单也明确表达其状态。
def _landmarks(features: list[dict]) -> str:
    return "；".join(f"[{feature['id']}] {feature['label']}（{SURFACE_LABELS[feature['surface']]}）" for feature in features) or "无"


# 返回全新默认数据，网页编辑或调用方修改不会污染后续生成。
def get_defaults() -> dict:
    return {
        "description": DEFAULT_DESCRIPTION,
        "style": DEFAULT_STYLE,
        "views": list(DEFAULT_VIEWS),
        "features": [dict(feature) for feature in DEFAULT_FEATURES],
        "available_views": [dict(view) for view in AVAILABLE_VIEWS],
        "available_surfaces": [dict(surface) for surface in AVAILABLE_SURFACES],
    }


# 用显式有向依赖解释相机干预；只表示规则关系，不表示统计识别或已生成图像。
def _causal_graph() -> dict:
    return {
        "nodes": [
            {"id": "identity", "label": "固定身份原文与规范地标"},
            {"id": "camera", "label": "相机方位干预"},
            {"id": "surface", "label": "地标表面法线"},
            {"id": "facing", "label": "相机方向与法线点积"},
            {"id": "visibility", "label": "朝向、隐藏或掠射边界"},
            {"id": "style", "label": "表达风格"},
            {"id": "prompt", "label": "单视图文本提示词"},
        ],
        "edges": [
            {"source": "identity", "target": "surface", "label": "固定地标归属"},
            {"source": "camera", "target": "facing", "label": "改变观察方向"},
            {"source": "surface", "target": "facing", "label": "提供表面法线"},
            {"source": "facing", "target": "visibility", "label": "按点积符号分类"},
            {"source": "identity", "target": "prompt", "label": "保留同一身份"},
            {"source": "camera", "target": "prompt", "label": "明确相机与画面方向"},
            {"source": "visibility", "target": "prompt", "label": "约束地标呈现及遮挡"},
            {"source": "style", "target": "prompt", "label": "约束表达风格"},
        ],
    }


# 生成独立且确定的多视图文本；None在Python接口表示采用默认清单，错误输入抛出中文异常。
def generate_multiview_prompt(
    description: str = DEFAULT_DESCRIPTION,
    *,
    style: str = DEFAULT_STYLE,
    views: list[str] | None = None,
    features: list[dict] | None = None,
) -> dict:
    description = _text(description, "description", 6000)
    style = _text(style, "style", 1000)
    selected = list(DEFAULT_VIEWS) if views is None else views  # 保留调用方选定的视图排列。
    if not isinstance(selected, list) or not 1 <= len(selected) <= 8:
        raise CharacterPromptError("views必须是包含1至8项的非空数组。")
    if any(not isinstance(view, str) or view not in VIEW_BY_ID for view in selected):
        raise CharacterPromptError("views含不支持的视图ID。")
    if len(set(selected)) != len(selected):
        raise CharacterPromptError("views中的视图ID不能重复。")
    # 示例地标只配套示例人物；自定义原文未提供地标时不擅自添加外貌或配饰。
    if features is None:
        features = [dict(feature) for feature in DEFAULT_FEATURES] if description == DEFAULT_DESCRIPTION else []
    canonical = _features(features)  # 规范身份与朝向无关，显式空清单也保持为空。
    identity = {"description": description, "features": canonical}  # 身份仅由原文和结构化地标决定。
    identity_bytes = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")  # 稳定序列化，不含视角或风格。
    character_id = "character-" + hashlib.sha256(identity_bytes).hexdigest()[:24]  # 可复核的身份文本指纹，不是图像一致性保证。
    results = []  # 每个视图只依赖固定身份、风格与自己的相机方位。
    for identifier in selected:  # 请求顺序只影响结果排列，不影响单个视图文本。
        view = VIEW_BY_ID[identifier]  # 当前固定相机定义。
        visible, hidden, grazing = _visibility(canonical, view["azimuth_deg"])  # 几何朝向三分区。
        negative = BASE_NEGATIVE  # 当前视图的负向约束由共有禁止项及背向地标组成。
        if hidden:
            negative += "；禁止在当前视图透体绘出或移位呈现：" + _landmarks(hidden)
        if grazing:
            negative += "；禁止把以下边界地标完整铺向相机：" + _landmarks(grazing)
        prompt = "\n".join((  # 单视图包含完整身份记忆、相机、风格、可见性和负向要求，可单独复制。
            f"人物多视图角色设定｜{view['label']}｜身份指纹：{character_id}",
            "【固定身份原文，逐字保留】\n" + description,
            "【完整身份地标记忆；清单出现不代表本视图必须绘出】\n" + _landmarks(canonical),
            "【表达风格，逐字保留】\n" + style,
            f"【相机干预】方位角{view['azimuth_deg']}°，0°为正面、90°为人物自身右侧。" + CAMERA_TEXT[identifier],
            "【朝向相机的地标】\n" + _landmarks(visible) + "。仅在相应表面按真实遮挡呈现，不复制到其他位置。",
            "【背向相机的地标】\n" + _landmarks(hidden) + "。保留其身份归属，但不得透过身体绘出或移到当前可见面。",
            "【掠射边界地标】\n" + _landmarks(grazing) + "。只能在真实轮廓允许时局部露出，不推定完整可见。",
            "【一致性规则】\n" + "\n".join(CONSISTENCY_RULES),
            "【负向提示词】\n" + negative,
        ))
        results.append({
            **view,
            "visible_features": visible,
            "hidden_features": hidden,
            "grazing_features": grazing,
            "prompt": prompt,
            "negative_prompt": negative,
        })
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": MODE,
        "character_id": character_id,
        "identity": identity,
        "style": style,
        "views": results,
        "causal_graph": _causal_graph(),
        "consistency_rules": list(CONSISTENCY_RULES),
        "warnings": [
            "本工具是确定性的显式因果设计提示词编排器，不是学习得到的因果推断，也不生成图像。",
            "自由原文与标签均按原样保留；地标表面由作者指定，工具不理解任意文本，语义冲突须由作者检查。",
            "可见性采用四个主表面法线的朝向近似；没有三维体积、姿势或深度求解，不能保证真实遮挡与图像身份一致。",
        ],
        "full_prompt": "人物多视图统一设定\n所选视图：" + "、".join(VIEW_BY_ID[view]["label"] for view in selected)
        + "\n统一规则：\n" + "\n".join(CONSISTENCY_RULES)
        + "\n\n" + "\n\n".join(view["prompt"] for view in results),
        "negative_prompt": BASE_NEGATIVE,
    }
