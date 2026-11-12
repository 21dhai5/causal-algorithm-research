# 因果算法研究

研究关联、预测、因果效应与序列决策的区别，搭建“预测 → 接收观测 → 验证 → 更新”的可审计闭环。

**当前仅为合成数据研究原型。** 没有真实业务数据、真实干预或后台常驻学习；不把预测准确等同于因果发现，不把模拟结果回灌为真实标签。

- [完整九节研究方案](docs/research-plan.md)
- [离线交互研究简报](docs/research-dashboard.html)：下载后在浏览器中打开，可查看本版实验或载入本机 JSON；不上传文件。
- [一手资料与查阅范围](docs/references.md)
- [实际执行的实验与审查](docs/executed-validation.md)
- [参与研究与提交提案](CONTRIBUTING.md)

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
