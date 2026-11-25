# Bench 说明：技能 vs 朴素关键词基线

本目录提供可复现的公平对照，用于核验“实验方案审查”技能是否真的依赖跨文件核对（库存、参数域、伦理状态），而不是只做关键词匹配。全部为合成案例，不含真实个人或实验数据。

## 1. 目录结构

```
bench/
  cases/<name>/
    case.json       # 案例元数据、参数域、伦理/安全状态、文档条款
    protocol.md     # 方案正文，含唯一可定位缺口
    inventory.csv   # 设备/材料/样本库存
  gold/<name>.json  # {case_id, expected_findings, expected_conclusion, notes}
  run_bench.py      # 纯标准库、确定性评测入口
  bench_metrics.json
  bench_report.md
```

## 2. 案例与植入缺口

| 案例 | 唯一缺口 | 技能判定 | 金标准结论 |
|---|---|---|---|
| `ethics-pending-cell-assay` | 人体 PBMC 样本，伦理状态为“审批中”，批件未下发 | CHK-07 伦理与安全 partial，blocker 未满足 | 不可行 |
| `sample-shortage-qpcr` | 需求 10×3×3=90 份，库存 60 份，缺口 33.3%（≤50%） | CHK-05 样本 conflict，major | 有条件可行 |
| `column-temp-over-limit-gc` | 柱温 250 °C，超出 `[200, 240] °C` 参数域 | CHK-08 参数范围 conflict，major | 有条件可行 |

每个案例的其余 8 个检查项都按原文和清单可判 `satisfied`，因此结论由技能计数规则唯一决定；若技能未命中该缺口，应先检查案例是否有歧义，而不是修改金标准。

## 3. 公平对照协议

1. 技能与基线读取完全相同的 `bench/cases/<name>/` 三个文件。
2. 技能按真实入口执行：
   `python scripts/run_skill.py --input bench/cases/<name> --work <tmp>/work --out <tmp>`。
3. 每次运行使用独立的 `tempfile.TemporaryDirectory()`，并设置 `PYTHONDONTWRITEBYTECODE=1`，避免缓存与跨案例污染。
4. 评价只读技能输出 `result.json` 的 `findings` 与 `conclusion`；不读取 `run-review.md` 等展示层文件。
5. 金标准在评测前固定；技能结论必须与金标准一致，否则视为失败并修正案例。
6. 基线同样是确定性实现，不联网、不读取额外信息。

## 4. 基线定义

- 只读取 `protocol.md`。
- 按 `。！？；;` 与换行切句。
- 命中固定关键词 `缺失 / 未提供 / 不设 / 未设 / 未附 / 超过` 的句子直接当作 finding。
- 类别仅按句内关键词做一次朴素映射，不读取 `inventory.csv`、`case.json` 的参数域或伦理字段，也不做定位回读。
- 结论恒为“可行”。

## 5. 指标定义

按案例比较“finding 类别集合”：

- TP：预测类别 ∩ 期望类别；FP：预测类别 − 期望类别；FN：期望类别 − 预测类别。
- `category_recall = ΣTP / (ΣTP + ΣFN)`。
- `category_precision = ΣTP / (ΣTP + ΣFP)`；无预测且存在期望缺口时记 0，避免空集精确率虚高。
- `conclusion_accuracy = 结论与金标准一致的案例数 / 案例总数`。
- `verified_findings`：命中类别的 finding 中 `evidence.verified=true` 的条目数。基线不产生可回读定位，因此恒为 0。
- `unresolved_gaps = ΣFN`，即金标准缺口未被该系统发现的数量。

## 6. 复现

在 submission 根目录执行：

```bash
python bench/run_bench.py
```

退出码 0 表示全部案例跑通且两项门槛成立：

- 技能类别召回严格高于基线；
- 技能结论一致性严格高于基线。

脚本会重写 `bench/bench_metrics.json`（`indent=2, sort_keys=True`）与 `bench/bench_report.md`。两次运行应字节一致。

## 7. 已知边界

- 案例为合成材料，只验证“可定位判定 + 公平对照”，不能替代真实方案的人工复核。
- 基线故意不实现库存、参数域、伦理核对，其结果不代表其他工具或人工审查的能力上限。
- 指标按类别集合计，不评价同类别内多条 finding 的措辞质量；措辞与建议仍需人工复核。
- 技能离线运行，不查供应商价格、货期或最新法规。
