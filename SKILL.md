---
name: experimental-plan-checklist-review
description: Use for experimental-design cases that require a checklist-based feasibility review of a protocol against equipment, materials, samples, time, ethics, parameter and risk constraints. Runs scripts/sk_entry.py over /input and writes /app/output/result.json plus /app/output/run-review.md with locator-verified findings and explicit required conditions. Standard library only, offline, deterministic.
---

# 实验方案审查（Checklist Review）

## 用途

对一份实验方案做可执行的可行性审查：按固定检查项逐条核对章节、参数行和资源表格，给出 `satisfied/partial/missing/conflict/uncertain` 判定、证据定位与原文、严重度、需补条件，并汇总为“可行 / 有条件可行 / 不可行”。输出必须能让评审人按 locator 回到原文复核，不能只给结论。

## 适用条件

- 案例要求“实验方案审查”“方案可行性/完备性评审”，并需要检查表、逐项证据或时间/样本估算。
- 输入至少有一份可读方案材料（Markdown/Text/JSON/CSV），或 `case.json` 内嵌方案。
- 需要核对设备/材料/样本条件、伦理与安全、参数范围、风险与异常。
- 需要在结论中区分“已具备 / 可外协 / 需采购 / 不具备”，并给出需补条件。

## 不适用场景

- 只要求润色文字、写论文摘要、翻译或排版，不做可行性判定。
- 只给一张图片/PDF 扫描件且没有可提取文本；本技能不解码图片或 OCR。
- 要求联网查询供应商价格、货期或最新法规；本技能离线运行，不访问网络。
- 要求代替伦理委员会出具审批意见，或伪造批件、库存、SOP 条款。

## 输入形态

`--input` 指向目录，入口自适应读取：

- `case.json`：案例元数据、`output_contract`、`parameter_domains`、`resources/inventory`、`ethics/safety`、`documents`、`time_window_h` 等。
- `protocol.md` / `task.md` / `*.txt`：按 `#`/`**粗体**`/中文序号标题切分章节。
- `*.csv` / `*.tsv`：表头识别 `name/category/model/status/quantity/unit/lead_time_days`（兼容中文列名），每行作为资源记录。
- `*.json`：递归展开为 JSON Pointer 定位的内容节。
- 若 `case.json` 内嵌 `protocol/plans/design/method/steps`，即使没有独立方案文件也会读取。

## 调用方式

安装后的精确命令：

```bash
python /skills/weekly-skill/scripts/sk_entry.py --input /input --work /app/work --out /app/output
```

等价 wrapper：

```bash
python /skills/weekly-skill/scripts/run_skill.py --input /input --work /app/work --out /app/output
```

参数：

- `--input`：输入目录，默认 `/input`。
- `--work`：工作目录，默认 `/app/work`。
- `--out`：输出目录，默认 `/app/output`；若以 `.json` 结尾则视为结果文件路径。

脚本固定写 `result.json` 与 `run-review.md`，退出码恒为 0（输入缺失/损坏也写降级结果）。

## 审查项体系与判定规则

默认 9 项（`assets/checklist.json`）：

| ID | 类别 | 满足条件 | 不满足时的处理 |
|---|---|---|---|
| CHK-01 | 假设与变量 | 假设 + 可测量变量/终点同时出现 | 只有其一→partial；均无→missing |
| CHK-02 | 对照组 | 阴性/阳性对照与分组写明 | 明示不设对照→missing；只写对照→partial |
| CHK-03 | 设备 | 方案点名设备在清单中且状态已具备 | 可外协/需采购→partial；不具备→conflict；无清单→uncertain |
| CHK-04 | 材料 | 耗材/试剂/色谱柱规格与库存匹配 | 缺行/规格不符不得默认满足 |
| CHK-05 | 样本 | 明示样本数×组数×重复数，且可得量足够 | 不足→conflict；数字缺失→uncertain |
| CHK-06 | 时间 | 明示步骤时长合计 ≤ 时间窗 | 超窗→conflict；无时间窗→uncertain |
| CHK-07 | 伦理与安全 | 触发项存在时审批已批准且有批件编号 | 审批中→partial；未声明→uncertain；被拒→conflict/blocker |
| CHK-08 | 参数范围 | 每个参数落在有限参数域/设备边界内 | 越界或单位不可换算→conflict；无参数域→uncertain |
| CHK-09 | 风险与异常 | 风险项 + 降级/替代/转人工路径 | 只有风险→partial；均无→missing |

规则细节见 `references/review-checklist.md`。案例自带 `checklist` 时优先采用；缺失的默认类别会补齐，并记录 `checklist_source`。

## 结论口径

- **可行**：全部检查项 satisfied。
- **有条件可行**：无 blocker 未满足，但至少一项 partial/missing/conflict/uncertain；必须输出 `required_conditions`。
- **不可行**：至少一项 blocker 未满足（伦理被拒/未获批、关键资源不具备、样本或时长缺口 > 50%）。
- **信息不足**：没有可读方案材料时的降级结论；不强行判可行/不可行。

`verdict_summary` 必须与 `findings` 一致：`counts.total == len(checklist)`，`findings` 等于非 satisfied 条目，结论由计数规则决定。

## 证据定位格式

- 行/章节：`protocol.md#L42`、`protocol.md#L28-L31`。
- 表格行：`inventory.csv#row=4`（文件实际行号，含表头）。
- 参数：`case.json#/parameter_domains/column_temp`。
- SOP/手册/伦理条款：`case.json#/documents/0/clauses/0/text`。

每条 finding 必须同时有 `locator` 与 `quote`；`quote` 是该定位处的连续原文，不得改写或拼接。入口会把 `quote` 回读校验，`verified=false` 的 finding 不算完成。

## 严重度分级

| 级别 | 含义 | 例子 |
|---|---|---|
| blocker | 不解决不能开工 | 伦理被拒、关键设备不具备、样本缺口 > 50% |
| major | 影响结论或需补条件 | 无对照、参数越界、样本不足、时间超窗 |
| minor | 影响可复现性 | 单位未写、步骤不清 |
| info | 提示 | 版本号、责任人 |

## 时间与样本估算规则

- 只用输入明示数字；缺什么记 uncertain，不补经验值。
- 时间：提取 `h/小时/min/分钟/d/天`，按设备占用/人工操作/等待周期分相，输出算式；跳过“总时长/时间窗/判读标准”行；与 `time_window_h` 比较。
- 样本：`required = 样本数 × 组数 × 重复数`，未写组数/重复数按 1 并在公式中显示；可得量取样本库存行 `quantity` 合计；不足记 shortfall。
- 参数：同义名归一，先单位换算再比较；无法换算记 `unit_inconsistent`。
- 详细规则见 `references/estimation-rules.md`。

## 异常处理

| 情况 | 处理 |
|---|---|
| 缺章节 | 该检查项判 missing，定位到方案首个可读行，rationale 写明检索词未命中；不伪造引文 |
| 参数缺失 | 判 uncertain，列出缺失参数；不默认在范围内 |
| 单位不一致 | 先换算（时间/体积/质量/温度）；不可换算判 conflict/uncertain，并记 `unit_inconsistent` |
| 互相矛盾 | 判 conflict，同时列两处 locator；结论按最不利处理 |
| 无 `case.json` | 仍读方案材料并生成默认检查表；结论信息不足或按材料保守判定 |
| `case.json` 损坏 | 写 `status=input_error` 的降级结果，保留 canonical 字段与不确定性 |
| 无资源清单 | 设备/材料/样本判 uncertain，不默认已具备 |
| 无 `output_contract` | 仍输出全部 canonical 字段；`contract.required_fields` 为空 |
| 输出目录不可写 | 退出码仍为 0，错误写 stderr，不崩溃 |

## 自检清单

1. `result.json` 含 `case_id/status/checklist/findings/verdict_summary/resources/estimates/conflicts/missing_info/evidence/uncertainty/run_log`。
2. `output_contract` 的每个键都在结果顶层；别名映射记录在 `contract`，未知键记录在 `contract_extras`。
3. 每条 finding 有 locator + quote，且 `verified=true`。
4. `counts.total == len(checklist)`，结论与计数规则一致。
5. 每个非 satisfied 项都有 `required_condition`。
6. 时间/样本有明确数字时才有 total，且必须有 `formula`。
7. 无 `__pycache__`、无网络、无第三方库、输出确定。

## Agent 执行步骤

1. 运行入口：

   ```bash
   python /skills/weekly-skill/scripts/sk_entry.py --input /input --work /app/work --out /app/output
   ```

2. 打开 `/app/output/result.json`，逐条读取 `findings`。
3. 对每条 finding：
   - 按 `evidence.locator` 回到输入文件（行号/表格行/JSON Pointer）定位；
   - 确认 `evidence.quote` 是连续原文；若不一致，修正或标记 `verified=false` 并在 `uncertainty` 说明；
   - 复核 `verdict`、`severity`、`required_condition` 是否与原文一致。
4. 核对 `verdict_summary` 与 `findings`：计数、结论口径必须一致；有 blocker 未满足时必须为“不可行”。
5. 核对 `estimates.time.formula` 与 `estimates.samples.formula` 只使用输入明示数字。
6. 将人工复核结论写入 `/app/output/run-review.md`（脚本已生成基础版，可在其上补充“已人工核对/修正”记录），保留逐项 locator 与 quote。
7. 最后再确认 `/app/output/result.json` 与 `/app/output/run-review.md` 均存在且可解析。
