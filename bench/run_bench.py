#!/usr/bin/env python3
"""Deterministic benchmark: checklist skill vs. naive keyword baseline.

Standard library only. For every directory under bench/cases, run
scripts/run_skill.py in an isolated temporary directory, compare its findings
against bench/gold, and compute the same metrics for a keyword-only baseline.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
ROOT = BENCH_DIR.parent
CASES_DIR = BENCH_DIR / "cases"
GOLD_DIR = BENCH_DIR / "gold"
RUN_SKILL = ROOT / "scripts" / "run_skill.py"

BASELINE_KEYWORDS = ("缺失", "未提供", "不设", "未设", "未附", "超过")
SENTENCE_SPLIT_RE = re.compile(r"[。！？；;\n]+")
BASELINE_CONCLUSION = "可行"


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_text(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as handle:
        return handle.read()


def category_set(findings):
    return {str(item.get("category")) for item in findings if item.get("category")}


def run_skill(case_dir):
    """Run the real entry point; return its parsed result.json."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    with tempfile.TemporaryDirectory(prefix="bench-run-") as tmp:
        tmpdir = Path(tmp)
        out_dir = tmpdir / "out"
        work_dir = tmpdir / "work"
        command = [
            sys.executable,
            str(RUN_SKILL),
            "--input", str(case_dir),
            "--work", str(work_dir),
            "--out", str(out_dir),
        ]
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        if completed.returncode != 0:
            raise RuntimeError("run_skill exited %d: %s" %
                               (completed.returncode, completed.stderr.strip()[:400]))
        result_path = out_dir / "result.json"
        if not result_path.is_file():
            raise RuntimeError("run_skill produced no result.json")
        return load_json(result_path)


def guess_category(sentence):
    """Naive keyword-to-category guess used only by the baseline."""
    if any(word in sentence for word in ("伦理", "审批", "批件", "IRB", "IACUC", "知情同意", "备案")):
        return "伦理与安全"
    if any(word in sentence for word in ("对照", "control")):
        return "对照组"
    if any(word in sentence for word in ("样本", "受试", "入组", "纳入", "动物", "小鼠", "大鼠")):
        return "样本"
    if any(word in sentence for word in ("温度", "流速", "参数", "超过", "超窗", "范围")):
        return "参数范围"
    if any(word in sentence for word in ("设备", "仪器")):
        return "设备"
    if any(word in sentence for word in ("材料", "试剂", "耗材", "库存", "货期", "采购", "外协")):
        return "材料"
    if any(word in sentence for word in ("时间", "时长", "排期", "小时")):
        return "时间"
    if any(word in sentence for word in ("风险", "异常", "故障", "应急")):
        return "风险与异常"
    if any(word in sentence for word in ("假设", "变量", "终点")):
        return "假设与变量"
    return "未分类"


def baseline_findings(protocol_text):
    """Keyword-only baseline: sentences hit by fixed keywords, no cross-checking."""
    findings = []
    seen = set()
    for raw in SENTENCE_SPLIT_RE.split(protocol_text):
        sentence = raw.strip()
        if not sentence:
            continue
        if not any(keyword in sentence for keyword in BASELINE_KEYWORDS):
            continue
        category = guess_category(sentence)
        key = (category, sentence)
        if key in seen:
            continue
        seen.add(key)
        findings.append({
            "category": category,
            "sentence": sentence,
            "verified": False,
            "reason": "keyword-only baseline; no inventory, parameter-domain or ethics check",
        })
    return findings


def score(predictions, expected_categories, conclusion, expected_conclusion,
          findings):
    matched = predictions & expected_categories
    false_positives = predictions - expected_categories
    missed = expected_categories - predictions
    verified_matched = 0
    for category in matched:
        for item in findings:
            if item.get("category") != category:
                continue
            if (item.get("evidence") or {}).get("verified") is True:
                verified_matched += 1
                break
    return {
        "predictions": sorted(predictions),
        "matched": sorted(matched),
        "false_positives": sorted(false_positives),
        "missed": sorted(missed),
        "true_positive_categories": len(matched),
        "false_positive_categories": len(false_positives),
        "false_negative_categories": len(missed),
        "conclusion": conclusion,
        "conclusion_match": conclusion == expected_conclusion,
        "verified_findings": verified_matched,
        "unresolved_gaps": len(missed),
    }


def aggregate(rows, key):
    tp = sum(row[key]["true_positive_categories"] for row in rows)
    fp = sum(row[key]["false_positive_categories"] for row in rows)
    fn = sum(row[key]["false_negative_categories"] for row in rows)
    recall = round(tp / float(tp + fn), 3) if (tp + fn) else 0.0
    precision = round(tp / float(tp + fp), 3) if (tp + fp) else 0.0
    conclusion_hits = sum(1 for row in rows if row[key]["conclusion_match"])
    accuracy = round(conclusion_hits / float(len(rows)), 3) if rows else 0.0
    return {
        "cases": len(rows),
        "true_positive_categories": tp,
        "false_positive_categories": fp,
        "false_negative_categories": fn,
        "category_recall": recall,
        "category_precision": precision,
        "conclusion_accuracy": accuracy,
        "verified_findings": sum(row[key]["verified_findings"] for row in rows),
        "unresolved_gaps": sum(row[key]["unresolved_gaps"] for row in rows),
    }


def evaluate_case(case_dir):
    name = case_dir.name
    gold_path = GOLD_DIR / (name + ".json")
    if not gold_path.is_file():
        raise RuntimeError("missing gold file for case: %s" % name)
    gold = load_json(gold_path)
    case_meta = load_json(case_dir / "case.json")
    if case_meta.get("case_id") != gold.get("case_id"):
        raise RuntimeError("case_id mismatch between case.json and gold: %s" % name)
    expected_categories = {item["category"] for item in gold.get("expected_findings", [])}
    if not expected_categories:
        raise RuntimeError("gold has no expected_findings: %s" % name)
    expected_conclusion = gold.get("expected_conclusion")

    result = run_skill(case_dir)
    skill_findings = result.get("findings") or []
    skill_predictions = category_set(skill_findings)
    skill = score(skill_predictions, expected_categories, result.get("conclusion"),
                  expected_conclusion, skill_findings)

    protocol_path = case_dir / "protocol.md"
    protocol_text = read_text(protocol_path) if protocol_path.is_file() else ""
    baseline_items = baseline_findings(protocol_text)
    baseline_predictions = category_set(baseline_items)
    baseline = score(baseline_predictions, expected_categories, BASELINE_CONCLUSION,
                     expected_conclusion, baseline_items)

    return {
        "case_id": gold.get("case_id"),
        "case_dir": "bench/cases/" + name,
        "expected_conclusion": expected_conclusion,
        "expected_categories": sorted(expected_categories),
        "skill": skill,
        "baseline": baseline,
    }


def render_report(rows, summary):
    lines = []
    lines.append("# 基准报告：实验方案审查技能 vs 朴素关键词基线")
    lines.append("")
    lines.append("本报告由 `bench/run_bench.py` 生成，纯标准库、离线、确定性；不含时间戳与绝对路径。")
    lines.append("")
    lines.append("## 1. 对照协议")
    lines.append("")
    lines.append("- 输入：`bench/cases/<name>/{case.json,protocol.md,inventory.csv}`。")
    lines.append("- 金标准：`bench/gold/<name>.json`，每个案例只植入一个可由原文/清单/参数域唯一判定的缺口。")
    lines.append("- 技能调用：`python scripts/run_skill.py --input bench/cases/<name> --work <tmp>/work --out <tmp>`。")
    lines.append("- 对照条件：同一案例、同一输入文件；技能与基线各跑一次，评价只读 `result.json.findings`。")
    lines.append("- 基线：只在 `protocol.md` 中按固定关键词切句，命中句直接当作 finding，不核对库存、参数域或伦理，结论恒为“可行”。")
    lines.append("")
    lines.append("## 2. 汇总指标")
    lines.append("")
    lines.append("| 指标 | 技能 | 基线 | 差值（技能-基线） |")
    lines.append("|---|---:|---:|---:|")
    for label, key in (
        ("finding 类别召回", "category_recall"),
        ("finding 类别精确", "category_precision"),
        ("结论一致性", "conclusion_accuracy"),
        ("可验证定位条目数", "verified_findings"),
        ("未解决缺口数", "unresolved_gaps"),
    ):
        skill_value = summary["skill"][key]
        baseline_value = summary["baseline"][key]
        delta = round(skill_value - baseline_value, 3)
        lines.append("| %s | %s | %s | %s |" % (label, skill_value, baseline_value, delta))
    lines.append("")
    lines.append("汇总口径：按案例对“finding 类别集合”计 TP/FP/FN；精确率在无预测且存在期望缺口时记 0；"
                 "可验证定位条目数只统计命中类别的 finding 中 `evidence.verified=true` 的条目。")
    lines.append("")
    lines.append("## 3. 分案例结果")
    lines.append("")
    lines.append("| 案例 | 金标准结论 | 技能结论 | 基线结论 | 期望类别 | 技能预测 | 基线预测 | 技能可验证 | 技能未解决 |")
    lines.append("|---|---|---|---|---|---|---|---:|---:|")
    for row in rows:
        expected = "、".join(row["expected_categories"])
        skill_predicted = "、".join(row["skill"]["predictions"]) or "—"
        baseline_predicted = "、".join(row["baseline"]["predictions"]) or "—"
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %d | %d |" % (
            row["case_dir"].split("/")[-1],
            row["expected_conclusion"],
            row["skill"]["conclusion"],
            row["baseline"]["conclusion"],
            expected,
            skill_predicted,
            baseline_predicted,
            row["skill"]["verified_findings"],
            row["skill"]["unresolved_gaps"],
        ))
    lines.append("")
    lines.append("## 4. 基线定义")
    lines.append("")
    lines.append("- 关键词：`%s`。" % "、".join(BASELINE_KEYWORDS))
    lines.append("- 切句：按 `。！？；;` 与换行切分，保留命中句原文。")
    lines.append("- 类别：按句内关键词做一次朴素映射（伦理/对照/样本/参数/设备/材料/时间/风险/假设），"
                 "不读取 `inventory.csv`、`case.json` 的参数域或伦理字段。")
    lines.append("- 定位：不产生可回读的 locator/quote，故可验证定位条目数恒为 0。")
    lines.append("- 结论：不使用检查项计数，恒输出“可行”。")
    lines.append("")
    lines.append("## 5. 复现")
    lines.append("")
    lines.append("```")
    lines.append("python bench/run_bench.py")
    lines.append("```")
    lines.append("")
    lines.append("## 6. 已知边界")
    lines.append("")
    lines.append("- 案例为合成材料，只用于验证“可定位判定 + 公平对照”，不代表真实实验方案。")
    lines.append("- 基线故意不实现库存、参数域、伦理核对，不能外推为其他工具的能力上限。")
    lines.append("- 指标按类别集合计，不评价同类别内多条 finding 的措辞质量；措辞质量需人工复核。")
    lines.append("- 技能结论必须由检查项计数规则唯一决定；若案例出现歧义，应修案例而不是改金标准。")
    lines.append("")
    return "\n".join(lines)


def main():
    if not RUN_SKILL.is_file():
        raise SystemExit("missing entry point: scripts/run_skill.py")
    case_dirs = sorted(path for path in CASES_DIR.iterdir() if path.is_dir())
    if not case_dirs:
        raise SystemExit("no cases found under bench/cases")

    rows = [evaluate_case(case_dir) for case_dir in case_dirs]
    summary = {
        "skill": aggregate(rows, "skill"),
        "baseline": aggregate(rows, "baseline"),
    }
    summary["delta"] = {
        "category_recall": round(summary["skill"]["category_recall"] - summary["baseline"]["category_recall"], 3),
        "category_precision": round(summary["skill"]["category_precision"] - summary["baseline"]["category_precision"], 3),
        "conclusion_accuracy": round(summary["skill"]["conclusion_accuracy"] - summary["baseline"]["conclusion_accuracy"], 3),
        "verified_findings": summary["skill"]["verified_findings"] - summary["baseline"]["verified_findings"],
        "unresolved_gaps": summary["baseline"]["unresolved_gaps"] - summary["skill"]["unresolved_gaps"],
    }

    metrics = {
        "benchmark": "experimental-plan-checklist-review",
        "baseline": {
            "keywords": list(BASELINE_KEYWORDS),
            "conclusion_rule": BASELINE_CONCLUSION,
            "cross_checks": "none",
        },
        "cases": rows,
        "summary": summary,
        "definitions": {
            "category_recall": "TP 类别数 / (TP + FN) 类别数；按案例汇总。",
            "category_precision": "TP 类别数 / (TP + FP) 类别数；无预测且存在期望缺口时记 0。",
            "conclusion_accuracy": "结论与金标准一致的案例数 / 案例总数。",
            "verified_findings": "命中类别的 finding 中 evidence.verified=true 的条目数。",
            "unresolved_gaps": "金标准中未被该系统命中的缺口类别数。",
            "gold_rule": "每个案例只有一个非 satisfied 检查项，且其结论由技能计数规则唯一决定。",
        },
    }

    gates = {
        "recall_strictly_better": summary["skill"]["category_recall"] > summary["baseline"]["category_recall"],
        "conclusion_strictly_better": summary["skill"]["conclusion_accuracy"] > summary["baseline"]["conclusion_accuracy"],
    }
    metrics["gates"] = gates

    metrics_path = BENCH_DIR / "bench_metrics.json"
    with open(metrics_path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")

    report_path = BENCH_DIR / "bench_report.md"
    with open(report_path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(render_report(rows, summary))
        handle.write("\n")

    if not all(gates.values()):
        sys.stderr.write("benchmark gates failed: %s\n" % json.dumps(gates, sort_keys=True))
        return 1

    sys.stdout.write(json.dumps({
        "cases": len(rows),
        "skill_recall": summary["skill"]["category_recall"],
        "baseline_recall": summary["baseline"]["category_recall"],
        "skill_conclusion_accuracy": summary["skill"]["conclusion_accuracy"],
        "baseline_conclusion_accuracy": summary["baseline"]["conclusion_accuracy"],
        "metrics": "bench/bench_metrics.json",
        "report": "bench/bench_report.md",
    }, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
