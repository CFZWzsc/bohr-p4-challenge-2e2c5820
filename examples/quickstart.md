# Demo case 快速开始

## 目录

```
examples/demo-case/
  case.json      # 案例元数据、output_contract（10 键）、参数域、伦理、SOP/手册条款
  protocol.md    # 合成方案，含 3 个已知缺口
  inventory.csv  # 设备/材料/样本库存
```

## 运行

在 submission 根目录执行：

```bash
python scripts/sk_entry.py --input examples/demo-case --work /tmp/work --out /tmp/out
```

或使用 thin wrapper：

```bash
python scripts/run_skill.py --input examples/demo-case --work /tmp/work --out /tmp/out
```

## 预期

- 退出码 0。
- `result.json` 中 `status=answered`、`conclusion=有条件可行`。
- `counts = {satisfied: 6, partial: 0, missing: 1, conflict: 2, uncertain: 0, total: 9}`。
- 3 条 finding，分别对应三个已知缺口：
  1. `protocol.md#L13`：明确写“不设对照组” → 对照组/缺失。
  2. `protocol.md#L23` + `inventory.csv#row=6`：12×1×3=36，库存 24 → 样本/冲突。
  3. `protocol.md#L42` + `case.json#/parameter_domains/column_temp`：柱温 45 °C > 40 °C → 参数/冲突。
- `evidence` 全部 `verified=true`；`contract.required_fields` 10 个键全部存在于结果顶层。

## 说明

这是合成案例，仅用于验证入口、定位与契约映射；不对应真实实验方案。实际案例请把 `--input` 指向 `/input`。
