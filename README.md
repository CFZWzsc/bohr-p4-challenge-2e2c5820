# 实验方案可行性审查技能（experimental-plan-checklist-review）

## 1. 用途

对实验方案做基于检查表的可行性审查：按固定检查项逐条核对章节、参数行、资源清单与伦理状态，给出 `satisfied/partial/missing/conflict/uncertain` 判定、可回读的证据定位、严重度与需补条件，并汇总为“可行 / 有条件可行 / 不可行”。输出面向人工复核，不能只给结论。

## 2. 单次运行

在包根目录执行：

```bash
python scripts/run_skill.py --input examples/demo-case --work out/work --out out
```

- `--input`：案例目录（不是单个文件），目录内至少包含 `case.json`，通常配套 `protocol.md` 与 `inventory.csv`。
- `--work`：工作目录，用于日志与临时文件。
- `--out`：输出目录；若以 `.json` 结尾，则视为结果文件路径。
- `scripts/sk_entry.py` 与 `scripts/run_skill.py` 等价；入口恒以退出码 0 结束，输入缺失或损坏时写降级结果。

## 3. 输入目录结构与字段

```text
<case-dir>/
  case.json       # 案例元数据、契约、参数域、伦理/安全、文档条款
  protocol.md     # 方案正文；也支持 task.md / *.txt / *.json
  inventory.csv   # 资源清单；也支持 *.tsv
```

### 3.1 case.json

| 字段 | 含义 |
|---|---|
| `case_id` | 案例标识，原样写入结果。 |
| `task` | 审查任务描述，参与伦理触发词检测。 |
| `output_contract` | 期望输出契约；声明的键会映射到结果顶层，别名记录在 `contract`，未知键记录在 `contract_extras`。 |
| `inventory_file` | 资源清单文件名；实际发现时仍会扫描目录内全部 CSV/TSV。 |
| `time_window_h` | 项目时间窗（小时）；缺失时时间检查判 uncertain。 |
| `parameter_domains` | 有限参数域，如 `{"column_temp": {"min": 30, "max": 40, "unit": "°C"}}`；键可为规范名或中文参数名。 |
| `ethics` | 伦理状态；`status` 取“已批准/审批中/已拒绝/已声明但状态不明/未声明”，可带 `approval_id`、`valid_until`。 |
| `safety` | 安全备案状态与危险项。 |
| `documents` | 文档条款数组，每项含 `doc_id/title/version/clauses[{clause_id,text}]`；用于引用 SOP、手册与伦理依据。 |
| `checklist` | 可选；案例自带检查项时优先采用，缺失的默认类别会自动补齐。 |
| `resources/inventory/equipment/materials` | 可选；内嵌资源清单，与 CSV 合并去重。 |
| `samples` | 可选；可直接给 `available/required`。 |

### 3.2 protocol.md

按 `#`/`**粗体**`/中文序号标题切分章节。审查依赖以下内容可被原文明确写出：假设与变量、对照与分组、设备与材料、样本数与重复数、步骤时长、伦理/安全状态、参数行、风险与降级路径。

### 3.3 inventory.csv

表头识别 `name/category/model/status/quantity/unit/lead_time_days/note`，兼容中文列名（名称、类别、型号、状态、数量、单位、货期、备注）。`status` 归一到四类资源状态：已具备 / 可外协 / 需采购 / 不具备；无法判断记未知。

## 4. 审查项体系

默认 9 项：覆盖竞赛要求的七类约束（设备、材料、样本、时间、伦理与安全、参数范围、风险与异常），并补充“假设与变量”“对照组”两项方法学检查。

| ID | 类别 | 判定满足的最低证据 | 默认严重度 |
|---|---|---|---|
| CHK-01 | 假设与变量 | 同一方案中同时出现可检验假设与可测量变量/终点 | major |
| CHK-02 | 对照组 | 同时写明阴性对照与阳性对照及分组；明示“不设对照”判缺失 | major |
| CHK-03 | 设备 | 方案点名设备可在清单逐项匹配且状态为已具备 | major |
| CHK-04 | 材料 | 耗材/试剂规格可在清单匹配，数量与状态满足 | major |
| CHK-05 | 样本 | 明示样本数×组数×重复数，且可得量 ≥ 需求 | major |
| CHK-06 | 时间 | 明示步骤时长合计 ≤ 时间窗 | major |
| CHK-07 | 伦理与安全 | 触发项存在时审批已批准并给出批件编号 | blocker |
| CHK-08 | 参数范围 | 每个参数落在有限参数域或设备边界内 | major |
| CHK-09 | 风险与异常 | 风险项与可执行降级/替代/转人工路径同时出现 | major |

## 5. 判定规则与阈值

### 5.1 单项判定

| verdict | 含义 |
|---|---|
| `satisfied` | 有原文或清单行直接支持，且无相反证据。 |
| `partial` | 方向正确但缺关键要素，如只写对照未分阴性/阳性、资源需采购/外协。 |
| `missing` | 应写的章节/参数/记录未出现；未写不等于满足。 |
| `conflict` | 原文与清单、参数域、伦理状态或分项合计互相矛盾。 |
| `uncertain` | 缺清单、缺参数域、单位无法换算、状态未声明等，不能默认满足。 |

### 5.2 结论

- **可行**：全部检查项 `satisfied`。
- **有条件可行**：无未满足的 blocker，但至少一项非 `satisfied`；必须输出 `required_conditions`。
- **不可行**：至少一项 blocker 未满足（如伦理未获批/被拒、关键资源不具备、样本或时长缺口 > 50%）。
- **信息不足**：没有可读方案材料时的降级结论。

计数必须与 `checklist` 一致：`counts.total == len(checklist)`，`findings` 等于非 `satisfied` 条目，结论由计数规则唯一决定。

### 5.3 关键阈值

- 时间：仅汇总输入明示的分项时长，统一换算为小时；分项合计与声明总时长差 > 0.1 h 记 `arithmetic_mismatch`；超窗且比例 > 1.5 记 blocker，否则 major。
- 样本：`required = 样本数 × 组数 × 重复数`，未写的组数/重复数按 1 并在公式中显示；缺口 ≤ 50% 记 major，> 50% 记 blocker。
- 参数：同名参数归一后先换算单位再比较；越界或单位不可换算记 conflict；无参数域记 uncertain。
- 资源：已具备判满足；可外协/需采购判 partial；不具备判 conflict（blocker）；状态未知判 uncertain。方案点名但清单无对应行时不得默认已具备。

### 5.4 证据定位

每条非满足项必须同时有 `locator` 与连续原文 `quote`，入口会回读校验：

- 行/章节：`protocol.md#L42`、`protocol.md#L28-L31`。
- 表格行：`inventory.csv#row=4`（含表头的实际行号）。
- 参数域：`case.json#/parameter_domains/column_temp`。
- 文档条款：`case.json#/documents/0/clauses/0/text`。

`evidence.verified=false` 的 finding 不算完成。

## 6. 输出字段

入口固定写 `result.json` 与 `run-review.md`，并附带 `constraint_check.csv`、`report.md`、`validation.json`、`provenance.json`。

`result.json` 顶层主要字段：

| 字段 | 含义 |
|---|---|
| `case_id` / `status` / `status_reason` | 案例标识、运行状态与原因。 |
| `conclusion` | 中文结论。 |
| `verdict_summary`（别名 `state`） | 结论、计数、严重度计数、blocker 统计与规则说明。 |
| `score` | 分类均值、总分、等级、阻断项与需补条件列表。 |
| `checklist`（别名 `items`） | 9 项逐条结果，含 verdict、severity、evidence、rationale、required_condition。 |
| `findings`（别名 `issues`） | 非 satisfied 条目。 |
| `resources` | 资源匹配行、状态计数、未匹配型号与待确认条件。 |
| `estimates` | 时间、样本、参数的估算值、算式与状态。 |
| `conflicts` / `missing_info` / `required_conditions` | 冲突、缺失信息与需补条件。 |
| `evidence`（别名 `citations`） | 全部证据及其回读校验结果。 |
| `uncertainty`（别名 `notes`） | 不确定性、边界与处理建议。 |
| `metadata` / `run_log` / `summary` | 版本、输入文件摘要、步骤日志与摘要。 |
| `contract` / `contract_extras` | 契约映射与实际写入的额外键。 |

## 7. 依赖与限制

- 纯 Python 标准库，离线运行，不访问网络，不写 `__pycache__` 依赖。
- 确定性输出：同一输入产生相同 `result.json`。
- 不做 OCR/图片解码；扫描件需先转成可读文本。
- 不查询供应商价格、货期或最新法规；不代替伦理委员会出具意见，也不伪造批件、库存或 SOP 条款。
- 输入缺失或损坏时仍以退出码 0 写降级结果，并在 `status`/`uncertainty` 中标明。

## 8. 配套材料

- `examples/demo-case/`：可直接运行的最小案例。
- `bench/`：技能与朴素关键词基线的公平对照、金标准、指标与复现说明，见 `bench/README.md`。
- `templates/checklist.json`：可复用的审查项模板。
- `templates/review_checklist.md`：人工复核清单模板。
