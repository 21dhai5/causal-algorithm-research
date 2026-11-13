"""开放元素清单的VFX提示词编排；只保留作者数据，不执行模拟或模型调用。"""

import json
import math
import re


MODE = "PROMPT_ONLY"  # 输出始终是提示词和作者数据。
MAX_TEXT_CHARS = 20000  # 原始场景文本的字符上限。
MAX_ELEMENTS = 400  # 单次明确列出的元素上限，不规定正常元素数量。
MAX_INTERACTIONS = 600  # 单次明确列出的交互上限。
MAX_ATTRIBUTES = 80  # 每个元素的自定义属性上限。
MAX_STRING_CHARS = 4000  # 单个名称、属性或交互描述的字符上限。
MAX_DETAIL_CHARS = 200000  # 原文与显式清单的JSON总字符预算；超限直接拒绝。
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")  # 引用ID采用最多64字符的安全ASCII标识。
NEGATIVE_PROMPT = "不得遗漏、合并或替换已列元素及其任意属性；不得擅自增加元素或交互；不得把否定、条件、未知状态改写为已发生事实；不得由排列顺序推断因果；不得凭空补写未提供的细节；不得声称已生成图像、视频或实际效果。"  # 约束忠实编排而非特定题材。


# 验证原始字符串但不裁剪或改写内容，避免丢失条件和否定。
def _text(value, field: str, *, empty: bool = False, limit: int = MAX_STRING_CHARS) -> str:
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError(f"{field}必须是{'0' if empty else '1'}至{limit}字符的字符串。")
    # 孤立代理码位无法编码为UTF-8，不允许留到响应写出时才失败。
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise ValueError(f"{field}必须包含有效Unicode字符。") from error
    return value


# 用户提供的引用键不能包含空白、路径或任意代码片段。
def _identifier(value, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValueError(f"{field}必须以英文字母开头，仅含字母、数字、下划线或连字符，长度1至64。")
    return value


# 检查对象字段而不隐式忽略旧接口或拼错的属性。
def _fields(value, allowed: set, required: set, field: str) -> None:
    if not isinstance(value, dict) or set(value).difference(allowed) or required.difference(value):
        raise ValueError(f"{field}字段无效；必需字段：{', '.join(sorted(required))}。")


# 输出标准JSON表示，保留标量类型和所有文字，禁止非有限浮点数。
def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


# 将作者标量写成可读描述；字符串逐字保留，空值仍明确表示未填写。
def _description(value) -> str:
    if isinstance(value, str):
        return value if value else "未填写（原始字符串为空）"
    return "待明确（原始值为null）" if value is None else _json(value)


# 校验扁平的自定义属性；名称不属于任何内置分类体系。
def _attributes(value, field: str) -> dict:
    if not isinstance(value, dict) or len(value) > MAX_ATTRIBUTES:
        raise ValueError(f"{field}必须是至多{MAX_ATTRIBUTES}项的属性对象。")
    result = {}  # 新副本避免输出与调用方的可变属性对象共享。
    for key, scalar in value.items():  # 任意作者属性逐项保留，不能截取前几项。
        _text(key, f"{field}属性名")
        if type(scalar) not in (str, int, float, bool, type(None)):
            raise ValueError(f"{field}.{key}必须是JSON标量，不能是数组或嵌套对象。")
        if isinstance(scalar, str):
            _text(scalar, f"{field}.{key}", empty=True)
        if type(scalar) is float and not math.isfinite(scalar):
            raise ValueError(f"{field}.{key}必须是有限数值。")
        result[key] = scalar
    return result


# 一次扫描预留全部显式ID；自动ID避开作者后续显式使用的同名ID。
def _ids(records: list, prefix: str, field: str) -> list[str]:
    reserved = set()  # 作者指定的ID在整个清单内唯一。
    for record in records:  # 先检查容器，避免异常对象进入引用处理。
        if not isinstance(record, dict):
            raise ValueError(f"{field}每项必须是对象。")
        if "id" in record:
            identifier = _identifier(record["id"], f"{field}.id")  # 显式ID不能自动改名。
            if identifier in reserved:
                raise ValueError(f"{field}存在重复id：{identifier}。")
            reserved.add(identifier)
    result = []  # 与输入顺序一一对应，不按名称合并。
    number = 1  # 缺省ID按输入次序递增分配。
    for record in records:
        if "id" in record:
            result.append(record["id"])
            continue
        while f"{prefix}{number:03}" in reserved:
            number += 1
        identifier = f"{prefix}{number:03}"  # 自动ID同样满足安全标识规则。
        result.append(identifier)
        reserved.add(identifier)
        number += 1
    return result


# 仅验证作者给出的依赖有向图；不会依据相邻位置添加依赖。
def _dag(dependencies: dict[str, list[str]], field: str) -> None:
    pending = {key: len(parents) for key, parents in dependencies.items()}  # 每个节点尚未处理的显式依赖数。
    children = {key: [] for key in dependencies}  # 反向邻接表使验证为O(节点+边)。
    for key, parents in dependencies.items():
        for parent in parents:
            if parent not in dependencies:
                raise ValueError(f"{field}引用不存在的id：{parent}。")
            children[parent].append(key)
    ready = [key for key, count in pending.items() if count == 0]  # 无依赖节点先参与拓扑检查。
    visited = 0  # 完成检查的节点总数，仅用于检测环。
    while ready:
        key = ready.pop()  # 当前节点不会改变输入清单的输出顺序。
        visited += 1
        for child in children[key]:
            pending[child] -= 1
            if pending[child] == 0:
                ready.append(child)
    if visited != len(dependencies):
        raise ValueError(f"{field}存在循环引用。")


# 只识别作者明确书写的逐行语法；普通自然语言保留为待拆分片段。
def _structured(text: str) -> tuple[list[dict], list[dict], list[str]]:
    elements = []  # 每条结构化行产生独立元素，不使用名词白名单。
    unresolved = []  # 原文字符偏移使用Python的Unicode字符索引，end为开区间。
    quotes = []  # 与已识别元素一一对应的原始行证据。
    offset = 0  # 包含换行符的累计位置，保留CRLF等输入的真实偏移。
    for raw in text.splitlines(keepends=True):
        line = raw.rstrip("\r\n")  # 仅行终止符不属于该行语法，原文仍完整保留。
        record = None  # 没有明确语法时不得把整句冒充元素。
        if "｜" in line or "|" in line:
            parts = re.split(r"[｜|]", line)  # 属性值按首个等号拆开，后续等号原样保留。
            attributes = {}  # 单行属性不允许重复名称造成覆盖。
            for part in parts[1:]:
                key, separator, value = part.partition("=")  # 属性名的语法空白剥离；值保持原样。
                key = key.strip()
                if not separator or not key or key in attributes:
                    raise ValueError("结构化行必须采用名称｜属性=值，且属性名不能重复。")
                attributes[key] = value
            record = {"name": parts[0].strip(), "attributes": attributes}
        elif "：" in line:
            name, separator, detail = line.partition("：")  # 中文冒号形式将完整后缀作为一个明确细节。
            if name.strip() and detail.strip():
                record = {"name": name.strip(), "attributes": {"完整细节": detail}}
        if record is not None:
            elements.append(record)
            quotes.append(line)
        elif line.strip():
            unresolved.append({"text": line, "start": offset, "end": offset + len(line), "reason": "普通叙述尚未由作者拆成具体元素及属性；未进行通用语义抽取。"})
        offset += len(raw)
    return elements, unresolved, quotes


# 逐元素编排完整数据；相同名称可用不同ID表达不同碎片或同名物件。
def _elements(records: list, quotes: list[str] | None) -> list[dict]:
    if not isinstance(records, list) or len(records) > MAX_ELEMENTS:
        raise ValueError(f"elements必须是至多{MAX_ELEMENTS}项的数组。")
    identifiers = _ids(records, "e", "elements")  # 显式和自动身份均在本次输出内稳定。
    result = []  # 输出元素数始终等于输入明确元素数。
    for index, record in enumerate(records):
        _fields(record, {"id", "name", "parent_id", "attributes"}, {"name"}, "elements")
        name = _text(record["name"], "elements.name")  # 不通过名称推断材质、角色或类别。
        parent = record.get("parent_id")  # null表示未指定父元素，不自动推断层级。
        if parent is not None:
            _identifier(parent, "elements.parent_id")
        attributes = _attributes(record.get("attributes", {}), "elements.attributes")  # 所有属性包含空值和否定均保留。
        source = {"basis": "explicit_inventory" if quotes is None else "explicit_text", "quote": "" if quotes is None else quotes[index]}  # 用户编辑清单不冒用原文引文。
        identifier = identifiers[index]  # 显式ID不因同名元素而合并。
        details = "；".join(f"{key}：{_description(value)}" for key, value in attributes.items())  # 每项属性均成为可读短句，不抽取或概括子集。
        prompt = (f"【{identifier} · {name}】所属：{parent if parent is not None else '独立元素'}。"
                  f"{details if details else '具体属性待明确'}。单独保留这一细节及其归属，未描述的部分不补写为事实。")  # 描述与原始数据分别保留，避免把JSON对象当作整段画面文案。
        result.append({"id": identifier, "name": name, "parent_id": parent, "attributes": attributes, "source": source, "prompt": prompt})
    _dag({item["id"]: [item["parent_id"]] if item["parent_id"] is not None else [] for item in result}, "elements.parent_id")
    return result


# 原样保留交互谓词及三个描述时点；不判断是否接触或发生任何结果。
def _interactions(records, elements: list[dict]) -> list[dict]:
    if not isinstance(records, list) or len(records) > MAX_INTERACTIONS:
        raise ValueError(f"interactions必须是至多{MAX_INTERACTIONS}项的数组。")
    identifiers = _ids(records, "i", "interactions")  # 交互ID独立于元素ID命名空间。
    names = {item["id"]: item["name"] for item in elements}  # 提示词同时给出端点ID和具体名称。
    result = []  # 只包含作者明确列出的交互，不添加默认事件。
    for index, record in enumerate(records):
        _fields(record, {"id", "source_id", "target_id", "trigger", "response", "before", "during", "after", "depends_on"}, {"source_id", "target_id", "trigger", "response"}, "interactions")
        source_id = _identifier(record["source_id"], "interactions.source_id")  # 作用发出端必须来自当前元素清单。
        target_id = _identifier(record["target_id"], "interactions.target_id")  # 作用接收端必须来自当前元素清单。
        if source_id not in names or target_id not in names:
            raise ValueError("interactions的source_id和target_id必须引用当前元素。")
        descriptions = {key: _text(record.get(key, ""), f"interactions.{key}", empty=key not in ("trigger", "response")) for key in ("trigger", "response", "before", "during", "after")}  # 没有给出的时点保持空字符串。
        parents = record.get("depends_on", [])  # 只有显式依赖进入DAG。
        if not isinstance(parents, list) or len(parents) > MAX_INTERACTIONS:
            raise ValueError("interactions.depends_on必须是有界ID数组。")
        for parent in parents:
            _identifier(parent, "interactions.depends_on")
        if len(set(parents)) != len(parents):
            raise ValueError("interactions.depends_on不能重复引用。")
        identifier = identifiers[index]  # 交互保持作者顺序，依赖不重写语义。
        prompt = (f"【交互 {identifier}】{names[source_id]}（{source_id}）作用于{names[target_id]}（{target_id}）。"
                  f"触发条件：{descriptions['trigger']}；可见响应：{descriptions['response']}。"
                  f"发生前：{descriptions['before'] or '未指定'}；发生中：{descriptions['during'] or '未指定'}；发生后：{descriptions['after'] or '未指定'}。"
                  f"仅依赖明确列出的交互：{'、'.join(parents) if parents else '无'}。响应始终受原条件限定，否定及未知状态不能改写为已经发生。")  # 地点、方向与传播信息由作者描述提供。
        result.append({"id": identifier, "source_id": source_id, "target_id": target_id, **descriptions, "depends_on": parents.copy(), "source": {"basis": "explicit_inventory", "quote": ""}, "prompt": prompt})
    _dag({item["id"]: item["depends_on"] for item in result}, "interactions.depends_on")
    return result


# 示例各行都是作者明确写出的单个物件或局部细节；无固定题材和数量约束。
_DEMO = [
    ("青色外袍", None, {"材质": "薄绢", "位置": "画面左侧，仅展示衣物局部"}),
    ("衣领内折", "e001", {"折线": "沿左领口内翻", "暗部": "窄条冷灰"}),
    ("袖口上层褶", "e001", {"走势": "从腕口向右下展开", "厚度": "薄绢双层"}),
    ("袖口下层褶", "e001", {"前后遮挡": "被上层褶遮去上沿", "局部投影": "接缝下方窄影"}),
    ("衣摆左侧尖角", "e001", {"形状": "细长三角", "边缘透光": "浅青"}),
    ("衣摆刺绣断针", "e001", {"位置": "左侧尖角内侧", "细节": "一小段银线中断"}),
    ("银色长刃", None, {"材质": "磨光钢", "姿态": "从画面左下斜指右上"}),
    ("刀口微缺口", "e007", {"形状": "不规则小月牙", "位置": "刃尖下方一小段"}),
    ("刃面斜向擦痕", "e007", {"微裂纹方向": "由左下向右上", "表面": "仅擦痕，不解释成断裂"}),
    ("刃脊细蚀刻", "e007", {"纹路": "连续细弧", "明暗": "凹处深灰、边沿银亮"}),
    ("护手铜绿斑", "e007", {"位置": "护手内凹面", "颗粒": "不均匀青绿点"}),
    ("握柄编绳纤维", "e007", {"颜色": "深褐", "细节": "一根毛边突出交叉结"}),
    ("刃缘白色光芯", "e007", {"形态": "极细不连续亮线", "位置": "沿朝上的刃口"}),
    ("光芯外青色薄层", "e013", {"透明度": "半透明", "前后遮挡": "局部覆盖刃口反射"}),
    ("薄层外侧单粒光点", "e014", {"位置": "薄层左侧外缘，仅此一粒", "条件": "仅为作者指定静态细节"}),
    ("金色弧形薄片", None, {"材质": "半透明金色薄片", "位置": "画面右上，不定义用途"}),
    ("薄片左缘折射层", "e016", {"折射层": "向内偏移一条淡金边", "厚薄": "上薄下厚"}),
    ("薄片内侧细波纹", "e016", {"方向": "沿内弧平行排列", "状态": "是否扩散尚未确定"}),
    ("薄片顶部缺口", "e016", {"形状": "短小不闭合弧", "边缘": "较暗且无发光补齐"}),
    ("薄片下沿反射", "e016", {"颜色": "冷青", "来源描述": "对应左侧青色薄层，强度待明确"}),
    ("衣肩冷色轮廓光", "e001", {"范围": "仅沿左肩外缘", "宽度": "窄且断续"}),
    ("刃尖局部高光", "e007", {"位置": "尖端朝上面", "形态": "短线而非光球"}),
    ("护手下方接触影", "e007", {"局部投影": "落在握柄上缘", "软硬": "近处清晰、边缘微软"}),
    ("薄片前侧漂尘", "e016", {"前后遮挡": "位于薄片前，遮住小段下缘", "颗粒": "不透明浅灰"}),
    ("薄片后侧漂尘", "e016", {"前后遮挡": "位于薄片后，由片面透视可见", "颗粒": "低对比暖灰"}),
    ("前景扁石", None, {"位置": "画面右下", "材质": "湿润深灰石"}),
    ("扁石白色断面", "e026", {"位置": "向左的切面", "细节": "粗糙白色矿粒"}),
    ("扁石细缝水痕", "e026", {"方向": "沿顶面细缝向下", "折射层": "透明窄水膜"}),
    ("后景棱角石", None, {"位置": "扁石之后偏左", "前后遮挡": "下半部被扁石遮住"}),
    ("后景石局部投影", "e029", {"局部投影": "向画面右后延伸", "边缘": "随距离渐软"}),
    ("前景单粒尘点", None, {"位置": "画面下缘略左", "清晰度": "略虚且保持独立"}),
    ("中景细尘丝", None, {"形态": "斜向纤细一缕", "前后遮挡": "经过长刃后方"}),
    ("远景薄雾", None, {"颜色": "低饱和灰蓝", "浓度": "左浅右浓"}),
    ("雾中透光缺隙", "e033", {"形状": "不规则窄缝", "可见内容": "深灰远景底色，无新增物件"}),
    ("雾层下缘淡带", "e033", {"走势": "近水平且右侧中断", "透明度": "保留后方底色"}),
    ("左下地面湿纹", None, {"材质": "石面薄水", "反射": "只见低亮度青色碎影"}),
    ("湿纹中的暗砂粒", "e036", {"位置": "细水纹中央", "前后遮挡": "水膜覆盖一半砂粒"}),
    ("地面一片纸灰", None, {"形态": "卷边薄片", "状态": "静置，未声明燃烧"}),
]
# 示例关系不求解任何条件；每个条件和阶段仍是作者文字。
DEFAULT_INTERACTIONS = [
    {"id": "i001", "source_id": "e014", "target_id": "e016", "trigger": "如果青色薄层靠近金色薄片；是否接触未知", "response": "仅在作者确认接触时，才描述接触处的局部色彩对应", "before": "二者仍有间隙，不出现接触反馈", "during": "接触点若成立，位置在薄片左下沿，传播方向沿内弧向上", "after": "未确认接触则保持未确认，不追加结果", "depends_on": []},
    {"id": "i002", "source_id": "e016", "target_id": "e025", "trigger": "仅当作者指定薄片透过背景光时", "response": "后侧漂尘通过薄片显示的色调与折射层一致", "before": "后侧漂尘身份保持独立", "during": "遮挡和透视关系遵从同一前后位置", "after": "不把色调对应解释为新的物理结果", "depends_on": []},
]
# 默认清单是可清空的示例创作数据，附属名称同时写入原文供人核对。
DEFAULT_ELEMENTS = [
    {"id": f"e{index:03}", "name": name, "parent_id": parent, "attributes": {**attributes, **({"附属对象": _DEMO[int(parent[1:]) - 1][0]} if parent else {})}}
    for index, (name, parent, attributes) in enumerate(_DEMO, 1)
]
# 文本单独调用时也只解析这些显式行，不暗中载入默认清单或交互。
DEFAULT_TEXT = "\n".join(item["name"] + "｜" + "｜".join(f"{key}={value}" for key, value in item["attributes"].items()) for item in DEFAULT_ELEMENTS)


# 生成开放清单的完整提示词；本函数不访问网络、文件或图像生成器。
def generate_prompt(text: str = DEFAULT_TEXT, *, elements=None, interactions=None) -> dict:
    _text(text, "text", empty=True, limit=MAX_TEXT_CHARS)
    warnings = []  # 明确报告未解决的粒度与清单完整性，避免假装穷尽抽取。
    unresolved = []  # 显式清单模式原文仅作上下文，不重复生成语义元素。
    quotes = None  # None区分作者清单与逐行结构化文本证据。
    if elements is None:
        elements, unresolved, quotes = _structured(text)
        extraction_status = "needs_element_details" if unresolved or not elements else "structured_text"  # 混合文本也必须暴露待拆分部分。
        if extraction_status == "needs_element_details":
            warnings.append("尚有原文未拆成具体元素，或未提供任何元素；标准库编排器不能保证自然语言的完整语义抽取，请逐项补充。")
    else:
        extraction_status = "explicit_inventory"  # 即使空数组也是作者权威清单，不能偷偷回退到默认示例。
        warnings.append("以作者显式元素清单为准；完整性取决于清单，原文仅保留为上下文，不自动补入遗漏元素。")
        if elements == []:
            warnings.append("显式元素清单为空；没有编造元素，请根据原始上下文补充具体细节。")
    # 序列化预算同时覆盖所有输入字段，超限必须报错而不是截断。
    try:
        detail_size = len(_json({"text": text, "elements": elements, "interactions": interactions}))  # 包含属性名和标量文本的总预算。
    except (TypeError, OverflowError, RecursionError) as error:
        raise ValueError("输入必须由标准有限JSON数据组成。") from error
    if detail_size > MAX_DETAIL_CHARS:
        raise ValueError(f"原文与清单的JSON总字符数不能超过{MAX_DETAIL_CHARS}。")
    output_elements = _elements(elements, quotes)  # 不论数量多少，全部元素与属性逐项输出。
    output_interactions = _interactions([] if interactions is None else interactions, output_elements)  # 缺省交互始终为空。
    sections = [  # 原文和作者字符串是待描述数据，不作为编排器的执行指令。
        "画面特效提示词：逐项表现以下明确写出的局部细节，分别保持各自的身份、属性与条件。",
        f"创作原文（完整保留）：\n{text}",
        "具体元素清单：",
        *(item["prompt"] for item in output_elements),
        "显式交互清单：",
        *(item["prompt"] for item in output_interactions),
        "一致性约束：同一ID的名称、父子归属及所有自定义属性同时成立；不同ID即使同名也分别保留。跨元素的遮挡、位置、材质、光照及作者给出的其他属性须相互对应；信息缺失或冲突时标记待明确，不擅自裁决。交互仅沿显式端点和依赖描述，位置、方向与传播路径以作者文字为准；不得把先后排列变成因果或把条件响应变成已经发生的事实。",
    ]
    if unresolved:
        sections.append("待拆分原文片段（并未识别为具体元素）：" + _json(unresolved))
    if warnings:
        sections.append("待明确说明：" + " ".join(warnings))
    return {
        "schema_version": "vfx-prompt-v2", "mode": MODE, "input_text": text,  # 协议版本、提示词模式与原始上下文。
        "extraction_status": extraction_status, "elements": output_elements, "interactions": output_interactions,  # 清单粒度与显式交互。
        "unresolved_fragments": unresolved, "warnings": warnings,  # 未解决原文和作者需要补充的说明。
        "full_prompt": "\n".join(sections), "negative_prompt": NEGATIVE_PROMPT,  # 可直接复制的正文与忠实性约束。
    }
