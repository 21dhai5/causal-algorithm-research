# 基于因果事件建模的场景与时间片段生成 MVP

## 1. 需求理解、实现边界与默认假设

这是**文本与规则驱动的事件分镜规划器**。输入短句，输出整体场景、事件关系、时间轴、逐镜脚本和图像提示词；显式配置图像服务后，可以生成并保存逐镜 PNG。它没有训练大型模型，也没有从数据识别因果效应。

**分镜图像是若干静态关键帧，不是连续视频。** 时间轴和运动说明属于待制作脚本；本程序不插帧、不合成 MP4，不生成声音，也不能保证生成图中的物理和身份一致性。

默认总时长 6 秒、镜头数 3、统一简洁写实故事板风格。分镜完整覆盖总长，不重叠、不留空；旧版独立简单事件可以并行，新增环境器物动作必须明确顺序，镜头仍依次播放。规则解析器只覆盖明确的小范围中文语法；未知、否定、条件或存在冲突的句子明确报错，避免任意补写情节。

两份用户材料用于以下设计原则，不将其历史操作描述当作当前工程事实：

- 世界层负责人物、物体、环境、位置及状态，即“描写什么”。
- 展示层负责景别、观察位置、俯仰、摄影机运动、构图、光色、剪辑与声音元数据，即“怎样展示”。
- 摄影机运动与主体行动分开；展示设计不回写故事事件或改变因果图。
- 仅选择当前场景需要的类别，不强凑全部世界背景、感官或摄影技法。

## 2. 系统架构与核心算法

流程为 `SceneParser.parse → validate_scene → DAG 拓扑排序 → 事件时间轴 → 镜头划分 → 状态快照/提示词 → 可选 ImageProvider`。

### 解析与依赖

`SceneParser` 是可替换协议，默认 `RuleSceneParser` 使用完整句匹配及有限词法。当前支持：

- 男孩踢足球，足球滚向桌子并撞倒桌上杯子的示例句型；允许部分颜色、衣着和量词变体。
- 猫坐在窗边；男孩跑步或开始跑步。
- 上述两个独立简单主体用“然后／随后／接着”表示先后，用“同时”表示完整并行。
- 环境声明在前、单人物动作在后的元素语法：开门、关门、入室、拿起水杯或箱子、放到桌子或箱子上，以及明确平稳方式的移桌或移箱；详见[场景元素说明](scene-elements.md)。这条语法不继承旧例的衣着变体或并行支持。

“穿红衣的男孩阻止穿蓝衣的男孩跑步”等复杂输入不会被截取成一个错误的肯定事件。普通高桌、跳跃、否定和复杂混合并行不在当前规则覆盖范围，明确失败。

时间关系保存为 `before` 或 `overlaps`。因果图另存 `causes` 和 `enables`：前者表示文本或规则提出的导致关系，后者只表示使后续事件可发生的前置条件。每条关系都带 `basis`、引文和解释。`unknown` 关系仅保存在 `unresolved_causal_relations`，不会自动成为因果边。

校验实体与事件 ID、关系端点、原文证据、状态字段和前置条件；联合检查 before／因果依赖是否有环。旧版简单事件只有全部独立、无顺序和因果冲突时才接受全程同时；新增环境器物动作拒绝并行或次序未定，复杂资源冲突调度暂不支持。

### 时间与状态

事件按拓扑顺序分配故事时间。示例中踢球和滚动各用权重 2，接触和倾倒各用权重 1，所以 6 秒分为 `2+2+1+1`。这只是可配置总长下的呈现安排，不是测量的运动耗时。

镜头边界为 `duration × i / shots`，使用 Decimal 计算，首尾直接固定为 0 和总长。镜头少于事件数时合并事件；多于事件数时细分同一事件阶段，通过不变的 `occurrence_id` 避免制造重复踢球等新行动。

每个事件包含 `preconditions`、`active_state` 和 `updates`。镜头保存起止状态及单个关键帧状态。未开始的事件不写入未来结果；已经结束的事件不回到初态。“跑起来”按准备—开始—跑动建模，不能在此前镜头就变成跑动。

单张图选择一个具体时刻，不要求一张图同时画出球离脚、滚动、接触和杯倒。跨镜复用实体外观、空间条件、统一风格及状态约束。

### 环境、器物与状态传播

新语法由 `RuleSceneParser` 分流到元素解析器，先按 `environment → objects → subjects` 登记稳定身份，再由 `compile_element_scene` 编译动作。每次读取上一个动作结束的完整状态，检查前置，写入直接效果，沿位置、支撑、固定或手持链计算 `root_location` 和 `world_position`；无关元素保留原状态，最后把完整快照交给时间轴和分镜器。

例如“开门 → 入室 → 平稳移桌”：门先从 `closed` 变为 `open`，人物才从 `outside` 进入 `room`；移桌只直接改变桌子位置，桌上的杯子在明确无滑落假设下跟随，墙画仍挂在墙上。“拿起 → 放回”则将杯子支撑从 `table` 改为 `null` 再恢复，同时将手持关系从 `null` 改为 `boy` 再解除。初始关系仅适用于初态，不能强行覆盖后续拿取结果。

原文事实用 `explicit_text` 保存引文；门初态缺省、未锁、可达性、静止支撑和准静态无滑落等必要补全集中保存在 `scene.assumptions` 及状态来源中；未知位置和未建模物理影响保持 `unknown`。`world.py` 是手写规则引擎，JSON 是规则推演记录，不代表从图像或数据学到了因果知识。先后关系也不会自动变成因果边。

文本入口当前限单场景、单人物、每类器物一个身份；不支持否定、条件、多人、富世界并行或未知分句。缺少入口的“走进房间”、门关闭却直接进入、未拿起就放回等前置冲突会失败。未指定环境时只登记抽象 `space` 与已提及器物，不补造房子或门。完整输入、字段和两份离线示例见[场景元素与状态传播](scene-elements.md)。

### 图像适配

`ImageProvider.generate(prompt) -> bytes` 可替换。默认 HTTP 适配器采用下述显式 JSON/base64 PNG 约定，不绑定某个供应商品牌：

```json
{"model":"模型标识","prompt":"分镜提示词","n":1,"size":"1024x1024","output_format":"png"}
```

服务返回 `{"data":[{"b64_json":"PNG的base64"}]}`。不下载返回 URL、不跟随重定向、不自动重试。返回文件需要通过有界 PNG 像素校验；保存时移除非像素辅助元数据，保留必要透明度。只有实际保存成功才写入图片相对路径。

本协议便于对接支持该结构的模型服务或本机适配器。供应方必须自行确认模型名、字段、权限和价格；本轮官方图像文档请求受限，未将其描述为经过真实供应方验证的完整兼容实现。

## 3. 输入输出格式及字段说明

Python 入口：

```python
from causal_storyboard import build_storyboard

board = build_storyboard(
    "一个男孩踢了一下足球，足球滚向桌子并撞倒了桌上的水杯。",
    duration=6,
    shots=3,
)
```

输入 text 为 1–4000 字符；duration 为有限正数、最多 3600 秒；shots 为 1–60 的整数。时长过短导致无法分配正长度片段时拒绝。style 为可选的统一呈现风格。接口可传入其他 `SceneParser`，但解析结果仍须通过校验。

主要输出：

- `schema_version`：当前为 `1.1`；旧示例文件保留其生成时版本。
- `modeling_scope`：规则／文本建模声明。
- `overall_scene_description`：原始场景与明确列出的统一设定。
- `scene.entities`：稳定实体 ID、原文外观与证据；旧足球语法中后文明确补充的颜色会合并，元素语法暂不支持这种外观补充。
- `scene.world`：环境和几何约束；补全属性注明依据。
- `scene.initial_state`：事件前状态，键为 `entity.attribute`。
- `scene.assumptions`：集中列出的常识或空间补全。
- `scene.continuity`：展示外观及跨镜连续性约束，不冒充原文事实。
- `scene.element_model`：仅元素语法包含；记录登记顺序、三类实体 ID、初始关系、逐属性 `state_sources`、有对象范围的布尔 `action_conditions` 与 `rule_catalog`，模型内部版本为 `1.0`。
- `element_trace`：仅元素语法包含；每个事件的完整 `before`／`after`、`direct_effects`、`propagated_effects`、`unchanged_entities` 和 `unresolved_effects`。效果记录前后值、规则 ID 与证据。
- `state_dependencies`：仅元素语法包含；根据动作前置状态的最近写入者记录规则内使能边，不从时间顺序推定现实因果。
- `events`：一次事件的参与者、证据、前置、活动、结果和三个阶段的关键帧文本。
- `temporal_relations`、`causal_relations`、`unresolved_causal_relations`：分别保存先后／并行、因果／使能、未知关系。
- `timeline`：每个故事事件发生一次的起止时间。
- `shots`：镜号、起止秒、事件引用、脚本、起止状态、关键帧、展示方法、图像提示词和实际图片状态。
- `generation_kind`：`STORYBOARD_STILL_IMAGES_NOT_CONTINUOUS_VIDEO`。

证据类型：`explicit_text` 来自原文；`commonsense_assumption` 是规则或必要补全；`unknown` 表示依据不足。它们不是统计置信度。

无图像调用时是 `{"status":"not_requested","path":null}`。成功后是 `{"status":"generated","path":"s01.png"}`；调用或保存失败时是 `{"status":"failed","path":null,"error":"脱敏错误说明"}`。失败路径不假装存在。

## 4. 项目目录与各文件完整代码

所有源文件已实际写入仓库，可直接运行；[完整源码汇编](storyboard-source.md)逐文件收录未省略的代码和配置。

```text
src/causal_storyboard/
  __init__.py       # 公共规划接口
  __main__.py       # python -m 入口
  core.py           # 解析、证据、DAG、状态、时间轴与提示词
  element_parser.py # 环境先行的有限中文语法与来源登记
  world.py          # 动作前置、元素状态传播与轨迹复核
  images.py         # 图像协议、HTTP、PNG检查与安全保存
  cli.py            # 参数、离线规划、可选图像调用、JSON保存
experiments/run_storyboard.py
examples/storyboard-football/storyboard.json
examples/scene-elements-room/storyboard.json
examples/scene-elements-pick-place/storyboard.json
.env.example
pyproject.toml
docs/storyboard-mvp.md
docs/scene-elements.md
docs/storyboard-source.md
docs/storyboard-validation.md
```

离线分镜模块仅使用 Python 3.12+ 标准库。项目原有因果研究依赖 NumPy；直接运行 `experiments/run_storyboard.py` 不需要 NumPy。没有新增模型权重、图像库或外部 SDK 依赖。

## 5. 安装配置与运行方法

在项目根目录，无需安装第三方包即可离线运行：

```powershell
python -B experiments/run_storyboard.py --text "一个男孩踢了一下足球，足球滚向桌子并撞倒了桌上的水杯。"
python -B experiments/run_storyboard.py --text "一个男孩踢了一下足球，足球滚向桌子并撞倒了桌上的水杯。" --duration 6 --shots 3 --output storyboard-output
```

第二条在已有父目录中独占创建新目录。若目标已存在，返回错误而不覆盖。仓库中的正式示例已经存在，重新运行请使用其他输出目录。

环境器物示例同样默认 6 秒、3 镜头，省略 `--output` 时只输出 JSON：

```powershell
python -B experiments/run_storyboard.py --text "房间里有一扇关闭的门，墙上挂着一幅画，桌上放着一个水杯。一个男孩打开门，然后走进房间，再平稳地把桌子移到房间右侧。"
```

安装项目后也可运行 `causal-storyboard --text "一只猫坐在窗边。"`，或 `python -m causal_storyboard`。安装完整项目会安装 pyproject 中原有的 NumPy 依赖；只需离线分镜时可以使用源码入口。

实际生成图像需要三个环境变量；不自动加载 `.env`：

```powershell
$env:STORYBOARD_IMAGE_URL = "https://your-image-service.example/v1/images/generations"
$env:STORYBOARD_IMAGE_MODEL = "your-model-id"
# STORYBOARD_IMAGE_KEY 由你的运行环境或秘密管理器注入，不写入代码或 Git。
python -B experiments/run_storyboard.py --text "一个男孩踢了一下足球，足球滚向桌子并撞倒了桌上的水杯。" --output storyboard-images --generate-images
```

示例域名不是可用服务；需换成已配置且可信的模型端点。远程必须为 HTTPS，本机回环 HTTP 只用于本地适配服务。程序会向配置的服务发送分镜提示词，不应输入私人资料。环境变量齐全但不加 `--generate-images` 时也不会调用模型。

成功时保存 storyboard.json 和各镜头 PNG；部分图片失败仍保存其余结果与状态，退出码为 3。输入、参数、配置和输出目录错误返回 2；完成返回 0。单次 socket 超时最多 120 秒，不等于整个请求的墙钟上限。

本次没有配置这三个变量，**未调用真实图像模型，也没有生成示例分镜图像**。适配器测试只使用本机测试端点和临时像素文件，不把它们交付为模型生成结果。

## 6. 完整示例

输入：**一个男孩踢了一下足球，足球滚向桌子并撞倒了桌上的水杯。**

### 整体场景与最小空间补全

人物和物体仅为男孩、足球、桌子、水杯。初始时男孩准备踢球，球静止在桌前地面，杯子直立在桌面迎球侧。原文未说明颜色、衣着、房间、天气，不增加这些故事事实；使用统一中性示意外观。

普通高桌的桌上杯子不能被贴地滚动的足球直接击中。因此显式补全为：**约12厘米低桌、足球半径约11厘米；杯底半径约4厘米，迎球边缘伸出桌面约2厘米且大部分仍受支撑；球沿无遮挡地面先接触外伸杯身，杯子向桌面内侧倒下并留在桌上。**

这些尺寸是创作假设，不是从文字测得。接触高度约12厘米位于足球可触及范围，伸出部分允许接触先于桌缘阻挡；不让球跳跃或穿桌。这里仍不是动力学模拟，无法验证质量、摩擦、冲量等具体条件。若原文明确给出高桌等冲突条件，当前规则拒绝而不静默改写。

### 事件与因果依据

1. `e1`：男孩踢一次球。前置为准备踢、球静止；结束后男孩为踢后姿态，球开始滚动。事件来自原文。
2. `e2`：同一球沿地面滚向桌前。球从桌前位置到可接触杯身的位置，杯子仍直立。
3. `e3`：球与杯身接触。由“撞倒”展开出接触阶段；杯子尚未倾倒。
4. `e4`：同一杯子倾倒。原文只规定倒下；具体朝向及留在桌上的安排列为补全假设，不增加碎裂或泼洒。

时间图：`e1 → e2 → e3 → e4`。

因果／前置图单独保存：

- `e1 causes e2`：`commonsense_assumption`；踢球启动滚动是常识补全，不能只从先后推出。
- `e2 enables e3`：`commonsense_assumption`；接近且路径相交是接触的空间前提，不是充分原因。
- `e3 causes e4`：`explicit_text`；原文结果动词“撞倒”明确将碰撞与倾倒绑定。

对“猫坐在窗边，然后男孩跑起来”，仅记录 `before`；其因果联系为 `unknown`，不加入因果 DAG。

### 完整时间分段和关键帧

- **s01：0–2秒，e1。** 全景交代男孩、同一球、低桌和直立杯子；男孩踢球一次。关键帧为2秒球刚离脚，男孩保持踢后姿态；杯子仍直立，未接触。
- **s02：2–4秒，e2。** 中景保留同一空间方向；球贴地滚向低桌前沿。关键帧为4秒球接近外伸杯身但尚未接触，杯子直立；不重新踢球。
- **s03：4–6秒，e3与e4。** 4–5秒发生接触，5–6秒杯子向内倾倒。关键帧为6秒杯子已侧倒且留在桌上，球仍在桌体外；不要求单张图表现完整运动。

完整结构、每个前置／结果状态和三条未截断提示词保存在 [storyboard.json](../examples/storyboard-football/storyboard.json)。每条提示词都复用原文实体、世界几何、连续性设定和风格，再加入当前唯一关键帧、完整状态、构图与摄影机字段；`image.status` 均为 `not_requested`，`image.path` 均为 null。

提示词的可读语义分别为：

1. **球刚离脚。** 简洁写实连续性故事板；同一男孩、足球、低桌、水杯；平整地面，低桌与外伸杯身按统一空间假设；全景、固定机位、轻微俯视、中性柔光。男孩处于踢后姿态，球刚离脚且开始滚动，杯子仍直立。只画该瞬间，不添加角色、跳跃、破碎或泼洒。
2. **接触前。** 沿用相同角色外观、道具属性、低桌位置和光色；中景、固定机位，保持运动方向。球贴地滚至外伸杯身之前，仍有间距；杯子直立且尚未被触碰。只画该瞬间，不能提前倒杯或让球穿桌。
3. **倾倒后。** 沿用相同场景与风格；中景、固定机位、轻微俯视，构图清楚显示桌面支撑关系。杯子向内侧倒下后留在桌面，球处于桌体外接触区域，男孩保持踢后姿态；不再断言倾倒后的持续接触。只画该瞬间，不增加碎片、液体或反应情节。

以上是完整程序提示词的语义说明，机器输出保留了可审计状态字段，不是已经生成的图像。

新增正式示例：[开门、入室、平稳移桌](../examples/scene-elements-room/storyboard.json)与[拿起、放回水杯](../examples/scene-elements-pick-place/storyboard.json)。均为实际离线运行得到的 6 秒、3 镜头 JSON；包含全场元素快照，未请求图像，图片路径为 `null`。具体变迁、假设和读取代码见[场景元素说明](scene-elements.md)。

## 7. 测试方法、已知限制与扩展方向

已执行内容、发现的问题及修复见 [验证记录](storyboard-validation.md)。复核至少覆盖：空串、非法时长／镜头数、否定和未知语法、来源引文、循环关系、前置不成立、1／3／多镜头、连续状态、独立并行、解析器替换、后文颜色、延迟动作起始、图像配置缺失、HTTP错误、损坏PNG及部分失败。

最小输出断言可以直接对任意 CLI 结果执行：

```python
import json
from pathlib import Path

report = json.loads(Path("storyboard-output/storyboard.json").read_text(encoding="utf-8"))
shots = report["shots"]
assert shots[0]["start_s"] == 0
assert shots[-1]["end_s"] == report["duration_s"]
assert all(left["end_s"] == right["start_s"] for left, right in zip(shots, shots[1:]))
assert all(left["end_state"] == right["start_state"] for left, right in zip(shots, shots[1:]))
assert all(shot["image"]["path"] is None for shot in shots)  # 离线运行不产生假图片路径。
```

当前限制：有限词法无法通用理解自然语言；因果依据是文本和常识规则；时间分配是脚本设计；几何补全仅自洽，不等于物理仿真；提示词复用不能保证跨图角色或空间一致；声音和镜头运动只是脚本；没有真实图像供应方端到端验证。PNG输入有限制且清理辅助元数据，输出目录不应由不可信用户并发替换。

后续优先增加：受约束的模型解析器和人工可编辑场景JSON、参考图／角色特征复用、空间布局条件生成、图像语义核查、局部重生成、一般区间并行调度。连续视频生成需要另接时序模型、运动与音轨合成，并单独验证跨帧一致性，不能靠把几张图排列就宣称实现。
