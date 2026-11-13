# 场景元素与状态传播

这项扩展为文本分镜增加一个有限的符号世界：先登记环境和器物，再登记主体、执行动作；每一步都保存全场状态及变化依据。它使用手写规则，不从数据识别因果，不理解图像，不进行物理仿真，也不生成连续视频。本文的正式示例只包含 JSON 和提示词，没有调用真实图像服务。

## 直接运行

在仓库根目录使用 Python 3.12+，无需第三方依赖：

```powershell
python -B experiments/run_storyboard.py --text "房间里有一扇关闭的门，墙上挂着一幅画，桌上放着一个水杯。一个男孩打开门，然后走进房间，再平稳地把桌子移到房间右侧。"
python -B experiments/run_storyboard.py --text "房间里有一张桌子，桌上放着一个水杯，墙上挂着一幅画。一个男孩拿起水杯，然后把水杯放回桌上。"
```

两条命令默认各输出 6 秒、3 镜头的 JSON 到终端。加 `--output scene-output` 可在已有父目录中独占创建新目录，只保存 `storyboard.json`；目标已存在会失败，请更换目录名。上述命令未带 `--generate-images`，不会发起图像调用，所有 `image.status` 为 `not_requested`、`image.path` 为 `null`。

正式输出已保存在[开门、入室、移桌示例](../examples/scene-elements-room/storyboard.json)和[拿起、放回示例](../examples/scene-elements-pick-place/storyboard.json)，无需重新运行也可查看。

## 输入写法

环境声明必须放在动作之前；每个分句都必须完整匹配。以下是有限语法的可用片段，组合时仍须满足动作前置条件：

- 场景、初态：`房间里有一扇关闭的门`、`门是打开的`、`房间里有一张桌子`、`桌上放着一个水杯`、`墙上挂着一幅画`、`桌子在房间左侧`。
- 主体：第一个动作明确写 `一个男孩`、`一个女孩` 或 `一个人`；后续可省略主体，或使用与唯一人物一致的代词。
- 动作：`打开门`、`关闭门`、`走进房间`、`拿起水杯`、`把水杯放回桌上`、`平稳地把桌子移到房间右侧`。水杯也可写杯子；拿取可用箱子，放置目标可用箱子，平稳移动可用箱子。
- 顺序：用逗号或句号分句，动作间可用 `然后`、`随后`、`接着`、`再`。无连接词时按叙述顺序安排，并记录该顺序是补全假设。

场景名可用房间、屋子或房子；符号方位为左侧、右侧、中间或中央。方位只适用于直接位于场景根节点的器物；“桌上箱子在房间右侧”需要额外坐标换算，当前拒绝，不会改写成箱子在桌子的局部右侧。提到墙上挂画时登记墙和画，提到桌上水杯时登记桌和杯。未写具体环境时，只用抽象 `space` 组织提到的器物，不添加可见房屋、入口或装饰。

文本入口限一个场景、一个人物、每类器物一个身份。再次使用“有一个水杯”等存在声明会产生身份歧义，明确拒绝；泛指“人”使用的他／她必须前后一致。衣着、颜色变体不能从旧足球示例泛化到此语法；未知分句、否定、条件、疑问、多人、跨场景及并行动作都会拒绝。声明放到动作后也会拒绝，避免把未来描述倒灌为初态。

前置不成立同样失败，例如：没有明确入口就走进房间、门关闭而直接进入、上锁却开门、未拿起就放回、试图拿起固定在墙上的画。移桌或移箱必须明确写出“平稳”或“准静态”；当前没有一般搬运、碰撞、滑落或跨房间传送语法。

## 一次动作如何影响全场

处理顺序是：初始化世界 → 检查动作前置 → 写入直接效果 → 沿关系链派生位置 → 保留无关元素 → 保存完整快照 → 分配时间和镜头。

1. **登记身份和初态。** `construction_order` 固定为 `environment → objects → subjects`。所有状态使用 `entity.attribute` 键，动作不能临时创建新器物。
2. **检查前置。** 如开门需要关闭且未锁；入室需要人物在门外、入口可达、门已打开且位于目的区域；拿取需要空手且器物未固定；放置需要实际手持、静止且稳定的支撑体。可达条件按主体、目标和起始区域登记为布尔断言，说明中出现“可达”二字不会使条件成立。前置不满足时终止，不静默跳过或补做动作。
3. **写入直接效果。** 开门改变 `door.open`；入室改变人物 `location`；拿取和放置同时更新器物的 `location`、`supported_by`、`held_by` 与人物的 `holding`。
4. **传播位置。** `location` 指向直接位置父体，支撑、固定和手持关系约束该父体。沿位置链计算最近区域 `root_location` 和符号位置路径 `world_position`；父体位置变化可以传到其后代。路径保留每层身份和未知值，例如 `room:table=unknown/cup=left` 只说明杯在桌的局部左侧，不能解释为杯在房间左侧；这不是实测坐标。
5. **保留与记录。** 没有直接效果或位置传播的元素保留全部已登记属性。拿取、放置或进门改变位置父体时，新父体下的局部方位退回 `unspecified`，不沿用旧方位；器物后代相对于器物的方位可以保持。进行时与完成态分别计算，后续动作不会改写前一快照；镜头保存全场起止状态和单一时刻的关键帧。

### 开门、入室、移桌

第一份示例中的主要完成态变化是：

```text
e1 open_door:   door.open: closed → open
e2 enter_room:  boy.location: outside → room
e3 move_object: table.position: unspecified → right
               cup.world_position:
                 room:table=unspecified/cup=unspecified
                 → room:table=right/cup=unspecified
```

杯子的 `location` 和 `supported_by` 始终为 `table`，`pose` 保持 `upright`。杯子没有被直接操作，但桌子位置变了，因此杯子的位置路径跟随；杯子在桌上的精确位置仍未指定。画的 `attached_to=wall`、`pose=hanging` 及位置均保留，`painting` 在每一步的 `unchanged_entities` 中；开门和人物移动不会自动让画掉落。

其中门关闭、墙画、桌上杯子和各动作是**原文事实**。门未锁、入口可达、人物开始在入口外、器物初始静止、桌面稳定，以及平稳搬运保持支撑且无滑落，是**集中记录的必要假设**；位置未指定仍为未知。桌上杯子随移桌传播是**在这些假设下应用规则的结果**，不代表现实中已经验证杯子一定不会滑落。

### 拿起、放回

第二份示例在两次动作后的关系为：

```text
                     初态       拿起后       放回后
cup.location         table      boy          table
cup.supported_by     table      null         table
cup.held_by          null       boy          null
boy.holding          null       cup          null
```

画仍固定在墙上。`scene.element_model.relations` 描述的只是**初始关系**，它不会把拿起后的杯子重新绑回桌上；应读取对应时刻快照中的关系。拿起进行中也保留拿起前的支撑，完成后才切换到手持，不能在早期镜头提前得到结果。

## 输出和证据从哪里读

顶层 `schema_version` 为 `1.1`，`scene.element_model.version` 为 `1.0`。旧语法仍可使用同一入口，只有元素场景输出下列扩展字段：

- `scene.element_model`：`construction_order` 及 `environment_ids`、`object_ids`、`subject_ids` 登记身份；`relations` 的 `scope` 和模型 `relation_scope` 均为 `initial_state`；`state_sources` 对应每一条初态属性；`action_conditions` 按 `event_id`、主体、目标登记 `reachable` 或 `support_preserved` 条件、布尔值和证据；可达条件还限定 `from_location`；`rule_catalog` 导出手写规则 ID 和说明，其 `basis` 为 `rule_based_not_data_identified`。
- `element_trace`：每次事件记录 `event_id`、完整 `before`／`after`、`direct_effects`、`propagated_effects`、`unchanged_entities`、`unresolved_effects`。效果项包括 `entity`、`property`、`before`、`after`、`rule_id`、`evidence`；派生位置采用 `inherit_location` 规则。
- `events`：保存真正读取的状态 `preconditions`、结构化 `required_conditions`、进行时差量 `active_state`、完成态差量 `updates`，并保留动作来源。`shots` 则保存全场 `start_state`、`end_state`、`keyframe.state` 及 `image_prompt`，提示词使用该时刻的支撑、固定、手持和派生位置。
- `state_dependencies`：按前置状态的最近写入者记录 `enables_under_rules` 边和 `state_keys`。本例 `e1 → e2` 通过 `door.open` 相连，`e2 → e3` 通过人物位置相连；载荷检查还记录读取的位置拓扑，因此“先拿走杯子，再移桌”的解除载荷依赖也会保留。它是规则执行读取依赖，可能包含保守的拓扑读取，并非最小原因集合，也不是现实因果证明。

`evidence` 使用 `basis`、`quote`、`explanation`。`explicit_text` 的引文须逐字来自输入；`commonsense_assumption` 表示必要补全或规则推演；`unknown` 表示依据不足。`scene.assumptions` 集中列出补全，`state_sources` 说明初态来源，效果记录说明变化来源；这些标签不是置信概率，也不是来源认证。

移物的 `unresolved_effects` 明确记录未建模的风、震动、摩擦或加速度等因素。移动、拿起、放置以及携物进门都会检查受支撑后代：若要保留箱子上杯子等后代的支撑，必须在**本次动作**的 `action` 中设置 `transport_mode=quasistatic`，并提供绑定同一 `event_id`、主体及搬运目标的 `support_preserved=true` 条件，否则拒绝执行。未来平稳移动的条件不能授权此前普通拿取；文本入口不会自动为普通“拿起箱子”补造这些额外保证。它不会自动推断滑落、泼洒、破碎或掉画；列表为空也不表示已排除现实中的所有影响。`unresolved_causal_relations` 另存无法确定的一般事件因果联系，“然后”只提供顺序，不自动产生因果边。

动作或确定顺序的证据不能为 `unknown`。复核会重新编译并比较派生输出，可以发现被手改的状态、效果和依赖；它不能证明提交者提供的原文和原始证据真实，也不能用“引文存在”证明该引文在语义上足以支持断言。结构化场景仍应来自可信解析器或经过内容审查。

以下代码可在仓库根目录读取正式结果，无需导入项目包：

```python
import json
from pathlib import Path

# 读取完整链示例，不发起图像请求或写入文件。
board = json.loads(Path("examples/scene-elements-room/storyboard.json").read_text(encoding="utf-8"))
for step in board["element_trace"]:  # 按事件查看全场完成态和传播依据。
    print(step["event_id"], step["after"]["cup.world_position"])
    print(step["propagated_effects"])
```

## Python 接口与结构化场景

安装项目或令 `PYTHONPATH` 指向 `src` 后，可以直接规划并复核元素场景：

```python
from causal_storyboard import RuleSceneParser, build_storyboard, validate_element_scene

# 使用带初态声明的完整文本，所有前置和来源仍由规则检查。
text = "房间里有一张桌子，桌上放着一个水杯，墙上挂着一幅画。一个男孩拿起水杯，然后把水杯放回桌上。"
scene = RuleSceneParser().parse(text)  # 返回已编译、带完整轨迹的场景。
validate_element_scene(scene)  # 重新编译并比较状态、效果与规则记录；失败抛 ValueError。
board = build_storyboard(text, duration=6, shots=3)  # 纯规划，不写文件或调用图像服务。
assert board["element_trace"][-1]["after"]["cup.supported_by"] == "table"
```

`SceneParser` 是可替换协议：应用可自行读取结构化 JSON，实现 `parse(text) -> dict`，再传入 `build_storyboard(text, parser=...)`。返回的场景骨架须含实体、初态及逐属性来源、集中假设、`element_model`、动作 `action` 参数、三阶段关键帧和显式事件顺序；用公开的 `compile_element_scene(scene)` 编译，再由 `validate_element_scene` 和 `validate_scene` 校验。编译在副本上工作；不要手改已编译的差量或轨迹来绕过前置。

结构化接口允许同一 `kind` 的实体使用不同稳定 ID，仍受类型、位置无环、互斥关系、单手及顺序约束；这不扩展文本入口的“一类一物”能力。当前 CLI 只接收 `--text`，没有 JSON 输入参数或场景编辑器。把结果保存成 JSON 只是在记录可审计的因果规则与推演，不会训练或更新 `world.py` 中的知识。

更完整的时间、图像适配和安全边界见[分镜 MVP](storyboard-mvp.md)；项目整体实际验证见[验证记录](storyboard-validation.md)。
