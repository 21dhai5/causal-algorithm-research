# 因果算法研究

研究关联、预测、因果效应与序列决策的区别，搭建“预测 → 接收观测 → 验证 → 更新”的可审计闭环。

**当前仅为合成数据研究原型。** 没有真实业务数据、真实干预或后台常驻学习；不把预测准确等同于因果发现，不把模拟结果回灌为真实标签。

- [完整九节研究方案](docs/research-plan.md)
- [离线交互研究简报](docs/research-dashboard.html)：下载后在浏览器中打开，可查看本版实验或载入本机 JSON；不上传文件。
- [一手资料与查阅范围](docs/references.md)
- [实际执行的实验与审查](docs/executed-validation.md)
- [参与研究与提交提案](CONTRIBUTING.md)
- [因果事件分镜 MVP](docs/storyboard-mvp.md)：文本规则解析、事件图、时间片段、逐镜提示词及可选图像适配器；分镜静帧不等于连续视频。

- [人脸提示词工具](docs/face-prompt-tool.md)：一句描述补全为完整提示词，支持本机页面、命令行和持久化文本去重；属于有限规则设计补全，不是学习得到的因果推断。
- [特效提示词工具](docs/combat-vfx.md)：按具体元素、局部细节、任意属性与条件关系逐项编写提示词，支持分层编辑、复制和 JSON 导出。

## 特效提示词生成

仅需 Python 3.12+ 标准库。在仓库根目录启动后，打开 <http://127.0.0.1:8766>：

```powershell
python -B experiments/run_combat.py --serve
```

输入画面描述，逐项记录具体细节；名称、数量、父子层级与属性均由输入决定。例如刃口缺口、反光细线、焰心、外焰边界、单束尾迹、接触亮斑、不同位置的扬尘可以分别对应数据。每项生成独立提示词，交互描述保存作用两端、条件、可见响应及前中后状态，完整提示词保留全部条目。

命令行默认输出提示词正文：`python -B experiments/run_combat.py --text "刃口缺口｜形状=小月牙｜位置=刃尖下方"`；加 `--json` 输出数据和逐项提示词。页面和接口仅处理文字，不渲染效果。结构化行可直接读取；普通叙述中无法可靠拆解的内容会逐字保留并标记待细化，不声称已自动识别全部画面元素。示例、开放数据格式与能力边界见[说明](docs/combat-vfx.md)。

## 人脸提示词工具

Python 3.12+ 标准库即可运行。在仓库根目录启动后，打开 <http://127.0.0.1:8765>：

```powershell
python -B experiments/run_face_prompt.py --serve
```

页面只需一个描述输入，支持复制和再次生成；也可用 `python -B experiments/run_face_prompt.py --text "一位成年女性的正面写实肖像"`。无需 API 密钥、图像或训练数据；仅按有限规则生成文字，不保证实际图像或人脸身份不同。历史位置、去重边界和命令参数见[使用说明](docs/face-prompt-tool.md)。

## 文本生成分镜

只用 Python 3.12+ 标准库，无需模型或 NumPy：

```powershell
python -B experiments/run_storyboard.py --text "一个男孩踢了一下足球，足球滚向桌子并撞倒了桌上的水杯。" --output storyboard-output
```

默认6秒、3镜头，独占创建新输出目录。离线不会生成图片或虚假路径；配置 `STORYBOARD_IMAGE_URL`、`STORYBOARD_IMAGE_MODEL`、`STORYBOARD_IMAGE_KEY` 并显式加 `--generate-images` 才发起图像请求。有限规则不覆盖通用中文；空间补全、运行边界和[完整代码](docs/storyboard-source.md)均见说明。

## 运行首版原型

需要 Python 3.12 或更高版本。建议在独立虚拟环境中运行：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.lock
.venv\Scripts\python -B experiments/run_synthetic.py --seed 42 --samples 1200 --replications 30 --output artifacts/my-run.json
```

Linux/macOS 将 `.venv\Scripts\python` 换为 `.venv/bin/python`。省略 `--output` 时输出 JSON；文件默认独占创建，避免覆盖已有报告。需要覆盖时必须显式指定 `--overwrite`；不要在其他人可写的共享目录中覆盖文件。

报告记录生成机制、来源、依赖版本、时间切分、支持拒绝、逐种子结果和区间限制。已运行的探索性结果放在 `artifacts/`；它们是合成实验交付物，不能作为现实有效性证明。

敏感性研究入口为 `python -B experiments/run_sensitivity.py`，独占创建 `artifacts/sensitivity-v1.json`。仓库已包含该版本的实际结果；重新运行前应显式归档已有同名报告。

## 已实现与边界

- 单条序列、二元动作、已知混杂机制；严格按 60% / 20% / 20% 切分训练、校准、测试。
- `ObservationLedger` 校验声明来源、时间、有限值、幂等与修订快照；来源枚举不代替来源认证。
- 持久性基线与动作已知时的一步线性预测；每步参数只使用当时已到达的观测标签。
- 固定训练模型的 g-computation、AIPW，以及作为关联量的未调整组间差。
- 经验支持不足时拒绝效应估计；移动块区间明确标为固定干扰模型的近似条件区间。
- 延迟标签、残差尾部漂移演示和来源/时间负对照；最终指标等待全部测试标签到齐后回顾性计算。

尚未实现自然动作边缘化预测、自动因果图发现、一般事件驱动评分/纠错重放、多步模拟、全流程有效推断、离线策略评价或强化学习。真实数据的识别分析与真实动作执行尚未接入。

## 目录

`src/causal_research/` 保存账本、模型、生成机制与评价；`experiments/` 保存可重复运行的研究入口；`docs/` 保存研究协议、证据与展示；`artifacts/` 保存明确标注的合成结果；`.github/` 保存提案、PR 和只读 CI 配置。

这是独立建立的新项目，不包含已放弃项目的源码、数据或历史。尚未选定项目级开源许可证；第三方依赖保留其适用许可证。
