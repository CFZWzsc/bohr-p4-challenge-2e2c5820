#!/usr/bin/env python3
"""Checklist-based experimental-protocol feasibility review.

Reads real case material from --input, reviews each checklist item against
protocol sections / parameter rows / inventory rows, and writes contract-complete
result.json plus run-review.md.

Standard library only. Offline. Deterministic. No private paths.
"""

import argparse
import csv
import hashlib
import json
import os
import re
import sys

VERSION = "2.0.0"
RULES_VERSION = "checklist-review-v2"

STATUS_VALUES = ("answered", "partial", "insufficient_evidence", "input_error")
VERDICT_VALUES = ("satisfied", "partial", "missing", "conflict", "uncertain")
VERDICT_ZH = {
    "satisfied": "满足",
    "partial": "部分满足",
    "missing": "缺失",
    "conflict": "冲突",
    "uncertain": "不确定",
}
SEVERITY_ZH = {"blocker": "阻断", "major": "重要", "minor": "次要", "info": "提示"}

# Contract-key aliases. Multiple contract keys may share one canonical field;
# the fill step writes each contract key explicitly, so no key is ever dropped.
ALIASES = {
    "case_id": "case_id",
    "status": "status",
    "status_reason": "status_reason",
    "items": "checklist",
    "item_list": "checklist",
    "checklist": "checklist",
    "checks": "checklist",
    "review_items": "checklist",
    "review_checklist": "checklist",
    "issues": "findings",
    "risks": "findings",
    "findings": "findings",
    "problems": "findings",
    "defects": "findings",
    "gaps": "findings",
    "conclusion": "conclusion",
    "summary": "conclusion",
    "verdict": "conclusion",
    "recommendation": "conclusion",
    "overall": "conclusion",
    "resources": "resources",
    "conditions": "resources",
    "resource_status": "resources",
    "inventory": "resources",
    "equipment": "resources",
    "citations": "evidence",
    "evidence": "evidence",
    "sources": "evidence",
    "references": "evidence",
    "anchors": "evidence",
    "quotes": "evidence",
    "notes": "uncertainty",
    "uncertainty": "uncertainty",
    "uncertainties": "uncertainty",
    "limitations": "uncertainty",
    "open_questions": "uncertainty",
    "state": "verdict_summary",
    "stats": "verdict_summary",
    "statistics": "verdict_summary",
    "counts": "verdict_summary",
    "verdict_summary": "verdict_summary",
    "estimates": "estimates",
    "time": "estimates",
    "sample_estimates": "estimates",
    "conflicts": "conflicts",
    "contradictions": "conflicts",
    "missing_info": "missing_info",
    "missing": "missing_info",
    "missing_information": "missing_info",
    "run_log": "run_log",
    "log": "run_log",
    "trace": "run_log",
    "required_conditions": "required_conditions",
    "change_log": "run_log",
}

DEFAULT_CHECKLIST = [
    {
        "item_id": "CHK-01",
        "category": "假设与变量",
        "question": "方案是否给出可检验假设，并绑定自变量、因变量与主要终点？",
        "severity": "major",
        "basis": "方法学规范/SOP",
        "rule": "假设与可测量变量同时出现才判满足；仅出现其一判部分满足；均未出现判缺失。",
    },
    {
        "item_id": "CHK-02",
        "category": "对照组",
        "question": "方案是否设置对照组，并说明阴性/阳性对照与分组方式？",
        "severity": "major",
        "basis": "SOP/方法学规范",
        "rule": "明确写出不设对照判缺失；阴性、阳性对照均写明判满足；只写对照未分层判部分满足。",
    },
    {
        "item_id": "CHK-03",
        "category": "设备",
        "question": "方案提到的设备型号/精度是否在现有条件清单中且可用？",
        "severity": "major",
        "basis": "设备清单/设备手册",
        "rule": "逐项匹配设备清单；已具备判满足，可外协或需采购判部分满足，不具备判冲突，清单缺失判不确定。",
    },
    {
        "item_id": "CHK-04",
        "category": "材料",
        "question": "方案所需耗材、试剂、色谱柱等的规格与库存是否满足？",
        "severity": "major",
        "basis": "材料清单/采购记录",
        "rule": "逐行匹配材料清单与库存数量；缺行或规格不符不得默认满足。",
    },
    {
        "item_id": "CHK-05",
        "category": "样本",
        "question": "样本来源、数量、保存条件与分组重复数是否够用？",
        "severity": "major",
        "basis": "样本清单/伦理批件",
        "rule": "仅用方案明示的样本数、组数、重复数计算需求；可得量不足判冲突，数字缺失判不确定。",
    },
    {
        "item_id": "CHK-06",
        "category": "时间",
        "question": "按步骤拆出的设备占用、人工操作与等待周期是否在时间窗内？",
        "severity": "major",
        "basis": "排期表/SOP",
        "rule": "仅汇总明示时长并写出算式；超过时间窗判冲突，无时间窗判不确定，无任何时长判缺失。",
    },
    {
        "item_id": "CHK-07",
        "category": "伦理与安全",
        "question": "涉及人体、动物、危险试剂或个人数据时，审批与安全状态是否明确？",
        "severity": "blocker",
        "basis": "伦理规范/安全制度",
        "rule": "触发伦理事项且已批准判满足；审批中判部分满足；未声明判不确定；被拒判冲突。",
    },
    {
        "item_id": "CHK-08",
        "category": "参数范围",
        "question": "方案参数值是否落在案例给出的有限参数域或设备/安全边界内？",
        "severity": "major",
        "basis": "设备手册/SOP/参数域",
        "rule": "逐参数比较上下限或允许值；越界判冲突，无参数域判不确定，单位不一致先换算或记冲突。",
    },
    {
        "item_id": "CHK-09",
        "category": "风险与异常",
        "question": "方案是否列出故障、批次差异、样本不足、参数越界等风险及降级路径？",
        "severity": "major",
        "basis": "风险管理制度/SOP",
        "rule": "风险项与可执行降级/转人工路径同时出现判满足；只有风险清单判部分满足；均无判缺失。",
    },
]

_CHUNK2 = "@@CHUNK2@@"


# ---------------------------------------------------------------------------
# Generic helpers
# ---------------------------------------------------------------------------

def norm_space(value):
    if not isinstance(value, str):
        value = "" if value is None else str(value)
    return re.sub(r"\s+", " ", value).strip()


def norm_key(value):
    value = norm_space(value).lower()
    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def findable_quote(value, limit=260):
    text = norm_space(value)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", "；", ";", ". ", "，", ","):
        idx = cut.rfind(sep)
        if idx >= limit * 0.5:
            cut = cut[: idx + 1]
            break
    return cut.strip()


def read_text(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        return fh.read()


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def write_text(path, text):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def as_number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def first_number(mapping, names):
    if isinstance(mapping, dict):
        for name in names:
            if name in mapping:
                number = as_number(mapping[name])
                if number is not None:
                    return number
    return None


def walk_json(obj, pointer=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")
            yield child, value
            for item in walk_json(value, child):
                yield item
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            child = pointer + "/" + str(index)
            yield child, value
            for item in walk_json(value, child):
                yield item


def json_pointer_get(data, pointer):
    node = data
    if not pointer:
        return node
    for raw in pointer.strip("/").split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, list):
            node = node[int(token)]
        elif isinstance(node, dict):
            node = node[token]
        else:
            raise KeyError(pointer)
    return node


def extract_contract(case):
    if not isinstance(case, dict):
        return {}
    raw = case.get("output_contract")
    out = {}
    if isinstance(raw, dict):
        for key, value in raw.items():
            out[str(key)] = "" if value is None else str(value)
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                out[item] = ""
            elif isinstance(item, dict):
                key = item.get("name") or item.get("key") or item.get("field")
                if key:
                    out[str(key)] = str(item.get("description") or item.get("type") or "")
    return out


def alias_of(key):
    return ALIASES.get(str(key))


def placeholder_for(key):
    lowered = str(key).lower()
    if re.search(r"(s|list|records|entries|items|array|findings|notes|citations)$", lowered):
        return []
    if re.search(r"(map|dict|index|catalog|lookup|by_|state|stats|summary|resources|estimates|counts)$", lowered):
        return {}
    if re.search(r"(conclusion|verdict|status|reason|text|string|message)$", lowered):
        return ""
    return None


def normalize_status(value):
    raw = norm_space(value).lower()
    if raw in STATUS_VALUES:
        return raw
    mapping = {
        "success": "answered", "ok": "answered", "complete": "answered",
        "completed": "answered", "done": "answered",
        "failed": "input_error", "error": "input_error", "failure": "input_error",
        "unsupported": "insufficient_evidence", "unknown": "insufficient_evidence",
        "no_evidence": "insufficient_evidence", "not_found": "insufficient_evidence",
        "incomplete": "partial", "degraded": "partial", "skipped": "partial",
    }
    return mapping.get(raw, "partial")


def infer_contract_value(key, result):
    """Best-effort lookup for a contract key that has no explicit alias."""
    lowered = str(key).lower()
    candidates = [
        lowered,
        lowered.replace("_", ""),
        lowered.replace("_", " "),
    ]
    for name, value in result.items():
        flat = str(name).lower().replace("_", "")
        if flat in [c.replace("_", "").replace(" ", "") for c in candidates]:
            if value not in (None, [], {}):
                return value, name
    token_map = {
        "review": "checklist", "check": "checklist", "finding": "findings",
        "issue": "findings", "risk": "findings", "resource": "resources",
        "conclusion": "conclusion", "verdict": "conclusion", "summary": "conclusion",
        "evidence": "evidence", "citation": "evidence", "source": "evidence",
        "note": "uncertainty", "uncertain": "uncertainty", "limit": "uncertainty",
        "stat": "verdict_summary", "count": "verdict_summary", "state": "verdict_summary",
        "estimate": "estimates", "time": "estimates", "sample": "estimates",
        "conflict": "conflicts", "missing": "missing_info", "log": "run_log",
        "condition": "resources",
    }
    for token, canonical in token_map.items():
        if token in lowered and result.get(canonical) not in (None, [], {}):
            return result[canonical], canonical
    return None, None


def fill_contract(result, case):
    """Write EVERY output_contract key at top level, preserving canonical fields.

    Aliased keys duplicate their canonical value. Unknown keys get a shape-aware
    best effort, and are recorded in contract_extras + contract.unmapped_fields.
    """
    contract = extract_contract(case)
    mapped, aliased, best_effort, unmapped = {}, [], {}, []
    extras = {}

    for key in contract:
        if key in ("case_id", "status"):
            mapped[key] = key
            continue
        if key in result and result.get(key) is not None:
            mapped[key] = key
            continue
        canonical = alias_of(key)
        if canonical and canonical in result:
            result[key] = result[canonical]
            mapped[key] = canonical
            if canonical != key:
                aliased.append("%s -> %s" % (key, canonical))
            continue
        inferred, source = infer_contract_value(key, result)
        if inferred is not None:
            result[key] = inferred
            mapped[key] = source
            best_effort[key] = source
            extras[key] = inferred
            continue
        result[key] = placeholder_for(key)
        unmapped.append(key)
        extras[key] = result[key]

    result["case_id"] = str(case.get("case_id") or result.get("case_id") or "")
    result["status"] = normalize_status(result.get("status"))
    result["contract"] = {
        "required_fields": sorted(contract.keys()),
        "mapped": mapped,
        "aliased_applied": aliased,
        "best_effort": best_effort,
        "unmapped_fields": unmapped,
    }
    result["contract_extras"] = extras
    return result


def template_checklist():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "checklist.json")
    path = os.path.abspath(path)
    if os.path.isfile(path):
        try:
            data = load_json(path)
            items = data.get("items") if isinstance(data, dict) else data
            if isinstance(items, list) and items:
                out = []
                for item in items:
                    if isinstance(item, dict) and item.get("question"):
                        out.append(dict(item))
                if out:
                    return out, "assets/checklist.json"
        except (OSError, ValueError):
            pass
    return [dict(item) for item in DEFAULT_CHECKLIST], "embedded-default"


# ---------------------------------------------------------------------------
# Input discovery and document parsing
# ---------------------------------------------------------------------------

TEXT_EXTS = {".md", ".markdown", ".txt", ".csv", ".tsv", ".json", ".jsonl"}

HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
BOLD_HEADING_RE = re.compile(r"^\s*\*\*(.+?)\*\*\s*$")
CN_HEADING_RE = re.compile(r"^\s*([一二三四五六七八九十]+)[、.]\s*(.+?)\s*$")
ARABIC_HEADING_RE = re.compile(r"^\s*(\d{1,2})[、.]\s+(.+?)\s*$")

CASE_CONTENT_KEYS = (
    "protocol", "plans", "candidate_plans", "plan_versions", "versions",
    "design", "experimental_design", "experiment", "method", "methods",
    "procedure", "procedures", "steps", "protocol_text", "manuscript",
    "material_text", "content", "background", "goal", "hypothesis",
)


def list_files(root):
    found = []
    if not root or not os.path.isdir(root):
        return found
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", ".git"))
        for name in sorted(files):
            found.append(os.path.join(base, name))
    return found


def relpath(path, root):
    try:
        return os.path.relpath(path, root).replace("\\", "/")
    except ValueError:
        return os.path.basename(path)


def find_case_file(input_dir):
    direct = os.path.join(input_dir, "case.json")
    if os.path.isfile(direct):
        return direct
    for path in list_files(input_dir):
        if os.path.basename(path).lower() == "case.json":
            return path
    return ""


def split_sections(text, rel):
    lines = text.splitlines()
    marks = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        match = HEADING_RE.match(line)
        if match:
            marks.append((index, match.group(2).strip(), len(match.group(1))))
            continue
        match = BOLD_HEADING_RE.match(line)
        if match and len(match.group(1)) <= 80:
            marks.append((index, match.group(1).strip(), 2))
            continue
        match = CN_HEADING_RE.match(line)
        if match and len(match.group(2)) <= 60:
            marks.append((index, match.group(2).strip(), 2))
            continue
        match = ARABIC_HEADING_RE.match(line)
        if match and len(match.group(2)) <= 60 and not re.search(r"[:：]", match.group(2)):
            marks.append((index, match.group(2).strip(), 3))
    sections = []
    if not marks:
        sections.append({
            "section_id": rel + "#S1", "heading": "全文", "level": 1,
            "start_line": 1, "end_line": max(1, len(lines)), "lines": lines,
            "text": text, "doc": rel,
        })
        return sections
    if marks[0][0] > 0:
        body = "\n".join(lines[: marks[0][0]]).strip()
        if body:
            sections.append({
                "section_id": rel + "#S0", "heading": "前言", "level": 0,
                "start_line": 1, "end_line": marks[0][0], "lines": lines[: marks[0][0]],
                "text": body, "doc": rel,
            })
    for pos, (index, heading, level) in enumerate(marks):
        end = marks[pos + 1][0] if pos + 1 < len(marks) else len(lines)
        body = "\n".join(lines[index:end]).strip()
        sections.append({
            "section_id": rel + "#S" + str(pos + 1), "heading": heading, "level": level,
            "start_line": index + 1, "end_line": max(index + 1, end),
            "lines": lines[index:end], "text": body, "doc": rel,
        })
    return sections


def flatten_json_sections(data, rel, pointer="", depth=0):
    """Flatten JSON content into pointer-addressed sections with exact leaf text."""
    sections = []
    if depth > 8:
        return sections
    if isinstance(data, dict):
        for key, value in data.items():
            child = pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")
            sections.extend(flatten_json_sections(value, rel, child, depth + 1))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            child = pointer + "/" + str(index)
            sections.extend(flatten_json_sections(value, rel, child, depth + 1))
    elif isinstance(data, str):
        text = norm_space(data)
        if not text:
            return sections
        raw_lines = [line.strip() for line in data.splitlines() if line.strip()]
        if len(raw_lines) > 1:
            for index, line in enumerate(raw_lines):
                sections.append({
                    "section_id": rel + "#" + pointer + ":L%d" % index,
                    "heading": pointer or "(root)", "level": 9,
                    "start_line": None, "end_line": None,
                    "lines": [line], "text": line, "doc": rel,
                    "locator": rel + "#" + pointer, "json": True,
                })
        else:
            sections.append({
                "section_id": rel + "#" + pointer, "heading": pointer or "(root)",
                "level": 9, "start_line": None, "end_line": None,
                "lines": [text], "text": text, "doc": rel,
                "locator": rel + "#" + pointer, "json": True,
            })
    elif isinstance(data, (int, float, bool)):
        text = str(data)
        sections.append({
            "section_id": rel + "#" + pointer, "heading": pointer or "(root)",
            "level": 9, "start_line": None, "end_line": None,
            "lines": [text], "text": text, "doc": rel,
            "locator": rel + "#" + pointer, "json": True,
        })
    return sections


def load_csv_doc(path, rel):
    try:
        raw = read_text(path)
    except OSError:
        return None
    lines = raw.splitlines()
    rows = []
    try:
        reader = csv.reader(lines)
        for index, row in enumerate(reader):
            rows.append({"row": index + 1, "cells": row, "line": lines[index] if index < len(lines) else ""})
    except csv.Error:
        for index, line in enumerate(lines):
            rows.append({"row": index + 1, "cells": [part.strip() for part in line.split(",")], "line": line})
    sections = [{
        "section_id": rel + "#table", "heading": "表格 " + rel, "level": 1,
        "start_line": 1, "end_line": max(1, len(lines)), "lines": lines,
        "text": raw, "doc": rel, "rows": rows, "csv": True,
    }]
    return {"rel": rel, "path": path, "text": raw, "lines": lines, "sections": sections,
            "rows": rows, "csv": True}


def discover_inputs(input_dir):
    state = {
        "input_dir": input_dir,
        "case": {}, "case_path": "", "case_error": "", "case_sha256": None,
        "task_text": "", "docs": [], "files": [], "material_count": 0,
    }
    if not os.path.isdir(input_dir):
        state["case_error"] = "input_directory_not_found"
        return state
    case_path = find_case_file(input_dir)
    if case_path:
        state["case_path"] = case_path
        state["case_sha256"] = sha256_file(case_path)
        try:
            case = load_json(case_path)
            if isinstance(case, dict):
                state["case"] = case
            else:
                state["case_error"] = "case_root_not_object"
        except (OSError, ValueError) as exc:
            state["case_error"] = "case_load_failed: %s" % exc
    else:
        state["case_error"] = "case_file_not_found"

    files = list_files(input_dir)
    state["files"] = [relpath(path, input_dir) for path in files]
    material_files = []
    for path in files:
        base = os.path.basename(path)
        lower = base.lower()
        ext = os.path.splitext(path)[1].lower()
        if lower == "case.json":
            continue
        if lower in ("result.json", "run-review.md", "entry-error.log") or lower.endswith(".tmp"):
            continue
        if lower in ("task.md", "task.txt"):
            state["task_text"] = read_text(path)
            continue
        if ext not in TEXT_EXTS:
            continue
        if lower.startswith(".") or lower.endswith(".meta.json"):
            continue
        material_files.append(path)

    for path in material_files:
        rel = relpath(path, input_dir)
        ext = os.path.splitext(path)[1].lower()
        if ext in (".csv", ".tsv"):
            doc = load_csv_doc(path, rel)
            if doc:
                state["docs"].append(doc)
            continue
        try:
            text = read_text(path)
        except OSError:
            continue
        if ext in (".json", ".jsonl"):
            try:
                data = json.loads(text)
                sections = flatten_json_sections(data, rel)
                state["docs"].append({
                    "rel": rel, "path": path, "text": text,
                    "lines": text.splitlines(), "sections": sections,
                })
                continue
            except ValueError:
                pass
        state["docs"].append({
            "rel": rel, "path": path, "text": text,
            "lines": text.splitlines(), "sections": split_sections(text, rel),
        })

    case = state["case"]
    if isinstance(case, dict):
        for key in CASE_CONTENT_KEYS:
            if key not in case:
                continue
            value = case[key]
            if value in (None, "", [], {}):
                continue
            sections = flatten_json_sections(value, "case.json", "/" + key)
            if sections:
                state["docs"].append({
                    "rel": "case.json", "path": case_path,
                    "text": json.dumps(value, ensure_ascii=False),
                    "lines": [], "sections": sections, "embedded": True,
                })
                break
    state["material_count"] = len(state["docs"])
    return state


def protocol_docs(state):
    return [doc for doc in state.get("docs", []) if not doc.get("embedded") and not doc.get("csv")]


def iter_doc_lines(docs):
    for doc in docs:
        for section in doc.get("sections", []):
            if section.get("json"):
                text = section.get("text") or ""
                yield doc, section, 0, text
                continue
            for offset, line in enumerate(section.get("lines", [])):
                if line.strip():
                    yield doc, section, section.get("start_line", 1) + offset, line


def section_has(section, terms):
    blob = (section.get("heading") or "") + "\n" + (section.get("text") or "")
    return any(term.lower() in blob.lower() for term in terms)


def line_has(line, terms):
    lowered = line.lower()
    return any(term.lower() in lowered for term in terms)


def first_section(docs, terms):
    for doc in docs:
        for section in doc.get("sections", []):
            if section_has(section, terms):
                return doc, section
    return None, None


def first_line(docs, terms, section_terms=None):
    for doc, section, line_no, line in iter_doc_lines(docs):
        if section_terms and not section_has(section, section_terms):
            continue
        if line_has(line, terms):
            return doc, section, line_no, line
    return None, None, None, None


# ---------------------------------------------------------------------------
# Evidence and locator verification
# ---------------------------------------------------------------------------

class EvidencePool(object):
    def __init__(self, input_dir):
        self.input_dir = input_dir
        self.items = []
        self._seen = {}

    def add(self, locator, quote, source="", section="", kind="quote"):
        quote = findable_quote(quote)
        key = (locator, quote)
        if key in self._seen:
            return self._seen[key]
        item = {
            "id": "E%d" % (len(self.items) + 1),
            "locator": locator,
            "quote": quote,
            "source": source,
            "section": section,
            "kind": kind,
        }
        self._seen[key] = item
        self.items.append(item)
        return item

    def add_line(self, doc, line_no, section=None):
        if not doc:
            return None
        if not line_no:
            if section and section.get("json"):
                return self.add_json(section.get("locator") or section.get("section_id"),
                                     section.get("text") or "", section.get("heading", ""))
            return None
        lines = doc.get("lines") or []
        if line_no < 1 or line_no > len(lines):
            return None
        quote = lines[line_no - 1]
        if not quote.strip():
            return None
        return self.add(doc["rel"] + "#L%d" % line_no, quote,
                        source=doc["rel"], section=(section or {}).get("heading", ""))

    def add_section_line(self, doc, section, offset_line):
        quote = section.get("lines", [])[max(0, offset_line - 1)] if section else ""
        locator = doc["rel"] + "#L%d" % offset_line if doc else ""
        return self.add(locator, quote, source=doc["rel"], section=section.get("heading", "")) if doc else None

    def add_json(self, locator, quote, section=""):
        return self.add(locator, quote, source="case.json", section=section, kind="json")

    def add_csv_row(self, doc, row):
        return self.add(doc["rel"] + "#row=%d" % row["row"], row["line"],
                        source=doc["rel"], section="表格", kind="row")

    def verify_all(self):
        for item in self.items:
            verified, reason = verify_one(self.input_dir, item)
            item["verified"] = verified
            item["verify_note"] = reason
        return sum(1 for item in self.items if item.get("verified"))


def _resolve_file(input_dir, rel):
    direct = os.path.join(input_dir, rel)
    if os.path.isfile(direct):
        return direct
    for path in list_files(input_dir):
        if relpath(path, input_dir) == rel or os.path.basename(path) == os.path.basename(rel):
            return path
    return ""


def verify_one(input_dir, item):
    locator = item.get("locator") or ""
    quote = norm_space(item.get("quote") or "")
    if not locator or not quote:
        return False, "missing locator or quote"
    if "#" in locator:
        rel, fragment = locator.split("#", 1)
    else:
        rel, fragment = locator, ""
    path = _resolve_file(input_dir, rel)
    if not path:
        return False, "source file not found"
    try:
        if fragment.startswith("/"):
            data = load_json(path)
            node = json_pointer_get(data, fragment)
            blob = node if isinstance(node, str) else json.dumps(node, ensure_ascii=False)
            return (quote in norm_space(blob)), "json pointer resolved"
        if fragment.startswith("row="):
            row = int(fragment.split("=", 1)[1])
            lines = read_text(path).splitlines()
            if 1 <= row <= len(lines):
                return (quote in norm_space(lines[row - 1])), "csv row resolved"
            return False, "row out of range"
        if fragment.startswith("L"):
            match = re.match(r"L(\d+)(?:-L(\d+))?$", fragment)
            if not match:
                return False, "bad line locator"
            start = int(match.group(1))
            end = int(match.group(2) or start)
            lines = read_text(path).splitlines()
            blob = norm_space(" ".join(lines[start - 1:end]))
            return (quote in blob), "line span resolved"
    except (OSError, ValueError, KeyError, IndexError) as exc:
        return False, "locator resolution failed: %s" % type(exc).__name__
    return False, "unsupported locator"


def evidence_from_section(doc, section, pool, prefer_terms=None):
    if not doc or not section:
        return None
    if section.get("json"):
        return pool.add_json(section.get("locator") or section.get("section_id"), section.get("text") or "",
                             section.get("heading", ""))
    for offset, line in enumerate(section.get("lines", [])):
        if not line.strip():
            continue
        if prefer_terms and not line_has(line, prefer_terms):
            continue
        return pool.add_line(doc, section.get("start_line", 1) + offset, section)
    return None


def evidence_from_line(doc, line_no, pool, section=None):
    return pool.add_line(doc, line_no, section)


def absence_evidence(docs, terms, pool):
    """A real locator + quote for a genuinely absent section/parameter."""
    for doc, section, line_no, line in iter_doc_lines(docs):
        return pool.add_line(doc, line_no, section)
    for doc in docs:
        if doc.get("lines"):
            return pool.add_line(doc, 1)
    return None


# ---------------------------------------------------------------------------
# Inventory / resources
# ---------------------------------------------------------------------------

RESOURCE_KEYS = (
    "resources", "inventory", "equipment", "materials", "consumables",
    "reagents", "catalog", "resource_list", "items", "stock",
)


def classify_resource_status(item):
    raw = norm_space(" ".join(str(item.get(key, "")) for key in
                             ("availability", "status", "state", "stock_status", "condition"))).lower()
    lead = first_number(item, ("lead_time_days", "lead_time", "delivery_days", "货期", "周期"))
    if any(word in raw for word in ("不具备", "不可用", "unavailable", "not available", "out of stock", "无货", "缺货")):
        return "不具备"
    if any(word in raw for word in ("需采购", "待采购", "procure", "purchase", "order")):
        return "需采购"
    if any(word in raw for word in ("可外协", "外协", "outsource", "external", "vendor")):
        return "可外协"
    if any(word in raw for word in ("已具备", "可用", "available", "in stock", "owned", "有库存")):
        return "已具备"
    quantity = first_number(item, ("quantity", "qty", "数量", "stock", "库存"))
    if quantity is not None and quantity > 0:
        return "已具备"
    if lead is not None:
        return "需采购"
    return "未知"


def inventory_from_json(value, source_path, category_hint=""):
    items = []
    if isinstance(value, dict):
        nested = any(isinstance(v, (dict, list)) for v in value.values())
        if nested and not any(k in value for k in ("name", "名称", "model", "型号")):
            for key, spec in value.items():
                if isinstance(spec, dict):
                    item = dict(spec)
                    item.setdefault("name", key)
                else:
                    item = {"name": key, "status": spec}
                items.append(item)
        else:
            items.append(dict(value))
    elif isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                items.append(dict(entry))
            elif isinstance(entry, str):
                items.append({"name": entry})
    for item in items:
        item.setdefault("_source", source_path)
        if category_hint and not item.get("category"):
            item["category"] = category_hint
    return items


def parse_inventory_csv(doc):
    items = []
    rows = doc.get("rows") or []
    if not rows:
        return items
    header = [norm_key(cell) for cell in rows[0]["cells"]]
    synonyms = {
        "name": ("name", "名称", "资源", "设备", "材料", "item", "resource"),
        "category": ("category", "类别", "类型", "kind", "type"),
        "model": ("model", "型号", "spec", "规格"),
        "status": ("status", "availability", "状态", "availability_status"),
        "quantity": ("quantity", "qty", "数量", "stock", "库存"),
        "unit": ("unit", "单位"),
        "lead_time_days": ("lead_time_days", "lead_time", "货期", "周期"),
        "note": ("note", "备注"),
    }
    index = {}
    for field, names in synonyms.items():
        for pos, head in enumerate(header):
            if any(name == head or name in head for name in names):
                index[field] = pos
                break
    for row in rows[1:]:
        cells = row["cells"]
        if not any(cell.strip() for cell in cells):
            continue
        item = {}
        for field, pos in index.items():
            if pos < len(cells) and cells[pos].strip():
                item[field] = cells[pos].strip()
        if not item.get("name"):
            continue
        item["_source"] = doc["rel"]
        item["_locator"] = doc["rel"] + "#row=%d" % row["row"]
        item["_quote"] = row["line"]
        items.append(item)
    return items


def collect_inventory(state):
    case = state.get("case") or {}
    items = []
    for key in RESOURCE_KEYS:
        if key not in case:
            continue
        category = ""
        if key in ("equipment",):
            category = "设备"
        elif key in ("materials", "consumables", "reagents"):
            category = "材料"
        items.extend(inventory_from_json(case[key], "case.json#/" + key, category))
    for doc in state.get("docs", []):
        if doc.get("csv"):
            items.extend(parse_inventory_csv(doc))
    # de-duplicate by name+model+source while preserving order
    seen = set()
    out = []
    for item in items:
        name = norm_space(item.get("name") or item.get("item") or item.get("model"))
        if not name:
            continue
        key = (norm_key(name), norm_key(item.get("model") or ""), item.get("_source") or "")
        if key in seen:
            continue
        seen.add(key)
        item["name"] = name
        item["status_zh"] = classify_resource_status(item)
        item.setdefault("category", "其他")
        out.append(item)
    return out


def resource_tokens(item):
    tokens = []
    for key in ("name", "model", "别名", "alias"):
        value = item.get(key)
        if isinstance(value, list):
            tokens.extend(str(v) for v in value if v)
        elif value:
            tokens.append(str(value))
    cleaned = []
    for token in tokens:
        token = norm_space(token)
        if len(token) < 2:
            continue
        if token not in cleaned:
            cleaned.append(token)
    return cleaned


def find_resource_mentions(inventory, docs):
    mentions = []
    for item in inventory:
        tokens = resource_tokens(item)
        best = None
        for doc, section, line_no, line in iter_doc_lines(docs):
            lowered = line.lower()
            if any(token.lower() in lowered for token in tokens):
                ev = {
                    "locator": doc["rel"] + "#L%d" % line_no if line_no else
                               (section.get("locator") or doc["rel"]),
                    "quote": findable_quote(line),
                    "section": section.get("heading", ""),
                }
                best = ev
                break
        mentions.append({
            "name": item.get("name"),
            "category": item.get("category"),
            "model": item.get("model"),
            "status": item.get("status_zh", "未知"),
            "quantity": first_number(item, ("quantity", "qty", "数量", "stock", "库存")),
            "unit": item.get("unit"),
            "lead_time_days": first_number(item, ("lead_time_days", "lead_time", "delivery_days", "货期")),
            "mentioned_in_protocol": bool(best),
            "evidence": best,
            "source_locator": item.get("_locator") or item.get("_source"),
            "source_quote": item.get("_quote"),
        })
    return mentions


def detect_unmatched_equipment(docs, inventory):
    known = " ".join(" ".join(resource_tokens(item)) for item in inventory).lower()
    unmatched = []
    pattern = re.compile(r"(?:型号|model)\s*[:：]\s*([A-Za-z0-9][A-Za-z0-9\-_./ ]{1,40})", re.I)
    for doc, section, line_no, line in iter_doc_lines(docs):
        for match in pattern.finditer(line):
            model = norm_space(match.group(1))
            if model and model.lower() not in known:
                unmatched.append({
                    "model": model,
                    "locator": doc["rel"] + "#L%d" % line_no,
                    "quote": findable_quote(line),
                    "reason": "型号未出现在资源清单中，按未知处理，不默认已具备",
                })
    return unmatched


# ---------------------------------------------------------------------------
# Documents / SOP / manual / ethics citations
# ---------------------------------------------------------------------------

DOC_KEYS = ("documents", "sops", "manuals", "guidelines", "standards", "ethics", "safety", "approvals")


def collect_document_clauses(case):
    clauses = []
    for key in DOC_KEYS:
        if key not in case:
            continue
        value = case[key]
        if isinstance(value, str):
            clauses.append({
                "doc_id": key, "title": key, "clause_id": "",
                "text": value, "locator": "case.json#/" + key,
            })
            continue
        entries = value if isinstance(value, list) else [value]
        for index, entry in enumerate(entries):
            if isinstance(entry, str):
                clauses.append({
                    "doc_id": key, "title": key, "clause_id": "",
                    "text": entry, "locator": "case.json#/%s/%d" % (key, index),
                })
                continue
            if not isinstance(entry, dict):
                continue
            doc_id = str(entry.get("doc_id") or entry.get("id") or entry.get("code") or key)
            title = str(entry.get("title") or entry.get("name") or key)
            doc_clauses = entry.get("clauses") or entry.get("items") or []
            if isinstance(doc_clauses, dict):
                doc_clauses = [dict({"clause_id": k}, **v) if isinstance(v, dict) else {"clause_id": k, "text": str(v)}
                               for k, v in doc_clauses.items()]
            if isinstance(doc_clauses, str):
                doc_clauses = [{"text": doc_clauses}]
            for cindex, clause in enumerate(doc_clauses):
                if isinstance(clause, str):
                    text = clause
                    clause_id = ""
                    pointer = "case.json#/%s/%d/clauses/%d" % (key, index, cindex)
                elif isinstance(clause, dict):
                    text = str(clause.get("text") or clause.get("rule") or clause.get("content") or "")
                    clause_id = str(clause.get("clause_id") or clause.get("id") or "")
                    pointer = "case.json#/%s/%d/clauses/%d/text" % (key, index, cindex)
                else:
                    continue
                if text:
                    clauses.append({
                        "doc_id": doc_id, "title": title, "clause_id": clause_id,
                        "text": text, "locator": pointer,
                    })
    return clauses


def find_document_clause(clauses, category):
    terms = {
        "伦理与安全": ("伦理", "审批", "IRB", "IACUC", "安全", "生物安全", "危险"),
        "设备": ("设备", "手册", "仪器", "SOP", "操作"),
        "材料": ("材料", "试剂", "耗材", "采购"),
        "参数范围": ("参数", "温度", "流速", "范围", "手册", "SOP"),
        "样本": ("样本", "入组", "受试者", "采集"),
        "时间": ("时间", "排期", "周期", "SOP"),
    }.get(category, ())
    for clause in clauses:
        blob = clause["title"] + " " + clause["text"]
        if any(term.lower() in blob.lower() for term in terms):
            return clause
    return None


# ---------------------------------------------------------------------------
# Time and sample estimation (only explicit numbers, formula always shown)
# ---------------------------------------------------------------------------

DURATION_RE = re.compile(
    r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*"
    r"(h|hr|hrs|hour|hours|小时|min|mins|minute|minutes|分钟|d|day|days|天)(?![\w])",
    re.I,
)
UNIT_HOURS = {
    "h": 1.0, "hr": 1.0, "hrs": 1.0, "hour": 1.0, "hours": 1.0, "小时": 1.0,
    "min": 1.0 / 60.0, "mins": 1.0 / 60.0, "minute": 1.0 / 60.0,
    "minutes": 1.0 / 60.0, "分钟": 1.0 / 60.0,
    "d": 24.0, "day": 24.0, "days": 24.0, "天": 24.0,
}


def classify_phase(line):
    lowered = line.lower()
    if any(word in lowered for word in ("等待", "孵育", "过夜", "平衡", "培养", "静置", "wait", "incubat", "equilibrat")):
        return "等待周期"
    if any(word in lowered for word in ("设备", "仪器", "采集", "离心", "色谱", "hplc", "pcr", "测序", "扫描", "运行", "instrument", "run")):
        return "设备占用"
    return "人工操作"


def estimate_time(state, pool, docs=None):
    if docs is None:
        docs = protocol_docs(state)
        if not docs:
            docs = [doc for doc in state.get("docs", []) if doc.get("sections")]
    case = state.get("case") or {}
    components = []
    for doc, section, line_no, line in iter_doc_lines(docs):
        if re.search(r"总时长|总周期|总耗时|合计耗时|总计|时间窗|窗口|截止|deadline|window|"
                     r"判读|判据|阈值|标准|acceptance|criteria|"
                     r"total\s+(?:time|duration)", line, re.I):
            continue
        matches = list(DURATION_RE.finditer(line))
        if not matches:
            continue
        match = matches[0]
        value = as_number(match.group(1))
        unit = match.group(2).lower()
        if value is None or unit not in UNIT_HOURS:
            continue
        hours = round(value * UNIT_HOURS[unit], 4)
        label = norm_space(re.split(r"[:：]", line, 1)[0])[:40] or section.get("heading", "")
        components.append({
            "phase": classify_phase(line),
            "label": label,
            "hours": hours,
            "locator": doc["rel"] + "#L%d" % line_no if line_no else (section.get("locator") or doc["rel"]),
            "quote": findable_quote(line),
            "evidence_id": (pool.add_line(doc, line_no, section) or {}).get("id") if line_no else None,
        })

    total = round(sum(item["hours"] for item in components), 4) if components else None
    formula = None
    if components:
        formula = " + ".join("%g" % item["hours"] for item in components) + " = %g h" % total

    declared = first_number(case, ("total_hours", "planned_hours", "duration_h", "estimated_hours", "time_budget_h"))
    declared_locator = None
    if declared is None:
        for doc, section, line_no, line in iter_doc_lines(docs):
            if re.search(r"总时长|总周期|总耗时|合计耗时|total\s+(?:time|duration)", line, re.I):
                match = DURATION_RE.search(line)
                if match and match.group(2).lower() in UNIT_HOURS:
                    declared = round(as_number(match.group(1)) * UNIT_HOURS[match.group(2).lower()], 4)
                    declared_locator = doc["rel"] + "#L%d" % line_no
                    pool.add_line(doc, line_no, section)
                    break

    window = first_number(case, ("time_window_h", "time_budget_h", "max_hours", "deadline_h",
                                 "schedule_window_h", "budget_hours", "window_hours"))
    window_locator = None
    if window is not None:
        for key in ("time_window_h", "time_budget_h", "max_hours", "deadline_h", "schedule_window_h", "budget_hours"):
            if key in case:
                window_locator = "case.json#/" + key
                pool.add_json(window_locator, "%g" % window, "时间窗")
                break

    effective = total if total is not None else declared
    within = None
    status = "unknown"
    if effective is None:
        status = "no_explicit_numbers"
    elif window is None:
        status = "window_not_provided"
    else:
        within = effective <= window
        status = "within_window" if within else "exceeds_window"

    mismatch = False
    if total is not None and declared is not None and abs(total - declared) > 0.1:
        mismatch = True

    return {
        "unit": "h",
        "components": components,
        "total_hours": total,
        "formula": formula,
        "declared_total_hours": declared,
        "declared_locator": declared_locator,
        "window_hours": window,
        "window_locator": window_locator,
        "within_window": within,
        "status": status,
        "arithmetic_mismatch": mismatch,
        "note": "仅汇总输入中明示的时长；未给出的等待/周转不臆造。",
    }


SAMPLE_RE = re.compile(
    r"(?:(?:入组|纳入|采集|计划|共|每组|n\s*=)\s*)?"
    r"(\d+)\s*(?:例|名|份|个|只|samples?|subjects?|patients?|aliquots?)\s*"
    r"(?:受试者|患者|样本|动物|小鼠|大鼠|志愿者)?",
    re.I,
)
REPLICATE_RE = re.compile(r"(\d+)\s*(?:次重复|重复|replicates?|reps?)", re.I)
GROUP_RE = re.compile(r"(\d+)\s*(?:组|个组|组别|groups?|arms?)", re.I)


def is_sample_resource(item):
    blob = (str(item.get("category") or "") + " " + str(item.get("name") or "") + " " + str(item.get("model") or "")).lower()
    return any(word in blob for word in ("样本", "血清", "血浆", "受试", "sample", "specimen", "aliquot", "血样", "组织"))


def estimate_samples(state, inventory, pool, docs=None):
    if docs is None:
        docs = protocol_docs(state)
        if not docs:
            docs = [doc for doc in state.get("docs", []) if doc.get("sections")]
    case = state.get("case") or {}
    n_value = n_locator = n_quote = None
    replicates = groups = None
    rep_locator = group_locator = None

    candidates = []
    for doc, section, line_no, line in iter_doc_lines(docs):
        if not line_has(line, ("样本", "受试", "入组", "纳入", "采集", "sample", "subject", "patient", "n =")):
            continue
        match = SAMPLE_RE.search(line)
        if match:
            candidates.append((doc, section, line_no, line, int(match.group(1))))
    if candidates:
        doc, section, line_no, line, value = candidates[0]
        n_value = value
        n_locator = (doc["rel"] + "#L%d" % line_no) if line_no else (section.get("locator") or doc["rel"])
        n_quote = findable_quote(line)
        pool.add_line(doc, line_no, section)

    for doc, section, line_no, line in iter_doc_lines(docs):
        if replicates is None:
            match = REPLICATE_RE.search(line)
            if match:
                replicates = int(match.group(1))
                rep_locator = (doc["rel"] + "#L%d" % line_no) if line_no else (section.get("locator") or doc["rel"])
        if groups is None:
            match = GROUP_RE.search(line)
            if match:
                groups = int(match.group(1))
                group_locator = (doc["rel"] + "#L%d" % line_no) if line_no else (section.get("locator") or doc["rel"])

    computed = None
    formula = None
    if n_value is not None:
        computed = n_value * (groups or 1) * (replicates or 1)
        formula = "%d × %d × %d = %d" % (n_value, groups or 1, replicates or 1, computed)

    available = None
    available_locator = None
    available_quote = None
    sample_items = [item for item in inventory if is_sample_resource(item)]
    quantities = [first_number(item, ("quantity", "qty", "数量", "stock", "库存")) for item in sample_items]
    quantities = [q for q in quantities if q is not None]
    if quantities:
        available = int(sum(quantities))
        available_locator = sample_items[0].get("_locator") or sample_items[0].get("_source")
        available_quote = sample_items[0].get("_quote")
        pool.add(available_locator, available_quote, source=sample_items[0].get("_source", ""), kind="row")
    elif isinstance(case.get("samples"), dict):
        available = first_number(case["samples"], ("available", "available_n", "count", "stock", "total"))
        available_locator = "case.json#/samples"

    required_declared = first_number(case, ("required_samples", "sample_size_required", "required_n"))
    if required_declared is None and isinstance(case.get("samples"), dict):
        required_declared = first_number(case["samples"], ("required", "required_n", "needed"))
    required = required_declared if required_declared is not None else computed

    status = "unknown"
    if required is not None and available is not None:
        status = "sufficient" if available >= required else "insufficient"
    elif required is None:
        status = "requirement_not_explicit"
    else:
        status = "availability_unknown"

    return {
        "available": available,
        "required_declared": required_declared,
        "required_computed": computed,
        "required_effective": required,
        "formula": formula,
        "sample_size": n_value,
        "groups": groups,
        "replicates": replicates,
        "status": status,
        "shortfall": (required - available) if (required is not None and available is not None and available < required) else 0,
        "evidence": {
            "locator": n_locator,
            "quote": n_quote,
            "available_locator": available_locator,
            "available_quote": available_quote,
            "replicates_locator": rep_locator,
            "groups_locator": group_locator,
        },
        "note": "仅在样本数、组数、重复数明示时相乘；未明示的量按 1 处理并在公式中显示。",
    }


# ---------------------------------------------------------------------------
# Parameter domains and unit handling
# ---------------------------------------------------------------------------

PARAM_KEYS = ("parameter_domains", "parameters", "parameter_ranges", "domains", "limits", "spec")
PARAM_NAME_HINTS = ("柱温", "温度", "流速", "流量", "进样", "ph", "浓度", "压力", "转速",
                    "时间", "电压", "功率", "剂量", "体积", "temperature", "flow", "pressure",
                    "concentration", "speed", "voltage", "power", "dose", "volume", "ph")

UNIT_ALIASES = {
    "℃": "c", "°c": "c", "c": "c", "k": "k", "°f": "f", "f": "f",
    "ml/min": "ml/min", "ml/min.": "ml/min", "ml·min-1": "ml/min", "ml min-1": "ml/min",
    "µl": "ul", "μl": "ul", "ul": "ul", "ml": "ml", "l": "l",
    "min": "min", "分钟": "min", "h": "h", "小时": "h", "s": "s", "秒": "s",
    "mg": "mg", "g": "g", "kg": "kg", "µg": "ug", "μg": "ug", "ug": "ug", "ng": "ng",
    "kpa": "kpa", "mpa": "mpa", "bar": "bar", "psi": "psi", "pa": "pa",
    "%": "%", "rpm": "rpm", "v": "v", "mv": "mv", "ma": "ma", "a": "a",
    "mm": "mm", "cm": "cm", "um": "um", "nm": "nm",
}


def clean_unit(unit):
    if not unit:
        return ""
    unit = norm_space(unit).lower().replace(" ", "")
    return UNIT_ALIASES.get(unit, unit)


def convert_value(value, from_unit, to_unit):
    """Return (converted, note) or (None, reason) when dimensions differ."""
    src, dst = clean_unit(from_unit), clean_unit(to_unit)
    if not src or not dst or src == dst:
        return value, None
    time_map = {"s": 1.0 / 3600.0, "min": 1.0 / 60.0, "h": 1.0, "d": 24.0}
    if src in time_map and dst in time_map:
        return value * time_map[src] / time_map[dst], "%s -> %s" % (src, dst)
    vol_map = {"ul": 0.001, "ml": 1.0, "l": 1000.0}
    if src in vol_map and dst in vol_map:
        return value * vol_map[src] / vol_map[dst], "%s -> %s" % (src, dst)
    mass_map = {"ug": 0.001, "mg": 1.0, "g": 1000.0, "kg": 1000000.0, "ng": 0.000001}
    if src in mass_map and dst in mass_map:
        return value * mass_map[src] / mass_map[dst], "%s -> %s" % (src, dst)
    if src in ("c", "k", "f") and dst in ("c", "k", "f"):
        celsius = value
        if src == "k":
            celsius = value - 273.15
        elif src == "f":
            celsius = (value - 32.0) * 5.0 / 9.0
        out = celsius
        if dst == "k":
            out = celsius + 273.15
        elif dst == "f":
            out = celsius * 9.0 / 5.0 + 32.0
        return out, "%s -> %s" % (src, dst)
    return None, "单位维度不一致: %s vs %s" % (src, dst)


def domain_from_spec(spec):
    if isinstance(spec, dict):
        low = first_number(spec, ("min", "minimum", "lower", "range_min", "from"))
        high = first_number(spec, ("max", "maximum", "upper", "range_max", "to"))
        allowed = spec.get("values") or spec.get("allowed") or spec.get("levels") or spec.get("one_of")
        rng = spec.get("range")
        if isinstance(rng, list) and len(rng) == 2:
            low = low if low is not None else as_number(rng[0])
            high = high if high is not None else as_number(rng[1])
        return {
            "min": low, "max": high,
            "values": allowed if isinstance(allowed, list) else None,
            "unit": spec.get("unit") or spec.get("units") or "",
        }
    if isinstance(spec, list) and len(spec) == 2:
        return {"min": as_number(spec[0]), "max": as_number(spec[1]), "values": None, "unit": ""}
    return {"min": None, "max": None, "values": None, "unit": ""}


def collect_domains(case):
    domains = {}
    if not isinstance(case, dict):
        return domains
    for pointer, value in walk_json(case):
        leaf = pointer.rsplit("/", 1)[-1]
        if leaf not in PARAM_KEYS:
            continue
        entries = []
        if isinstance(value, dict):
            if any(key in value for key in ("min", "max", "minimum", "maximum", "range", "values", "allowed")):
                entries.append((leaf, value))
            else:
                for name, spec in value.items():
                    entries.append((name, spec))
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    name = entry.get("name") or entry.get("key") or entry.get("parameter")
                    if name:
                        entries.append((str(name), entry))
        for name, spec in entries:
            domain = domain_from_spec(spec)
            if domain["min"] is None and domain["max"] is None and not domain["values"]:
                continue
            key = norm_key(name)
            domains[key] = {
                "name": str(name), "min": domain["min"], "max": domain["max"],
                "values": domain["values"], "unit": domain["unit"],
                "locator": "case.json#" + pointer + ("" if isinstance(value, list) else "/" + str(name)),
            }
    return domains


PARAM_LINE_RE = re.compile(
    r"^\s*[-*]?\s*([A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff_()（）/\-· ]{1,30}?)\s*[:：=]\s*"
    r"([-+]?\d+(?:\.\d+)?)\s*([A-Za-z°℃µμ/%·\-0-9]{0,15})"
)
PARAM_KEY_MAP = {
    "柱温": "column_temp", "色谱柱温度": "column_temp", "column temperature": "column_temp",
    "温度": "temperature", "temperature": "temperature",
    "流速": "flow_rate", "流量": "flow_rate", "flow rate": "flow_rate", "flow": "flow_rate",
    "进样量": "injection_volume", "进样体积": "injection_volume", "injection volume": "injection_volume",
    "ph": "ph", "ph值": "ph",
    "浓度": "concentration", "concentration": "concentration",
    "压力": "pressure", "pressure": "pressure",
    "转速": "rpm", "离心转速": "rpm", "speed": "rpm",
    "电压": "voltage", "voltage": "voltage",
    "功率": "power", "power": "power",
    "剂量": "dose", "dose": "dose",
    "体积": "volume", "volume": "volume",
    "时间": "time", "duration": "time", "time": "time",
}


def canonical_param_key(name):
    key = norm_key(name)
    if key in PARAM_KEY_MAP:
        return norm_key(PARAM_KEY_MAP[key])
    for token, canonical in PARAM_KEY_MAP.items():
        if norm_key(token) in key:
            return norm_key(canonical)
    return key


def parse_protocol_parameters(docs):
    params = []
    for doc, section, line_no, line in iter_doc_lines(docs):
        if re.search(r"时间窗|窗口|总时长|总周期|截止|deadline|window", line, re.I):
            continue
        heading = section.get("heading") or ""
        in_param_section = any(term in heading.lower() for term in ("参数", "条件", "设置", "parameter", "condition", "setting"))
        if not in_param_section and not any(hint in line.lower() for hint in PARAM_NAME_HINTS):
            continue
        match = PARAM_LINE_RE.match(line)
        if not match:
            continue
        name = norm_space(match.group(1))
        value = as_number(match.group(2))
        unit = norm_space(match.group(3))
        if value is None or len(name) < 2:
            continue
        params.append({
            "name": name,
            "canonical": canonical_param_key(name),
            "value": value,
            "unit": unit,
            "locator": doc["rel"] + "#L%d" % line_no if line_no else (section.get("locator") or doc["rel"]),
            "quote": findable_quote(line),
            "section": heading,
        })
    return params


def compare_parameters(params, domains):
    results = []
    for param in params:
        domain = domains.get(param["canonical"]) or domains.get(norm_key(param["name"]))
        entry = dict(param)
        entry.update({"status": "no_domain", "domain": None, "converted_value": None, "conversion_note": None})
        if domain:
            entry["domain"] = {
                "min": domain["min"], "max": domain["max"], "values": domain["values"],
                "unit": domain["unit"], "locator": domain.get("locator"),
            }
            value = param["value"]
            if domain.get("unit") and param.get("unit"):
                converted, note = convert_value(value, param["unit"], domain["unit"])
                if converted is None:
                    entry["status"] = "unit_inconsistent"
                    entry["conversion_note"] = note
                    results.append(entry)
                    continue
                value = converted
                entry["converted_value"] = round(value, 6)
                entry["conversion_note"] = note
            if domain["min"] is not None or domain["max"] is not None:
                low = domain["min"] if domain["min"] is not None else float("-inf")
                high = domain["max"] if domain["max"] is not None else float("inf")
                entry["status"] = "in_range" if low <= value <= high else "out_of_range"
            elif domain["values"]:
                entry["status"] = "in_range" if value in domain["values"] else "out_of_range"
        results.append(entry)
    return results


# ---------------------------------------------------------------------------
# Ethics / safety
# ---------------------------------------------------------------------------

def ethics_status(case):
    values = []
    for key in ("ethics", "compliance", "approvals", "irb", "safety", "biosafety"):
        if key in case:
            values.append(json.dumps(case[key], ensure_ascii=False))
    blob = " ".join(values).lower()
    if any(word in blob for word in ("拒绝", "未通过", "rejected", "denied")):
        return "已拒绝", blob
    if any(word in blob for word in ("已批准", "批准", "approved", "approval granted", "通过")):
        return "已批准", blob
    if any(word in blob for word in ("审批中", "待批", "已提交", "pending", "submitted", "in review")):
        return "审批中", blob
    if values:
        return "已声明但状态不明", blob
    return "未声明", ""


def detect_triggers(text):
    lowered = text.lower()
    triggers = []
    if any(word in lowered for word in ("受试者", "患者", "人体", "人外周血", "血清", "血浆", "human", "patient", "participant", "subject")):
        triggers.append("人体样本")
    if any(word in lowered for word in ("小鼠", "大鼠", "动物", "animal", "mouse", "mice", "rat")):
        triggers.append("动物实验")
    if any(word in lowered for word in ("乙腈", "甲醇", "有毒", "剧毒", "放射性", "危险", "hazard", "toxic", "radioactive")):
        triggers.append("危险试剂")
    if any(word in lowered for word in ("个人数据", "隐私", "personal data", "privacy", "pii")):
        triggers.append("个人数据")
    return triggers


# ---------------------------------------------------------------------------
# Checklist definitions and item evaluation
# ---------------------------------------------------------------------------

CATEGORY_MAP = {
    "假设与变量": "hypothesis", "假设": "hypothesis", "变量": "hypothesis", "hypothesis": "hypothesis",
    "对照组": "controls", "对照": "controls", "controls": "controls", "control": "controls",
    "设备": "equipment", "仪器": "equipment", "equipment": "equipment",
    "材料": "materials", "耗材": "materials", "试剂": "materials", "materials": "materials",
    "样本": "samples", "受试者": "samples", "samples": "samples",
    "时间": "time", "排期": "time", "time": "time",
    "伦理与安全": "ethics", "伦理": "ethics", "安全": "ethics", "ethics": "ethics",
    "参数范围": "parameters", "参数": "parameters", "parameters": "parameters",
    "风险与异常": "risks", "风险": "risks", "异常": "risks", "risks": "risks",
}

SEVERITY_ORDER = {"blocker": 0, "major": 1, "minor": 2, "info": 3}


def category_key(category, question=""):
    cat = str(category or "").lower()
    qst = str(question or "").lower()
    for token in sorted(CATEGORY_MAP, key=len, reverse=True):
        if token.lower() in cat:
            return CATEGORY_MAP[token]
    for token in sorted(CATEGORY_MAP, key=len, reverse=True):
        if token.lower() in qst:
            return CATEGORY_MAP[token]
    return "general"


def load_checklist(case):
    raw = None
    source = "default"
    if isinstance(case, dict):
        for key in ("checklist", "checklist_items", "review_checklist", "checks"):
            if isinstance(case.get(key), list) and case[key]:
                raw = case[key]
                source = "case.json#/" + key
                break
    defs = []
    if raw:
        for index, item in enumerate(raw):
            if isinstance(item, str):
                item = {"category": item, "question": item}
            if not isinstance(item, dict):
                continue
            category = item.get("category") or item.get("type") or item.get("name") or "其他"
            question = item.get("question") or item.get("check") or item.get("description") or category
            defs.append({
                "item_id": str(item.get("item_id") or item.get("id") or "CHK-%02d" % (index + 1)),
                "category": category,
                "question": question,
                "severity": str(item.get("severity") or "major").lower(),
                "basis": str(item.get("basis") or item.get("source") or "案例检查项"),
                "rule": str(item.get("rule") or item.get("criterion") or "按输入证据逐项判定。"),
                "_source": source,
            })
    template, template_source = template_checklist()
    if not defs:
        for item in template:
            item = dict(item)
            item["_source"] = template_source
            defs.append(item)
        return defs, template_source
    present = {category_key(item.get("category"), item.get("question")) for item in defs}
    for item in template:
        key = category_key(item.get("category"), item.get("question"))
        if key not in present:
            item = dict(item)
            item["_source"] = template_source
            defs.append(item)
    return defs, source


def content_lines(docs):
    for doc, section, line_no, line in iter_doc_lines(docs):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if HEADING_RE.match(line) or BOLD_HEADING_RE.match(line):
            continue
        yield doc, section, line_no, line


def find_content_line(docs, terms):
    for doc, section, line_no, line in content_lines(docs):
        if line_has(line, terms):
            return doc, section, line_no, line
    return None, None, None, None


def citation_evidence(ctx, category):
    clause = find_document_clause(ctx["clauses"], category)
    if not clause:
        return None, None
    item = ctx["pool"].add_json(clause["locator"], clause["text"], "%s %s" % (clause["doc_id"], clause["clause_id"]))
    return item, clause


def make_item(defn, verdict, evidence, rationale, severity=None, required_condition=None,
              suggested_fix="", supporting=None, citation=None):
    severity = severity or defn.get("severity") or "major"
    if verdict != "satisfied" and not required_condition:
        required_condition = "需按建议补齐证据或条件后复核。"
    return {
        "item_id": defn.get("item_id"),
        "category": defn.get("category"),
        "question": defn.get("question"),
        "verdict": verdict,
        "verdict_zh": VERDICT_ZH.get(verdict, verdict),
        "evidence": evidence,
        "rationale": rationale,
        "severity": severity,
        "severity_zh": SEVERITY_ZH.get(severity, severity),
        "required_condition": required_condition,
        "suggested_fix": suggested_fix or "补充可核验的方案原文或资源记录。",
        "supporting_evidence": supporting or [],
        "basis": defn.get("basis"),
        "rule": defn.get("rule"),
        "citation": citation,
        "checklist_source": defn.get("_source"),
    }


def eval_hypothesis(ctx, defn):
    h_doc, h_sec, h_line, h_text = find_content_line(ctx["docs"], ("假设", "hypothesis", "研究问题", "research question"))
    v_doc, v_sec, v_line, v_text = find_content_line(ctx["docs"], ("变量", "variable", "终点", "endpoint", "判读标准", "outcome"))
    evidence = ctx["pool"].add_line(h_doc, h_line, h_sec) if h_doc else None
    if not evidence and v_doc:
        evidence = ctx["pool"].add_line(v_doc, v_line, v_sec)
    if not evidence:
        evidence = absence_evidence(ctx["docs"], ("假设", "变量"), ctx["pool"])
    support = []
    if v_doc and v_line and (not h_doc or v_doc is not h_doc or v_line != h_line):
        ev = ctx["pool"].add_line(v_doc, v_line, v_sec)
        if ev:
            support.append(ev)
    if h_doc and v_doc:
        return make_item(defn, "satisfied", evidence,
                         "已给出可检验假设，并给出可测量变量/终点；两处原文可按定位复核。",
                         supporting=support,
                         suggested_fix="保持假设、变量与判读标准一致；修订时同步更新终点定义。")
    if h_doc or v_doc:
        missing = "变量或主要终点" if h_doc else "可检验假设"
        return make_item(defn, "partial", evidence,
                         "方案只写了假设或只写了变量，缺少%s，无法完整复核可检验性。" % missing,
                         required_condition="补齐%s，并说明测量方法与判读阈值。" % missing,
                         suggested_fix="在方案中同时写明假设、自变量、因变量与主要终点。",
                         supporting=support)
    return make_item(defn, "missing", evidence,
                     "未在方案中找到假设与变量/终点，不能把未写当作满足。",
                     required_condition="补充可检验假设、变量与主要终点。",
                     suggested_fix="新增“假设与变量”章节，绑定测量指标与判读阈值。")


def eval_controls(ctx, defn):
    doc, sec, line_no, line = find_content_line(ctx["docs"], ("不设对照", "无对照", "未设对照", "without control", "no control", "不设置对照"))
    if doc:
        ev = ctx["pool"].add_line(doc, line_no, sec)
        return make_item(defn, "missing", ev,
                         "方案原文明确不设对照组；处理效应无法与时间/批次/安慰剂效应区分。",
                         severity="major",
                         required_condition="补设阴性对照；如涉及干预，同时补阳性对照并写明分组与样本分配。",
                         suggested_fix="增加对照组章节，列明阴性/阳性对照、分组方式与随机化/盲法安排。")
    doc, sec, line_no, line = find_content_line(ctx["docs"], ("对照", "control"))
    if doc:
        blob = (sec.get("text") or "") + " " + line
        has_neg = any(term in blob for term in ("阴性对照", "negative control", "空白对照", "溶剂对照"))
        has_pos = any(term in blob for term in ("阳性对照", "positive control", "阳性药物"))
        ev = ctx["pool"].add_line(doc, line_no, sec)
        if has_neg and has_pos:
            return make_item(defn, "satisfied", ev,
                             "方案同时写明阴性对照与阳性对照，可支持处理效应判读。",
                             suggested_fix="保持对照定义与分组样本量一致；变更干预时重新核对对照。")
        return make_item(defn, "partial", ev,
                         "方案提到对照，但未同时写明阴性/阳性对照，判读边界不完整。",
                         required_condition="补齐阴性对照与阳性对照（或说明不适用的依据）。",
                         suggested_fix="在对照章节分别定义阴性、阳性对照及分组样本量。")
    ev = absence_evidence(ctx["docs"], ("对照",), ctx["pool"])
    return make_item(defn, "missing", ev,
                     "未找到对照设置；未写不等于已满足。",
                     required_condition="补设对照组并写明分组、样本量与判读方式。",
                     suggested_fix="新增对照组章节。")


def _resource_eval(ctx, defn, kinds):
    mentions = [row for row in ctx["mentions"] if row.get("category") in kinds]
    if not ctx["inventory"]:
        ev = absence_evidence(ctx["docs"], kinds, ctx["pool"])
        return make_item(defn, "uncertain", ev,
                         "案例未提供资源/库存清单，无法核验%s是否到位；按未知处理。" % "/".join(kinds),
                         required_condition="提供设备/材料清单（名称、型号、状态、数量、货期）。",
                         suggested_fix="补充资源清单后重跑；在此之前不得写成已具备。")
    mentioned = [row for row in mentions if row.get("mentioned_in_protocol")]
    if not mentioned:
        ev = absence_evidence(ctx["docs"], kinds, ctx["pool"])
        return make_item(defn, "missing", ev,
                         "方案未点名任何可在资源清单中匹配的%s，无法核对型号与可用性。" % "/".join(kinds),
                         required_condition="在方案中写明设备/材料名称与型号，并与清单逐项对应。",
                         suggested_fix="补充设备型号、关键附件与耗材规格。")
    statuses = [row.get("status") for row in mentioned]
    first = mentioned[0]
    evidence = ctx["pool"].add(first["evidence"]["locator"], first["evidence"]["quote"],
                               first["evidence"].get("section", "")) if first.get("evidence") else None
    support = []
    for row in mentioned:
        if row.get("source_locator"):
            support.append(ctx["pool"].add(row["source_locator"], row.get("source_quote") or row["name"],
                                           source=row.get("source_locator", "").split("#")[0], kind="row"))
    support = [item for item in support if item]
    if any(status == "不具备" for status in statuses):
        bad = [row["name"] for row in mentioned if row.get("status") == "不具备"]
        return make_item(defn, "conflict", evidence,
                         "资源清单显示不具备：%s；方案不能按原样开工。" % "、".join(bad),
                         severity="blocker",
                         required_condition="替换为清单内可用资源，或提供外协/采购合同与到位时间。",
                         suggested_fix="给出替代型号并重新核对精度、附件与方法兼容性。",
                         supporting=support)
    if any(status in ("需采购", "可外协") for status in statuses):
        pending = [row["name"] for row in mentioned if row.get("status") in ("需采购", "可外协")]
        return make_item(defn, "partial", evidence,
                         "部分资源需采购/外协：%s；开始前需确认到货或外协排期。" % "、".join(pending),
                         required_condition="完成采购/外协并确认到位时间早于方案开始时间。",
                         suggested_fix="把采购/外协行、责任人与预计到位日写入排期表。",
                         supporting=support)
    if any(status == "未知" for status in statuses):
        return make_item(defn, "uncertain", evidence,
                         "资源清单中存在状态未注明的条目，无法确认是否可用。",
                         required_condition="逐条确认资源状态（已具备/可外协/需采购/不具备）。",
                         suggested_fix="补齐资源状态与库存数量。",
                         supporting=support)
    return make_item(defn, "satisfied", evidence,
                     "方案点名的资源均可在清单中匹配且标记为已具备。",
                     suggested_fix="保持型号与清单一致；更换批次前复核规格。",
                     supporting=support)


def eval_equipment(ctx, defn):
    return _resource_eval(ctx, defn, ("设备", "仪器", "equipment"))


def eval_materials(ctx, defn):
    return _resource_eval(ctx, defn, ("材料", "耗材", "试剂", "materials", "consumable", "reagent"))


def eval_samples(ctx, defn):
    est = ctx["samples"]
    ev = None
    if est["evidence"].get("locator"):
        ev = ctx["pool"].add(est["evidence"]["locator"], est["evidence"]["quote"],
                             kind="quote")
    if ev is None:
        ev = absence_evidence(ctx["docs"], ("样本", "受试者"), ctx["pool"])
    support = []
    if est["evidence"].get("available_locator"):
        support.append(ctx["pool"].add(est["evidence"]["available_locator"],
                                       est["evidence"].get("available_quote") or "样本库存",
                                       kind="row"))
    support = [item for item in support if item]
    status = est["status"]
    if status == "sufficient":
        return make_item(defn, "satisfied", ev,
                         "可得样本 %s ≥ 需求 %s（%s）。" % (est["available"], est["required_effective"], est["formula"]),
                         suggested_fix="保持样本量与分组重复数一致；入组前复核库存。",
                         supporting=support)
    if status == "insufficient":
        ratio = (est["shortfall"] / float(est["required_effective"])) if est["required_effective"] else 1
        severity = "blocker" if ratio > 0.5 else "major"
        return make_item(defn, "conflict", ev,
                         "可得样本 %s < 需求 %s，缺口 %s；算式：%s。不能把缺口当作已满足。" %
                         (est["available"], est["required_effective"], est["shortfall"], est["formula"]),
                         severity=severity,
                         required_condition="补充至少 %s 份样本，或下调组数/重复数并重算功效。" % est["shortfall"],
                         suggested_fix="扩大样本来源、延长采集窗口，或按功效分析调整分组重复数。",
                         supporting=support)
    if status == "requirement_not_explicit":
        return make_item(defn, "uncertain", ev,
                         "方案未明示样本数/组数/重复数，无法计算需求量；不臆造数字。",
                         required_condition="写明样本数、组数与重复数，并给出样本量依据。",
                         suggested_fix="补充样本量计算与分组表。",
                         supporting=support)
    if status == "availability_unknown":
        return make_item(defn, "uncertain", ev,
                         "需求可计算，但库存/可得样本量未知，无法判断是否够用。",
                         required_condition="提供样本库存或来源确认（数量、保存条件、伦理状态）。",
                         suggested_fix="补充样本清单与来源证明。",
                         supporting=support)
    return make_item(defn, "uncertain", ev,
                     "样本需求与可得量均无法从输入中确认。",
                     required_condition="补充样本需求与库存证据。",
                     suggested_fix="在方案中增加样本与来源章节。")


def eval_time(ctx, defn):
    est = ctx["time"]
    ev = None
    if est["components"]:
        first = est["components"][0]
        ev = ctx["pool"].add(first["locator"], first["quote"], kind="quote")
    if ev is None:
        ev = absence_evidence(ctx["docs"], ("时间", "时长", "h", "小时"), ctx["pool"])
    support = []
    if est.get("window_locator"):
        support.append(ctx["pool"].add_json(est["window_locator"], "%g" % est["window_hours"], "时间窗"))
    support = [item for item in support if item]
    status = est["status"]
    if status == "no_explicit_numbers":
        return make_item(defn, "missing", ev,
                         "方案没有任何可解析的步骤时长或总时长，无法估算时间成本。",
                         required_condition="按步骤写明设备占用、人工操作与等待周期。",
                         suggested_fix="新增时间估算表，列出每步时长、并行关系与等待周期。")
    if status == "window_not_provided":
        return make_item(defn, "uncertain", ev,
                         "方案时长可估算（%s），但案例未给出时间窗，无法判断是否超期。" % est.get("formula"),
                         required_condition="补充项目时间窗或排期约束。",
                         suggested_fix="提供截止时间/机时窗口后重算。",
                         supporting=support)
    if est.get("arithmetic_mismatch"):
        return make_item(defn, "conflict", ev,
                         "分项时长合计与方案声明总时长不一致：合计 %s h，声明 %s h。" %
                         (est["total_hours"], est["declared_total_hours"]),
                         severity="major",
                         required_condition="统一分项与总时长，说明并行/等待如何计入。",
                         suggested_fix="重算总时长并更新排期表。",
                         supporting=support)
    if status == "exceeds_window":
        effective = est.get("total_hours") if est.get("total_hours") is not None else est.get("declared_total_hours")
        ratio = effective / float(est["window_hours"]) if est["window_hours"] else 1
        severity = "blocker" if ratio > 1.5 else "major"
        return make_item(defn, "conflict", ev,
                         "计划时长 %g h 超过时间窗 %g h；算式：%s。" %
                         (effective, est["window_hours"], est.get("formula")),
                         severity=severity,
                         required_condition="压缩步骤/并行化/增加机时，使总时长不超过 %g h。" % est["window_hours"],
                         suggested_fix="拆分批次、并行等待步骤，或申请额外机时。",
                         supporting=support)
    effective = est.get("total_hours") if est.get("total_hours") is not None else est.get("declared_total_hours") or 0
    return make_item(defn, "satisfied", ev,
                     "计划时长 %g h 在时间窗 %g h 内；算式：%s。" %
                     (effective, est["window_hours"], est.get("formula")),
                     suggested_fix="保持排期假设；变更步骤时长时重算。",
                     supporting=support)


def eval_ethics(ctx, defn):
    triggers = ctx["triggers"]
    status = ctx["ethics_status"]
    doc, sec, line_no, line = find_content_line(ctx["docs"],
        ("伦理批件", "伦理", "IRB", "IACUC", "审批", "备案", "安全声明"))
    if not doc:
        doc, sec, line_no, line = find_content_line(ctx["docs"],
            ("受试者", "患者", "人体", "血清", "动物", "小鼠", "大鼠", "乙腈", "危险", "hazard", "human", "animal"))
    ev = ctx["pool"].add_line(doc, line_no, sec) if doc else absence_evidence(ctx["docs"], ("伦理", "安全"), ctx["pool"])
    citation_item = None
    clause = find_document_clause(ctx["clauses"], "伦理与安全")
    if clause:
        citation_item = ctx["pool"].add_json(clause["locator"], clause["text"], "伦理依据")
    support = []
    if citation_item:
        support.append(citation_item)
    if not triggers:
        return make_item(defn, "satisfied", ev,
                         "未检出人体/动物/危险试剂/个人数据触发项；伦理与安全按不触发处理。",
                         suggested_fix="若后续加入人体/动物样本或危险试剂，重新触发审批检查。",
                         supporting=support)
    label = "、".join(triggers)
    if status == "已批准":
        return make_item(defn, "satisfied", ev,
                         "检出触发项（%s），案例声明伦理审批已批准；仍以批件原件与有效期为最终依据。" % label,
                         suggested_fix="执行前核对批件编号、有效期与方案版本一致。",
                         supporting=support, citation=clause)
    if status == "审批中":
        return make_item(defn, "partial", ev,
                         "检出触发项（%s），审批仍在进行中；未获批前不得入组或采样。" % label,
                         required_condition="取得伦理批件并确认批准版本覆盖当前方案。",
                         suggested_fix="把批件编号、批准日期与覆盖范围写入方案首页。",
                         supporting=support, citation=clause)
    if status == "已拒绝":
        return make_item(defn, "conflict", ev,
                         "检出触发项（%s），但伦理审批被拒；方案不能执行。" % label,
                         severity="blocker",
                         required_condition="修改方案后重新送审，或终止涉及该样本的步骤。",
                         suggested_fix="按审查意见修订并重新提交伦理申请。",
                         supporting=support, citation=clause)
    return make_item(defn, "uncertain", ev,
                     "检出触发项（%s），但伦理/安全审批状态未声明；不得写成已批准。" % label,
                     severity="blocker",
                     required_condition="明确需要的审批级别、提交材料与预计周期，并取得批件。",
                     suggested_fix="补充伦理/安全审批状态与批件编号。",
                     supporting=support, citation=clause)


def eval_parameters(ctx, defn):
    results = ctx["params"]
    if not results:
        ev = absence_evidence(ctx["docs"], ("参数", "柱温", "流速", "pH"), ctx["pool"])
        return make_item(defn, "missing", ev,
                         "方案未给出可比较的数值参数，无法核对参数范围。",
                         required_condition="列出关键参数、设定值、单位与允许范围。",
                         suggested_fix="新增参数表，逐项给出设定值与依据。")
    out = [row for row in results if row.get("status") == "out_of_range"]
    bad_unit = [row for row in results if row.get("status") == "unit_inconsistent"]
    no_domain = [row for row in results if row.get("status") == "no_domain"]
    first = out[0] if out else (bad_unit[0] if bad_unit else results[0])
    ev = ctx["pool"].add(first["locator"], first["quote"], kind="quote")
    support = []
    for row in results:
        domain = row.get("domain")
        if domain and domain.get("locator"):
            anchor = domain.get("max") if domain.get("max") is not None else domain.get("min")
            support.append(ctx["pool"].add_json(domain["locator"], "%g" % anchor, "参数域"))
    support = [item for item in support if item]
    if out:
        row = out[0]
        domain = row.get("domain") or {}
        return make_item(defn, "conflict", ev,
                         "%s 设定 %g %s，超出参数域 [%s, %s] %s；按原文定位复核。" %
                         (row["name"], row["value"], row.get("unit", ""),
                          domain.get("min"), domain.get("max"), domain.get("unit", "")),
                         required_condition="把 %s 调整到 [%s, %s] %s 内，或提供设备/色谱柱耐受限依据。" %
                         (row["name"], domain.get("min"), domain.get("max"), domain.get("unit", "")),
                         suggested_fix="修改参数表并重新核对方法适用性。",
                         supporting=support)
    if bad_unit:
        row = bad_unit[0]
        return make_item(defn, "conflict", ev,
                         "%s 的单位与参数域单位不一致且无法换算：%s。" %
                         (row["name"], row.get("conversion_note")),
                         required_condition="统一单位并重新比较，或提供单位换算依据。",
                         suggested_fix="在参数表中同时写明单位与换算关系。",
                         supporting=support)
    if no_domain:
        names = "、".join(row["name"] for row in no_domain)
        return make_item(defn, "uncertain", ev,
                         "以下参数没有对应参数域，无法判断是否越界：%s。" % names,
                         required_condition="补充这些参数的允许范围或设备边界。",
                         suggested_fix="为每个参数补充上下限与依据来源。",
                         supporting=support)
    return make_item(defn, "satisfied", ev,
                     "全部可比参数均在有限参数域内（共 %d 项）。" % len(results),
                     suggested_fix="保持参数值不变；变更设备或方法时重核参数域。",
                     supporting=support)


def eval_risks(ctx, defn):
    risk_doc, risk_sec, risk_line, risk_text = find_content_line(ctx["docs"],
        ("风险", "异常", "故障", "应急", "risk", "failure", "exception", "troubleshoot"))
    fb_doc, fb_sec, fb_line, fb_text = find_content_line(ctx["docs"],
        ("降级", "替代", "备用", "转人工", "停机", "复测", "更换", "fallback", "contingency", "backup"))
    ev = ctx["pool"].add_line(risk_doc, risk_line, risk_sec) if risk_doc else (
        ctx["pool"].add_line(fb_doc, fb_line, fb_sec) if fb_doc else absence_evidence(ctx["docs"], ("风险",), ctx["pool"]))
    support = []
    if fb_doc and (not risk_doc or fb_doc is not risk_doc or fb_line != risk_line):
        ev2 = ctx["pool"].add_line(fb_doc, fb_line, fb_sec)
        if ev2:
            support.append(ev2)
    if risk_doc and fb_doc:
        return make_item(defn, "satisfied", ev,
                         "方案同时给出风险项与可执行降级/替代/转人工路径。",
                         suggested_fix="为每条风险绑定触发阈值、责任人与转人工节点。",
                         supporting=support)
    if risk_doc:
        return make_item(defn, "partial", ev,
                         "方案列出风险，但未给出可执行的降级路径或转人工节点。",
                         required_condition="为每条风险补充降级路径、替代方案与转人工节点。",
                         suggested_fix="新增异常处置表：触发条件→动作→责任人→记录。",
                         supporting=support)
    return make_item(defn, "missing", ev,
                     "未找到风险与异常处置内容；未写不等于不会发生。",
                     required_condition="补充设备故障、批次差异、样本不足、参数越界等风险与处置。",
                     suggested_fix="新增风险与异常章节。")


EVALUATORS = {
    "hypothesis": eval_hypothesis,
    "controls": eval_controls,
    "equipment": eval_equipment,
    "materials": eval_materials,
    "samples": eval_samples,
    "time": eval_time,
    "ethics": eval_ethics,
    "parameters": eval_parameters,
    "risks": eval_risks,
}


def eval_generic(ctx, defn):
    blob = " ".join(doc.get("text", "") for doc in ctx["docs"]).lower()
    category = str(defn.get("category") or "")
    if category and category.lower() in blob:
        ev = absence_evidence(ctx["docs"], (category,), ctx["pool"])
        return make_item(defn, "partial", ev,
                         "方案中出现“%s”相关表述，但无法按内置规则逐条判定。" % category,
                         required_condition="按检查项问题补充可核验原文与参数。",
                         suggested_fix="把该检查项改写成可定位的章节或参数行。")
    ev = absence_evidence(ctx["docs"], (category,), ctx["pool"])
    return make_item(defn, "uncertain", ev,
                     "该检查项没有专用判定规则，且未找到足够原文，按不确定处理。",
                     required_condition="人工确认该检查项是否适用于本方案。",
                     suggested_fix="在案例中提供该检查项的判定口径。")


# ---------------------------------------------------------------------------
# Review assembly
# ---------------------------------------------------------------------------

def case_text(state):
    parts = [doc.get("text") or "" for doc in state.get("docs", [])]
    case = state.get("case") or {}
    for key in ("goal", "objective", "task", "task_instruction", "title"):
        if isinstance(case.get(key), str):
            parts.append(case[key])
    if state.get("task_text"):
        parts.append(state["task_text"])
    return "\n".join(parts)


def severity_counts(items):
    counts = {"blocker": 0, "major": 0, "minor": 0, "info": 0}
    for item in items:
        key = item.get("severity") or "major"
        counts[key] = counts.get(key, 0) + 1
    return counts


def decide_conclusion(items, has_material):
    if not has_material:
        return "信息不足"
    blockers = [item for item in items if item.get("verdict") != "satisfied" and item.get("severity") == "blocker"]
    if blockers:
        return "不可行"
    if any(item.get("verdict") != "satisfied" for item in items):
        return "有条件可行"
    return "可行"


def build_review(state):
    pool = EvidencePool(state["input_dir"])
    docs = protocol_docs(state)
    if not docs:
        docs = [doc for doc in state.get("docs", []) if doc.get("sections")]
    case = state.get("case") or {}

    inventory = collect_inventory(state)
    mentions = find_resource_mentions(inventory, docs)
    unmatched = detect_unmatched_equipment(docs, inventory)
    time_est = estimate_time(state, pool, docs)
    samples_est = estimate_samples(state, inventory, pool, docs)
    domains = collect_domains(case)
    params = compare_parameters(parse_protocol_parameters(docs), domains)
    clauses = collect_document_clauses(case)
    e_status, _ = ethics_status(case)
    triggers = detect_triggers(case_text(state))

    ctx = {
        "state": state, "docs": docs, "inventory": inventory, "mentions": mentions,
        "unmatched": unmatched, "time": time_est, "samples": samples_est,
        "domains": domains, "params": params, "clauses": clauses,
        "ethics_status": e_status, "triggers": triggers, "pool": pool,
    }

    defs, checklist_source = load_checklist(case)
    items = []
    for defn in defs:
        key = category_key(defn.get("category"), defn.get("question"))
        evaluator = EVALUATORS.get(key, eval_generic)
        items.append(evaluator(ctx, defn))

    findings = [item for item in items if item.get("verdict") != "satisfied"]
    counts = {verdict: sum(1 for item in items if item.get("verdict") == verdict) for verdict in VERDICT_VALUES}
    counts["total"] = len(items)
    conclusion = decide_conclusion(items, bool(docs))
    conclusion_code = {
        "可行": "feasible",
        "有条件可行": "conditionally_feasible",
        "不可行": "not_feasible",
        "信息不足": "insufficient_information",
    }[conclusion]

    conditions = []
    seen_conditions = set()
    for item in findings:
        condition = item.get("required_condition")
        if condition and condition not in seen_conditions:
            seen_conditions.add(condition)
            conditions.append({
                "item_id": item.get("item_id"),
                "category": item.get("category"),
                "condition": condition,
                "severity": item.get("severity"),
            })

    conflicts = []
    for row in params:
        if row.get("status") == "out_of_range":
            conflicts.append({
                "kind": "parameter_out_of_range",
                "parameter": row.get("name"),
                "value": row.get("value"),
                "unit": row.get("unit"),
                "domain": row.get("domain"),
                "locator": row.get("locator"),
                "quote": row.get("quote"),
                "detail": "%s=%g %s 超出参数域" % (row.get("name"), row.get("value") or 0, row.get("unit") or ""),
            })
        elif row.get("status") == "unit_inconsistent":
            conflicts.append({
                "kind": "unit_inconsistent",
                "parameter": row.get("name"),
                "locator": row.get("locator"),
                "quote": row.get("quote"),
                "detail": row.get("conversion_note"),
            })
    if time_est.get("status") == "exceeds_window":
        conflicts.append({
            "kind": "time_exceeds_window",
            "detail": "计划 %g h > 时间窗 %g h" % (time_est.get("total_hours") or 0, time_est.get("window_hours") or 0),
            "formula": time_est.get("formula"),
            "locator": time_est.get("window_locator"),
        })
    if time_est.get("arithmetic_mismatch"):
        conflicts.append({
            "kind": "arithmetic_mismatch",
            "detail": "分项合计 %g h 与声明总时长 %g h 不一致" %
                      (time_est.get("total_hours") or 0, time_est.get("declared_total_hours") or 0),
            "locator": time_est.get("declared_locator"),
        })
    if samples_est.get("status") == "insufficient":
        conflicts.append({
            "kind": "sample_shortage",
            "detail": "可得 %s < 需求 %s，缺口 %s（%s）" %
                      (samples_est.get("available"), samples_est.get("required_effective"),
                       samples_est.get("shortfall"), samples_est.get("formula")),
            "locator": samples_est.get("evidence", {}).get("locator"),
            "quote": samples_est.get("evidence", {}).get("quote"),
        })
    for row in unmatched:
        conflicts.append({
            "kind": "unmatched_resource",
            "detail": "型号 %s 未在资源清单中出现" % row.get("model"),
            "locator": row.get("locator"),
            "quote": row.get("quote"),
        })
    if e_status == "已拒绝":
        conflicts.append({"kind": "ethics_rejected", "detail": "伦理审批被拒", "locator": "case.json#/ethics"})

    missing_info = []
    if not docs:
        missing_info.append("可读的方案材料（markdown/text/json/csv）")
    if not case:
        missing_info.append("case.json")
    if time_est.get("status") in ("no_explicit_numbers", "window_not_provided"):
        missing_info.append("明确的步骤时长或时间窗")
    if samples_est.get("status") in ("requirement_not_explicit", "availability_unknown"):
        missing_info.append("样本数/组数/重复数或可得样本量")
    if not domains:
        missing_info.append("参数域或设备/安全边界")
    if e_status in ("未声明", "已声明但状态不明") and triggers:
        missing_info.append("伦理/安全审批状态与批件编号")
    for row in unmatched:
        missing_info.append("资源清单中的型号 %s" % row.get("model"))

    uncertainty = []
    if not docs:
        uncertainty.append({"kind": "no_material", "item": "protocol",
                            "detail": "输入中没有可读的方案材料，无法做实质审查。",
                            "resolution": "提供 protocol.md/task.md 或 case.json 内嵌方案后重跑。"})
    if state.get("case_error"):
        uncertainty.append({"kind": "case_error", "item": "case.json",
                            "detail": state["case_error"],
                            "resolution": "修正 case.json 后重跑；当前结果不推断缺失字段。"})
    if not inventory:
        uncertainty.append({"kind": "no_inventory", "item": "resources",
                            "detail": "案例未提供资源/库存清单，资源状态按未知处理。",
                            "resolution": "补充设备、材料、样本清单后重跑。"})
    if not domains:
        uncertainty.append({"kind": "no_parameter_domain", "item": "parameter_domains",
                            "detail": "未给出有限参数域，参数越界无法判定。",
                            "resolution": "补充参数上下限或设备/安全边界。"})
    if time_est.get("status") == "window_not_provided":
        uncertainty.append({"kind": "no_time_window", "item": "time_window_h",
                            "detail": "未给出时间窗，无法判断排期是否可行。",
                            "resolution": "补充截止时间或机时窗口。"})
    if e_status == "未声明" and triggers:
        uncertainty.append({"kind": "ethics_unknown", "item": "ethics",
                            "detail": "检出伦理触发项但未声明审批状态；不得视为已批准。",
                            "resolution": "补充伦理/安全审批状态与批件编号。"})
    for row in unmatched:
        uncertainty.append({"kind": "unmatched_resource", "item": row.get("model"),
                            "detail": "型号未在资源清单中匹配，按未知处理。",
                            "resolution": "在清单中补充该型号或改用清单内型号。"})
    known_details = " ".join(str(item.get("detail", "")) for item in uncertainty)
    for row in conflicts:
        detail = row.get("detail") or row.get("kind") or ""
        if detail and detail in known_details:
            continue
        uncertainty.append({"kind": "open_conflict", "item": row.get("kind"),
                            "detail": detail,
                            "resolution": "先按 required_conditions 修正该冲突来源再重跑；冲突未关闭前结论不视为可直接执行。"})
    for missing in missing_info:
        if missing and missing in known_details:
            continue
        uncertainty.append({"kind": "missing_information", "item": missing,
                            "detail": "材料中未给出该项，相关判断按最保守处理。",
                            "resolution": "补充该项后重跑；在此之前不得把对应检查项视为满足。"})

    verified_count = pool.verify_all()
    summary = "审查 %d 项：满足 %d，部分满足 %d，缺失 %d，冲突 %d，不确定 %d；结论：%s。" % (
        counts["total"], counts["satisfied"], counts["partial"], counts["missing"],
        counts["conflict"], counts["uncertain"], conclusion,
    )
    if conditions:
        summary += "需先补条件：" + "；".join(item["condition"] for item in conditions[:4])
        if len(conditions) > 4:
            summary += " 等 %d 项" % len(conditions)

    resource_counts = {"已具备": 0, "可外协": 0, "需采购": 0, "不具备": 0, "未知": 0}
    for row in mentions:
        key = row.get("status") if row.get("status") in resource_counts else "未知"
        resource_counts[key] += 1
    resources = {
        "items": mentions,
        "counts": resource_counts,
        "unmatched_mentions": unmatched,
        "conditions": [row for row in mentions if row.get("status") in ("可外协", "需采购", "不具备", "未知")],
        "basis": "资源状态来自案例清单；清单缺失时记未知，不默认已具备。",
    }

    blockers = [item for item in items if item.get("severity") == "blocker"]
    verdict_summary = {
        "conclusion": conclusion,
        "conclusion_code": conclusion_code,
        "counts": counts,
        "severity_counts": severity_counts(items),
        "blocker_total": len(blockers),
        "blocker_unmet": sum(1 for item in blockers if item.get("verdict") != "satisfied"),
        "findings": len(findings),
        "total_items": len(items),
        "rule": "任一 blocker 未满足→不可行；否则任一未满足→有条件可行；全部满足→可行。",
    }

    metadata = {
        "skill": "experimental-plan-checklist-review",
        "version": VERSION,
        "rules_version": RULES_VERSION,
        "deterministic": True,
        "checklist_source": checklist_source,
        "input_files": state.get("files", []),
        "case_sha256": state.get("case_sha256"),
        "materials": len(docs),
    }

    run_log = [
        {"step": "discover_input", "detail": "case=%s; docs=%d; files=%d" %
         (os.path.basename(state.get("case_path") or "none"), len(docs), len(state.get("files", [])))},
        {"step": "load_checklist", "detail": "source=%s; items=%d" % (checklist_source, len(defs))},
        {"step": "cross_check_resources", "detail": "inventory=%d; mentioned=%d; unmatched=%d" %
         (len(inventory), sum(1 for row in mentions if row.get("mentioned_in_protocol")), len(unmatched))},
        {"step": "estimate_time", "detail": "status=%s; total=%s; window=%s" %
         (time_est.get("status"), time_est.get("total_hours"), time_est.get("window_hours"))},
        {"step": "estimate_samples", "detail": "status=%s; required=%s; available=%s" %
         (samples_est.get("status"), samples_est.get("required_effective"), samples_est.get("available"))},
        {"step": "evaluate_checklist", "detail": "items=%d; findings=%d" % (len(items), len(findings))},
        {"step": "verify_evidence", "detail": "verified=%d; total=%d" % (verified_count, len(pool.items))},
    ]

    status = "answered"
    status_reason = "review_complete"
    if not docs:
        status = "insufficient_evidence"
        status_reason = "no_readable_protocol_material"
    elif state.get("case_error"):
        status = "input_error"
        status_reason = state["case_error"]

    result = {
        "case_id": str(case.get("case_id") or ""),
        "status": status,
        "status_reason": status_reason,
        "verdict_summary": verdict_summary,
        "conclusion": conclusion,
        "summary": summary,
        "checklist": items,
        "findings": findings,
        "resources": resources,
        "estimates": {"time": time_est, "samples": samples_est, "parameters": params},
        "conflicts": conflicts,
        "missing_info": missing_info,
        "required_conditions": conditions,
        "evidence": pool.items,
        "uncertainty": uncertainty,
        "metadata": metadata,
        "run_log": run_log,
    }

    problems = self_check(result)
    if problems:
        result["status"] = "partial"
        result["status_reason"] = "self_check: " + "; ".join(problems[:3])
        for problem in problems:
            result["uncertainty"].append({
                "kind": "self_check", "item": "result", "detail": problem,
                "resolution": "需人工复核后再视为完成。",
            })

    result = fill_contract(result, case)
    result["run_log"].append({"step": "write_outputs", "detail": "result.json; run-review.md"})
    return result


def self_check(result):
    problems = []
    items = result.get("checklist") or []
    findings = result.get("findings") or []
    counts = (result.get("verdict_summary") or {}).get("counts") or {}
    if counts.get("total") != len(items):
        problems.append("counts.total 与 checklist 长度不一致")
    for verdict in VERDICT_VALUES:
        actual = sum(1 for item in items if item.get("verdict") == verdict)
        if counts.get(verdict) != actual:
            problems.append("counts.%s 与条目不一致" % verdict)
    if len(findings) != len([item for item in items if item.get("verdict") != "satisfied"]):
        problems.append("findings 与未满足条目数不一致")
    for item in findings:
        ev = item.get("evidence") or {}
        if not ev.get("locator") or not ev.get("quote"):
            problems.append("%s 缺少 locator/quote" % item.get("item_id"))
        elif ev.get("verified") is False:
            problems.append("%s 的引文未能按 locator 复核" % item.get("item_id"))
        if not item.get("required_condition"):
            problems.append("%s 未给出需补条件" % item.get("item_id"))
    expected = decide_conclusion(items, bool(result.get("metadata", {}).get("materials")))
    actual = (result.get("verdict_summary") or {}).get("conclusion")
    if expected != actual:
        problems.append("结论与计数规则不一致")
    time_est = (result.get("estimates") or {}).get("time") or {}
    if time_est.get("total_hours") is not None and not time_est.get("formula"):
        problems.append("时间总量缺少算式")
    samples_est = (result.get("estimates") or {}).get("samples") or {}
    if samples_est.get("required_computed") is not None and not samples_est.get("formula"):
        problems.append("样本总量缺少算式")
    return problems


# ---------------------------------------------------------------------------
# Human-readable review
# ---------------------------------------------------------------------------

def md_escape(value):
    return norm_space(value).replace("|", "\\|")


def write_review(result, out_dir):
    lines = []
    lines.append("# 实验方案审查报告（自动生成，供人工复核）")
    lines.append("")
    lines.append("- case_id: `%s`" % (result.get("case_id") or "unknown"))
    lines.append("- status: `%s`" % result.get("status"))
    lines.append("- 结论: **%s**" % result.get("conclusion"))
    lines.append("- 契约键: %s" % (", ".join((result.get("contract") or {}).get("required_fields", [])) or "未声明"))
    lines.append("")
    summary = result.get("verdict_summary") or {}
    counts = summary.get("counts") or {}
    lines.append("## 1. 结论统计")
    lines.append("")
    lines.append("| 满足 | 部分满足 | 缺失 | 冲突 | 不确定 | 合计 |")
    lines.append("|---|---|---|---|---|---|")
    lines.append("| %s | %s | %s | %s | %s | %s |" % (
        counts.get("satisfied", 0), counts.get("partial", 0), counts.get("missing", 0),
        counts.get("conflict", 0), counts.get("uncertain", 0), counts.get("total", 0)))
    lines.append("")
    lines.append("判定规则：%s" % summary.get("rule", ""))
    lines.append("")
    lines.append("## 2. 逐项检查")
    lines.append("")
    lines.append("| 项 | 类别 | 判定 | 严重度 | 证据定位 | 可复核 |")
    lines.append("|---|---|---|---|---|---|")
    for item in result.get("checklist") or []:
        ev = item.get("evidence") or {}
        lines.append("| %s | %s | %s | %s | `%s` | %s |" % (
            md_escape(item.get("item_id")), md_escape(item.get("category")),
            md_escape(item.get("verdict_zh")), md_escape(item.get("severity_zh")),
            md_escape(ev.get("locator")), "是" if ev.get("verified") else "否"))
    lines.append("")
    lines.append("## 3. 发现与需补条件")
    lines.append("")
    if not result.get("findings"):
        lines.append("无未满足项。")
    for item in result.get("findings") or []:
        ev = item.get("evidence") or {}
        lines.append("### %s %s（%s / %s）" % (item.get("item_id"), item.get("category"),
                                              item.get("verdict_zh"), item.get("severity_zh")))
        lines.append("")
        lines.append("- 理由：%s" % item.get("rationale"))
        lines.append("- 定位：`%s`" % ev.get("locator"))
        lines.append("- 原文：> %s" % ev.get("quote"))
        lines.append("- 需补条件：%s" % item.get("required_condition"))
        lines.append("- 建议修改：%s" % item.get("suggested_fix"))
        lines.append("")
    lines.append("## 4. 资源核验")
    lines.append("")
    resources = result.get("resources") or {}
    lines.append("状态统计：%s" % json.dumps(resources.get("counts") or {}, ensure_ascii=False))
    lines.append("")
    lines.append("| 资源 | 类别 | 状态 | 清单定位 | 方案提及 |")
    lines.append("|---|---|---|---|---|")
    for row in resources.get("items") or []:
        lines.append("| %s | %s | %s | `%s` | %s |" % (
            md_escape(row.get("name")), md_escape(row.get("category")),
            md_escape(row.get("status")), md_escape(row.get("source_locator")),
            "是" if row.get("mentioned_in_protocol") else "否"))
    lines.append("")
    lines.append("## 5. 时间与样本估算")
    lines.append("")
    time_est = (result.get("estimates") or {}).get("time") or {}
    samples_est = (result.get("estimates") or {}).get("samples") or {}
    lines.append("- 时间：%s；算式：`%s`；时间窗：%s h；判定：%s" % (
        time_est.get("status"), time_est.get("formula"), time_est.get("window_hours"), time_est.get("status")))
    for comp in time_est.get("components") or []:
        lines.append("  - %s %s：%g h @ `%s`" % (comp.get("phase"), comp.get("label"),
                                                  comp.get("hours"), comp.get("locator")))
    lines.append("- 样本：可得 %s，需求 %s；算式：`%s`；判定：%s" % (
        samples_est.get("available"), samples_est.get("required_effective"),
        samples_est.get("formula"), samples_est.get("status")))
    lines.append("")
    lines.append("## 6. 定位复核")
    lines.append("")
    verified = sum(1 for ev in result.get("evidence") or [] if ev.get("verified"))
    total = len(result.get("evidence") or [])
    lines.append("已按 locator 回读输入文件复核：%d/%d 条引文可定位。" % (verified, total))
    lines.append("")
    for ev in result.get("evidence") or []:
        lines.append("- [%s] `%s` %s" % ("x" if ev.get("verified") else " ", ev.get("locator"),
                                          "可定位" if ev.get("verified") else "需人工复核"))
    lines.append("")
    lines.append("## 7. 不确定性与缺失信息")
    lines.append("")
    for item in result.get("uncertainty") or []:
        lines.append("- %s：%s（处理：%s）" % (item.get("item"), item.get("detail"), item.get("resolution")))
    if not result.get("uncertainty"):
        lines.append("- 无")
    lines.append("")
    lines.append("## 8. 自检提示")
    lines.append("")
    lines.append("1. 对每条 finding，按 `locator` 回到输入文件核对 `quote` 是否为连续原文。")
    lines.append("2. 核对结论与计数：任一 blocker 未满足应为不可行；否则有未满足项应为有条件可行。")
    lines.append("3. 核对时间/样本算式只使用输入明示数字，不补充任何外部数值。")
    lines.append("4. 如人工补充了判断，请同步更新 `result.json` 的 checklist/findings/uncertainty。")
    lines.append("")
    write_text(os.path.join(out_dir, "run-review.md"), "\n".join(lines))


def degraded_result(state, reason):
    checklist = []
    template, source = template_checklist()
    for defn in template:
        checklist.append(make_item(defn, "uncertain", {
            "locator": "", "quote": "", "source": "", "section": "", "kind": "none", "verified": False,
        }, "输入不可用，无法按原文判定。", required_condition="提供可读的方案与 case.json 后重跑。",
            suggested_fix="修复输入后重跑入口脚本。"))
    counts = {"satisfied": 0, "partial": 0, "missing": 0, "conflict": 0, "uncertain": len(checklist), "total": len(checklist)}
    summary = "审查 %d 项：输入不足，全部按不确定处理；结论：信息不足。" % len(checklist)
    result = {
        "case_id": str((state.get("case") or {}).get("case_id") or ""),
        "status": "insufficient_evidence" if reason in ("no_case", "no_material") else "input_error",
        "status_reason": reason,
        "verdict_summary": {
            "conclusion": "信息不足", "conclusion_code": "insufficient_information",
            "counts": counts, "severity_counts": severity_counts(checklist),
            "findings": len(checklist), "total_items": len(checklist),
            "rule": "无可读输入时不判定可行/不可行，统一记为信息不足。",
        },
        "conclusion": "信息不足",
        "summary": summary,
        "checklist": checklist,
        "findings": checklist,
        "resources": {"items": [], "counts": {}, "unmatched_mentions": [], "conditions": []},
        "estimates": {"time": {"status": "unknown", "total_hours": None, "formula": None},
                      "samples": {"status": "unknown", "available": None, "required_effective": None, "formula": None},
                      "parameters": []},
        "conflicts": [],
        "missing_info": ["可读的 /input/case.json 与方案材料"],
        "required_conditions": [{"item_id": "INPUT", "category": "输入", "condition": "提供可读输入后重跑。", "severity": "blocker"}],
        "evidence": [],
        "uncertainty": [{
            "kind": "input_error" if result_status_error(reason) else "no_material",
            "item": "input", "detail": reason,
            "resolution": "确认 /input 下存在 case.json 与至少一份方案材料（md/txt/json/csv）。",
        }],
        "metadata": {"skill": "experimental-plan-checklist-review", "version": VERSION,
                     "rules_version": RULES_VERSION, "deterministic": True,
                     "checklist_source": source, "input_files": state.get("files", []),
                     "case_sha256": state.get("case_sha256"), "materials": 0},
        "run_log": [{"step": "discover_input", "detail": reason},
                    {"step": "write_outputs", "detail": "result.json; run-review.md"}],
    }
    return fill_contract(result, state.get("case") or {})


def result_status_error(reason):
    return reason not in ("no_case", "no_material")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def resolve_outputs(out_value):
    out_value = out_value or "/app/output"
    if out_value.lower().endswith(".json"):
        result_path = os.path.abspath(out_value)
        out_dir = os.path.dirname(result_path)
    else:
        out_dir = os.path.abspath(out_value)
        result_path = os.path.join(out_dir, "result.json")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir, result_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Checklist-based experimental protocol feasibility review.")
    parser.add_argument("--input", default="/input", help="input directory containing case.json and material")
    parser.add_argument("--work", default="/app/work", help="working directory for logs")
    parser.add_argument("--out", "--output", dest="out", default="/app/output",
                        help="output directory, or a .json file path")
    args = parser.parse_args(argv)

    input_dir = args.input
    if os.path.isfile(input_dir):
        input_dir = os.path.dirname(os.path.abspath(input_dir))
    out_dir, result_path = resolve_outputs(args.out)
    try:
        os.makedirs(args.work, exist_ok=True)
    except OSError:
        pass

    state = {"input_dir": input_dir, "case": {}, "case_error": "no_case", "files": []}
    try:
        state = discover_inputs(input_dir)
        if not state.get("case") and not state.get("docs"):
            reason = state.get("case_error") or "no_case"
            if reason in ("case_file_not_found", "input_directory_not_found"):
                reason = "no_case"
            result = degraded_result(state, reason)
        elif not state.get("docs"):
            result = degraded_result(state, "no_material")
        else:
            result = build_review(state)
    except Exception as exc:  # never crash the harness
        result = degraded_result(state, "runtime_error: %s: %s" % (type(exc).__name__, exc))
        try:
            write_text(os.path.join(args.work, "entry-error.log"), "%s: %s\n" % (type(exc).__name__, exc))
        except OSError:
            pass

    try:
        write_json(result_path, result)
        write_review(result, out_dir)
    except OSError as exc:
        sys.stderr.write("cannot write output: %s\n" % exc)
        return 0

    sys.stdout.write(json.dumps({
        "case_id": result.get("case_id"),
        "status": result.get("status"),
        "conclusion": result.get("conclusion"),
        "checklist": len(result.get("checklist") or []),
        "findings": len(result.get("findings") or []),
        "result": result_path,
    }, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as exc:  # last-resort guard
        try:
            out_dir, result_path = resolve_outputs("/app/output")
            write_json(result_path, {
                "case_id": "", "status": "input_error",
                "status_reason": "unhandled_exception: %s" % type(exc).__name__,
                "conclusion": "信息不足", "summary": "入口异常，未产生实质审查。",
                "checklist": [], "findings": [], "resources": {}, "estimates": {},
                "conflicts": [], "missing_info": ["入口异常"], "required_conditions": [],
                "evidence": [], "uncertainty": [{"kind": "runtime_error", "item": "entry",
                                                 "detail": str(exc), "resolution": "查看 work/entry-error.log"}],
                "contract_extras": {},
            })
        except OSError:
            pass
        sys.exit(0)
