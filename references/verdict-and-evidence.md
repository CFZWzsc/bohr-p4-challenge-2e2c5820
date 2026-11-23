# 结论口径与证据定位

## 判定取值

| verdict | 含义 | 使用条件 |
|---|---|---|
| satisfied | 满足 | 有原文/清单行直接支持，且无相反证据 |
| partial | 部分满足 | 方向正确但缺关键要素（如只写对照未分阴性/阳性、资源需采购） |
| missing | 缺失 | 应写的章节/参数/记录未出现；不能把未写当作满足 |
| conflict | 冲突 | 原文之间、原文与清单/参数域/伦理状态互相矛盾 |
| uncertain | 不确定 | 输入缺清单、缺参数域、单位无法换算、状态未声明等 |

## 结论

- **可行**：9 项全部 satisfied。
- **有条件可行**：无 blocker 未满足，但至少 1 项 partial/missing/conflict/uncertain；必须输出 `required_conditions`。
- **不可行**：至少 1 项 blocker 未满足（伦理被拒/未获批、关键资源不具备、时长或样本缺口超过 50%）。
- **信息不足**：没有任何可读方案材料；不强行给出可行/不可行。

计数必须与 `checklist` 逐项一致：`counts.total == len(checklist)`，`findings` 等于非 satisfied 条目。

## 证据定位格式

统一写成 `<相对文件>#<片段>`：

- 章节/行：`protocol.md#L42` 或 `protocol.md#L28-L31`。
- 表格行：`inventory.csv#row=4`（row 为文件实际行号，含表头）。
- JSON 参数：`case.json#/parameter_domains/column_temp`。
- 文档条款：`case.json#/documents/0/clauses/0/text`。

每条 finding 必须同时有 `locator` 与 `quote`：

- `quote` 必须是该定位处连续原文的可搜索片段，不能改写、拼接或加省略号。
- 入口脚本会把 `quote` 回读到输入文件；`verified=false` 的 finding 不能算完成。
- 缺章节类 finding 用“absence evidence”：定位到方案首个可读行，并在 rationale 写明“检索词未命中”，不能伪造引文。

## 严重度

| severity | 含义 | 典型例子 |
|---|---|---|
| blocker | 不解决不能开工 | 伦理被拒、关键设备不具备、样本缺口 > 50% |
| major | 影响结论或需补条件 | 无对照、参数越界、样本不足、时间超窗 |
| minor | 影响可读性/可复现性 | 单位未写、步骤描述不清 |
| info | 提示 | 建议补充版本号、责任人 |
