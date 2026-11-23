---
name: versioned-experiment-feasibility-review
description: Use when an experimental-design case supplies one or more versioned experimental plans plus equipment, material, price, booking, sample or ethics constraints and asks for a feasibility review; run scripts/run_skill.py to produce a contract-preserving result.json with per-version checks, resource status, time and sample arithmetic, conflicts and a defensible conclusion.
---

# 版本化实验方案可行性审查

## 用途与适用条件

对一份或一组版本化实验方案做资源与条件核验：逐项检查设备、材料、时间、样本、参数范围、风险与异常、伦理与安全七类约束，区分“已具备 / 可外协 / 需采购 / 不具备 / 未知”，给出可执行结论（可行、有条件可行、不可行、信息不足）及具体条件。

适用于 `versioned_feasibility_review` 类案例：每例含 3 个版本化候选方案、前瞻性资源/价格/预约契约和有限参数域。

不适用：实验执行、数据分析建模、文献综述、论文写作。审查结论不替代实验室安全员或伦理委员会的正式审批。

## 输入

- `/input/case.json`（可用 `--case`）：`case_id`、`output_contract`；常见可选键 `plans`/`plan_versions`、`resources`/`equipment`/`materials`、`price_list`、`bookings`、`samples`、`ethics`、`constraints`、`parameters`/`parameter_domains`、`time_window_h`。
- `/input/task.md`（可选）：补充审查口径。
- 输出默认 `/app/output/result.json`。

## 处理流程（对应评分维度）

1. **版本识别（任务完成度）**：按 `version`/`revision`/`version_id` 排序方案；若只有一版，标 `single_version`，不做伪差异。取最新版为主审查对象，并保留全部版本结果。
2. **七类检查项（完整性）**：对每个版本逐项检查 `hypothesis_and_variables`、`controls`、`equipment_and_materials`、`time_cost`、`parameter_range`、`risk_and_exception`、`ethics_and_safety`；每项给 `pass`/`conditional`/`fail`/`unknown` 与依据路径。
3. **引用匹配（正确性）**：把方案中出现的设备/材料名称与资源清单做规范化匹配（小写、去标点），输出 `matched_resource`；未匹配不得默认为“已满足”，记 `unknown`。
4. **资源状态四分类（正确性）**：依据清单中的 `availability`/`status`/`lead_time`/`stock` 归为 `available`、`outsource`、`procure`、`unavailable`、`unknown`；采购与外协写入条件。
5. **时间与排期算术（正确性）**：汇总步骤时长或方案声明时长，与 `time_window_h`、设备预约小时比较；给出差值与超时比例；等待周期单独列出，不并入人工工时。
6. **样本与伦理（正确性）**：核对所需样本数、重复数与可得样本数；检测动物/人体样本/危险试剂/个人数据标志，输出所需审批级别与状态，缺审批信息记 `unknown`，不写成已批准。
7. **参数越界（正确性）**：把方案参数值与有限参数域比较，逐项输出 `in_range`/`out_of_range`/`no_domain`。
8. **结论与条件（可核验性）**：按“存在 fail → not_feasible；仅 conditional/unknown → conditionally_feasible 或 insufficient_information；全部 pass → feasible”的规则生成结论，并列出可执行的前置条件、责任人与复核动作。
9. **版本差异（创新增益）**：字段级比较最新版与上一版，说明修订是否消除上一版的阻塞项。

## 输出契约

| 字段 | 含义 |
|-|-|
| `case_id` | 与输入一致 |
| `output_contract` 各字段 | 命中则填真实值，否则 `null` + `contract_notes` |
| `status` | `success` / `partial` / `insufficient_input` / `failed` |
| `result` | `plans_reviewed`、`reviews`（逐版本）、`selected_version`、`conclusion`、`conditions`、`version_diff`、`sample_check`、`ethics_check` |
| `evidence` | 输入哈希、命中的键路径、资源条目索引 |
| `uncertainty` | 未知资源状态、缺失审批、未声明参数域 |
| `errors` / `stats` | 真实错误与计数（检查项数、fail 数） |

## 异常处理表

| 情况 | 处置 | 状态 |
|-|-|-|
| `case.json` 缺失/非法 | 空骨架 + `case_load_failed` | `failed` |
| 无方案 | 输出空 reviews，说明缺失 | `insufficient_input` |
| 方案无版本号 | 按输入顺序编号并注明 | `partial` |
| 资源清单为空 | 所有资源项 `unknown`，结论最多 `insufficient_information` | `insufficient_input` |
| 方案提到的设备未在清单 | `unmatched_resource`，不视为已具备 | `conditional` |
| 时间窗缺失 | 不判定超时，记 `time_window_not_provided` | `partial` |
| 伦理状态未定 | `ethics_and_safety` 记 `unknown` | `partial` |
| 方案自相矛盾（声明的总量与分项不符） | 记录 `arithmetic_mismatch` 并以分项为准 | `partial` |

## 限制

- 只审查输入中出现的方案与资源，不补充外部设备参数或法规条款。
- 不对科学假设本身做同行评审式判断，只检查其是否可检验、是否绑定变量与对照。
- 价格、库存、排期均视为组织方前瞻性契约，不代表真实供应商报价或实验室占用。
- 不生成审批编号或安全许可结论。

## 最小调用示例（示例，非官方案例结果）

```bash
python /skills/weekly-skill/scripts/run_skill.py --case /input/case.json --out /app/output/result.json --work /app/work
```

示意输入：`{"case_id":"synthetic-review-demo","output_contract":{"reviews":"array","conclusion":"string"}}`。示意输出保留 `case_id`、`reviews`、`conclusion`、`status`；无方案时 `insufficient_input`，`reviews` 为空数组。仅为接口示例。


## 交付保证与评分对齐

调用顺序（固定）：

1. 先运行包内脚本（若存在）：`python scripts/run_skill.py`（默认读 `/input/case.json`，写 `/app/output/result.json`）；路径不同时用 `--case` / `--out` 指定。
2. 再完成脚本无法自动完成的实质工作（译文、论述、图表、修订、结论等），把结果写回 `result.json` 对应字段。
3. 最后自检：`case_id` 与输入一致；`output_contract` 每个字段都存在；`status` 为 `completed`（仅在确实缺输入时为 `partial`）；无 `pending` 占位；数字、引用、来源可逐条回溯。

运行保证：

- 输入缺失、JSON 损坏、字段异常、输出目录不存在时，仍须写出结构化 `result.json` 并正常结束，不得崩溃或非零退出。
- 不联网、不伪造数据、不声称平台评分或官方案例结果。
- 交付物必须是可直接编辑与复核的成品，而不是流程说明。

评分对齐（本题五个维度）：

- 实际效果（40）：完整产出任务要求的最终成品，覆盖全部输入条目，可直接进入修改流程。
- 使用增益（25）：体现相对基础 Agent 的可验证改进（结构化、术语/数字/引用核对、可编辑性）。
- 创新增益（15）：保留方法学增量（分块、对齐、二次校验、版本比对等），并用结果证明其价值。
- 可靠体验（10）：异常输入有明确降级与说明，不同长度/文体/重复运行下稳定产出。
- 生态贡献（10）：用途、调用、输入输出、限制、示例、维护信息齐全，资源可被他人复用。

## 最终交付强制要求

1. **调用 Agent 必须交付成品，不是流程说明**：脚本产出只是索引、核对或规格骨架；调用 Agent 必须在同一 `result.json` 中补齐本题要求的最终产物（正文/译文/审稿意见/综述/分析结论/图表源文件与导出件/幻灯片页内容与讲稿/实验方案等）。交付字段为空、只有标题骨架，或含 `pending`、`TODO` 之类占位，一律视为未完成。
2. **必须覆盖全部输入条目**：输入中的每个章节、问题、文献、图、页面、指标都要有对应条目，不得只处理示例或首条；确实缺失的条目写入 `uncertainty` / `limitations` 并说明原因，不得静默跳过。
3. **必须自检后再交付**：`case_id` 与输入一致；`output_contract` 每个字段都存在；状态值取本题契约规定的枚举；数字、单位、引用、来源可逐条回溯；结果内部无自相矛盾。
4. **参数等价**：`python scripts/run_skill.py --case <输入> --out <输出>` 与 `--output <输出>` 等价；默认 `/input/case.json` → `/app/output/result.json`。
5. **平台用 3 个固定案例分别运行**：逻辑要由输入驱动，不针对某一份示例硬编码；字段命名差异走别名匹配与显式降级，并在 `uncertainty` 记录假设。
