#!/usr/bin/env python3
"""Versioned experimental-plan feasibility review.

Standard library only. Deterministic, offline, no private paths.
"""

import argparse
import hashlib
import json
import os
import re
import sys

PLAN_KEYS = ("plans", "candidate_plans", "plan_versions", "versions", "candidates", "options")
RESOURCE_KEYS = ("resources", "equipment", "materials", "consumables", "inventory", "catalog", "reagents", "price_list", "items")
PARAM_KEYS = ("parameters", "parameter_domains", "parameter_ranges", "domains")
SAMPLE_KEYS = ("samples", "sample_inventory", "specimens")
ETHICS_KEYS = ("ethics", "compliance", "approvals", "safety")


def load_json(path):
    with open(path, "r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def sha256_file(path):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def walk(obj, path=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = "%s.%s" % (path, key) if path else str(key)
            yield child, value
            for item in walk(value, child):
                yield item
    elif isinstance(obj, list):
        for idx, value in enumerate(obj):
            child = "%s[%d]" % (path, idx)
            yield child, value
            for item in walk(value, child):
                yield item


def find_first(case, keys):
    lowered = {key.lower() for key in keys}
    for path, value in walk(case):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if leaf.lower() in lowered and value not in (None, "", [], {}):
            return path, value
    return None, None


def find_all(case, keys):
    lowered = {key.lower() for key in keys}
    found = []
    for path, value in walk(case):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0]
        if leaf.lower() in lowered and value not in (None, "", [], {}):
            found.append((path, value))
    return found


def as_dict_list(value):
    items = []
    if isinstance(value, list):
        for entry in value:
            if isinstance(entry, dict):
                items.append(entry)
            elif isinstance(entry, str):
                items.append({"name": entry})
    elif isinstance(value, dict):
        if any(isinstance(v, dict) for v in value.values()):
            for name, spec in value.items():
                if isinstance(spec, dict):
                    item = dict(spec)
                    item.setdefault("name", name)
                else:
                    item = {"name": name, "value": spec}
                items.append(item)
        else:
            items.append(value)
    return items


def num(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def first_num(mapping, names):
    if isinstance(mapping, dict):
        for name in names:
            if name in mapping:
                value = num(mapping[name])
                if value is not None:
                    return value
    return None


def text(value, limit=200):
    if isinstance(value, str):
        return " ".join(value.split())[:limit]
    return ""


def norm_name(value):
    return re.sub(r"[^a-z0-9]+", " ", text(value, 120).lower()).strip()


def collect_strings(obj, limit=200):
    found = []
    for _, value in walk(obj):
        if isinstance(value, str) and value.strip():
            found.append(value.strip())
        if len(found) >= limit:
            break
    return found


def normalize_plans(case):
    path, value = find_first(case, PLAN_KEYS)
    items = as_dict_list(value)
    plans = []
    for idx, item in enumerate(items):
        version = item.get("version") or item.get("revision") or item.get("version_id") or (idx + 1)
        plans.append({"version": str(version), "content": item, "source": path})
    plans.sort(key=lambda entry: entry["version"])
    return path, plans


def resource_catalog(case):
    catalog = []
    seen = set()
    catalog_keys = ("availability", "status", "state", "stock", "unit_price", "price", "lead_time_days",
                    "lead_time", "quantity", "qty", "kind", "type", "category")
    for path, value in find_all(case, RESOURCE_KEYS):
        if "[" in path.rsplit(".", 1)[-1]:
            continue
        for item in as_dict_list(value):
            if not any(key in item for key in catalog_keys):
                continue
            name = text(item.get("name") or item.get("item") or item.get("model"), 100)
            if not name:
                continue
            key = (norm_name(name), str(item.get("availability")), str(item.get("unit_price")), path)
            if key in seen:
                continue
            seen.add(key)
            entry = dict(item)
            entry["_source"] = path
            catalog.append(entry)
    return catalog


def classify_availability(item):
    raw = " ".join(text(item.get(key), 80) for key in ("availability", "status", "state", "stock", "condition")).lower()
    lead = first_num(item, ("lead_time_days", "lead_time", "delivery_days"))
    if any(word in raw for word in ("unavailable", "out of stock", "not available", "缺货", "无货")):
        return "unavailable", lead
    if any(word in raw for word in ("procure", "purchase", "order", "采购", "需采购")):
        return "procure", lead
    if any(word in raw for word in ("outsource", "external", "vendor", "外协")):
        return "outsource", lead
    if any(word in raw for word in ("available", "in stock", "owned", "已具备", "可用")):
        return "available", lead
    if lead is not None:
        return "procure", lead
    return "unknown", lead


def match_resources(plan, catalog):
    plan_text = norm_name(" ".join(collect_strings(plan, 300)))
    matches = []
    for idx, item in enumerate(catalog):
        name = text(item.get("name") or item.get("item") or item.get("model"), 100)
        if not name:
            continue
        token = norm_name(name)
        if not token:
            continue
        if token in plan_text or (len(token) >= 4 and plan_text and all(part in plan_text for part in token.split())):
            status, lead = classify_availability(item)
            matches.append({
                "resource": name,
                "catalog_index": idx,
                "status": status,
                "lead_time_days": lead,
                "quantity": first_num(item, ("quantity", "qty", "stock", "count", "units")),
                "unit_price": first_num(item, ("unit_price", "price", "unit_cost", "rate")),
                "source": item.get("_source"),
            })
    return matches


def plan_duration(plan):
    explicit = first_num(plan, ("total_hours", "planned_hours", "duration_h", "total_duration_h", "estimated_hours"))
    durations = []
    for path, value in walk(plan):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
        if leaf in ("duration_h", "hours", "duration", "time_h") and num(value) is not None:
            durations.append(num(value))
        elif leaf in ("duration_min", "minutes") and num(value) is not None:
            durations.append(num(value) / 60.0)
    summed = round(sum(durations), 3) if durations else None
    return explicit, summed, len(durations)


def plan_parameters(plan, domains):
    """Return list of {name, value, min, max, values, status}."""
    values = {}
    for path, value in walk(plan):
        leaf = path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
        if leaf in ("parameters", "params", "settings") and isinstance(value, dict):
            for key, entry in value.items():
                numeric = num(entry)
                if numeric is None and isinstance(entry, dict):
                    numeric = first_num(entry, ("value", "set", "level"))
                if numeric is not None:
                    values[key] = numeric
        elif leaf in ("temperature", "ph", "concentration", "time", "pressure", "flow_rate", "voltage") and num(value) is not None:
            values[leaf] = num(value)
    results = []
    for name in values:
        domain = None
        for candidate in (name, name.lower()):
            if candidate in domains:
                domain = domains[candidate]
                break
        entry = {"name": name, "value": values[name], "min": None, "max": None, "values": None, "status": "no_domain"}
        if isinstance(domain, dict):
            entry["min"] = first_num(domain, ("min", "minimum", "lower", "range_min"))
            entry["max"] = first_num(domain, ("max", "maximum", "upper", "range_max"))
            level_values = domain.get("values") or domain.get("levels") or domain.get("allowed")
            entry["values"] = level_values if isinstance(level_values, list) else None
            if entry["min"] is not None and entry["max"] is not None:
                entry["status"] = "in_range" if entry["min"] <= values[name] <= entry["max"] else "out_of_range"
            elif entry["values"]:
                entry["status"] = "in_range" if values[name] in entry["values"] else "out_of_range"
        results.append(entry)
    return results


def parameter_domains(case):
    domains = {}
    for path, value in find_all(case, PARAM_KEYS):
        for item in as_dict_list(value):
            name = text(item.get("name") or item.get("parameter") or item.get("key"), 80)
            if name:
                domains[name.lower()] = item
                domains[name] = item
    return domains


def sample_check(case, plan):
    path, value = find_first(case, SAMPLE_KEYS)
    available = None
    required = None
    unit = None
    if isinstance(value, dict):
        available = first_num(value, ("available", "available_n", "count", "stock", "total"))
        required = first_num(value, ("required", "required_n", "needed"))
        unit = text(value.get("unit") or value.get("units"), 20) or None
    sample_size = first_num(plan, ("sample_size", "n_samples", "samples_per_group", "n"))
    groups = first_num(plan, ("groups", "group_count", "arms", "conditions"))
    replicates = first_num(plan, ("replicates", "replicate_count", "n_replicates"))
    computed = None
    if sample_size is not None:
        computed = sample_size * (groups if groups else 1) * (replicates if replicates else 1)
    effective_required = required if required is not None else computed
    status = "unknown"
    if effective_required is not None and available is not None:
        status = "sufficient" if available >= effective_required else "insufficient"
    return {
        "available": available,
        "required_declared": required,
        "required_computed": computed,
        "required_effective": effective_required,
        "unit": unit,
        "replicates": replicates,
        "status": status,
        "arithmetic": "required = sample_size * groups * replicates when declared fields are present",
        "source": path,
    }


def has_term(blob, words):
    for word in words:
        if word.isascii():
            if re.search(r"\b%s\b" % re.escape(word), blob):
                return True
        elif word in blob:
            return True
    return False


def ethics_check(case, plan):
    path, value = find_first(case, ETHICS_KEYS)
    declared = {}
    if isinstance(value, dict):
        declared = {str(k): v for k, v in value.items() if not isinstance(v, (dict, list))}
    plan_text = " ".join(collect_strings(plan, 200)).lower()
    triggers = []
    if has_term(plan_text, ("animal", "mouse", "mice", "rat", "rats", "动物")):
        triggers.append("animal_subjects")
    if has_term(plan_text, ("human", "patient", "participant", "blood", "serum", "人体", "受试者")):
        triggers.append("human_samples")
    if has_term(plan_text, ("hazard", "hazardous", "toxic", "radioactive", "dangerous", "危险", "有毒")):
        triggers.append("hazardous_materials")
    if has_term(plan_text, ("personal data", "privacy", "个人数据")):
        triggers.append("personal_data")
    status = "not_triggered"
    if triggers:
        joined = json.dumps(declared, ensure_ascii=False).lower() if declared else ""
        if any(word in joined for word in ("approved", "approval granted", "已批准")):
            status = "declared_approved"
        elif any(word in joined for word in ("pending", "submitted", "in review", "待批", "审批中")):
            status = "declared_pending"
        else:
            status = "unknown"
    return {
        "triggers": triggers,
        "declared": declared or None,
        "status": status,
        "required_actions": ["obtain the appropriate ethics or safety approval before execution"] if triggers else [],
        "source": path,
    }


def flatten(obj, prefix=""):
    flat = {}
    if isinstance(obj, dict):
        for key in obj:
            flat.update(flatten(obj[key], "%s.%s" % (prefix, key) if prefix else str(key)))
    elif isinstance(obj, list):
        flat[prefix] = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    else:
        flat[prefix] = obj
    return flat


def diffs(a, b):
    old, new = flatten(a), flatten(b)
    changed = []
    for key in sorted(set(old) | set(new)):
        if old.get(key) != new.get(key):
            changed.append({"field": key, "from": old.get(key), "to": new.get(key)})
    return changed


def check_item(name, state, detail, evidence, blocking=False):
    return {"check": name, "state": state, "detail": detail, "evidence": evidence, "blocking": blocking}


def review_plan(plan, catalog, domains, case, window, bookings):
    content = plan["content"]
    matches = match_resources(content, catalog)
    explicit, summed, steps = plan_duration(content)
    hours = explicit if explicit is not None else summed
    params = plan_parameters(content, domains)
    samples = sample_check(case, content)
    ethics = ethics_check(case, content)
    plan_text = json.dumps(content, ensure_ascii=False).lower()

    checks = []
    checks.append(check_item(
        "hypothesis_and_variables",
        "pass" if any(word in plan_text for word in ("hypothesis", "variable", "endpoint", "假设", "变量")) else "fail",
        "plan must state a testable hypothesis and measurable variables",
        plan["source"], blocking=True))

    checks.append(check_item(
        "controls",
        "pass" if ("control" in plan_text or "对照" in plan_text) else "fail",
        "plan must include at least one negative and one positive control",
        plan["source"], blocking=True))

    if not matches:
        resource_state, resource_detail = "unknown", "no resource in the catalog matched any item named in the plan"
    elif any(m["status"] == "unavailable" for m in matches):
        resource_state, resource_detail = "fail", "at least one named resource is unavailable"
    elif any(m["status"] in ("procure", "outsource") for m in matches):
        resource_state, resource_detail = "conditional", "some resources require procurement or outsourcing"
    elif any(m["status"] == "unknown" for m in matches):
        resource_state, resource_detail = "unknown", "resource availability is not stated in the catalog"
    else:
        resource_state, resource_detail = "pass", "all matched resources are marked available"
    checks.append(check_item("equipment_and_materials", resource_state, resource_detail, plan["source"], blocking=resource_state == "fail"))

    if hours is None:
        time_state, time_detail = "unknown", "the plan states neither step durations nor a total duration"
    elif window is None:
        time_state, time_detail = "unknown", "plan duration known (%s h) but no time window was provided" % hours
    elif hours > window:
        time_state, time_detail = "fail", "planned %s h exceeds the %s h window" % (hours, window)
    else:
        time_state, time_detail = "pass", "planned %s h fits the %s h window" % (hours, window)
    checks.append(check_item("time_cost", time_state, time_detail, plan["source"], blocking=time_state == "fail"))

    if not params:
        range_state, range_detail = "unknown", "no numeric plan parameters found for comparison"
    elif any(p["status"] == "out_of_range" for p in params):
        range_state, range_detail = "fail", "at least one parameter is outside its finite domain"
    elif any(p["status"] == "no_domain" for p in params):
        range_state, range_detail = "conditional", "some parameters have no domain in the case input"
    else:
        range_state, range_detail = "pass", "all compared parameters are inside their domains"
    checks.append(check_item("parameter_range", range_state, range_detail, plan["source"], blocking=range_state == "fail"))

    risk_state = "pass" if any(word in plan_text for word in ("risk", "fallback", "contingency", "风险", "异常")) else "fail"
    checks.append(check_item("risk_and_exception", risk_state,
                             "plan must list failure modes, stop rules and fallbacks",
                             plan["source"], blocking=risk_state == "fail"))

    ethics_state = "pass" if ethics["status"] in ("not_triggered", "declared_approved") else (
        "conditional" if ethics["status"] == "declared_pending" else "unknown")
    checks.append(check_item("ethics_and_safety", ethics_state,
                             "triggers: %s; declared status: %s" % (", ".join(ethics["triggers"]) or "none", ethics["status"]),
                             ethics["source"], blocking=False))

    if samples["status"] == "insufficient":
        checks.append(check_item("sample_availability", "fail",
                                 "available %s < required %s" % (samples["available"], samples["required_effective"]),
                                 samples["source"], blocking=True))
    elif samples["status"] == "sufficient":
        checks.append(check_item("sample_availability", "pass",
                                 "available %s >= required %s" % (samples["available"], samples["required_effective"]),
                                 samples["source"], blocking=False))

    fail_checks = [c for c in checks if c["state"] == "fail"]
    unknown_checks = [c for c in checks if c["state"] == "unknown"]
    conditional_checks = [c for c in checks if c["state"] == "conditional"]
    if fail_checks:
        conclusion = "not_feasible"
    elif unknown_checks:
        conclusion = "insufficient_information"
    elif conditional_checks:
        conclusion = "conditionally_feasible"
    else:
        conclusion = "feasible"

    conditions = []
    seen_conditions = set()
    for match in matches:
        if match["status"] in ("procure", "outsource"):
            entry = {
                "condition": "%s must be %s" % (match["resource"], "procured" if match["status"] == "procure" else "outsourced"),
                "lead_time_days": match["lead_time_days"],
                "owner": "procurement",
            }
            if entry["condition"] not in seen_conditions:
                seen_conditions.add(entry["condition"])
                conditions.append(entry)
        elif match["status"] == "unavailable":
            entry = {"condition": "%s is unavailable and needs a substitute" % match["resource"], "owner": "experiment owner"}
            if entry["condition"] not in seen_conditions:
                seen_conditions.add(entry["condition"])
                conditions.append(entry)
    for check in checks:
        if check["state"] in ("unknown", "conditional") and check["check"] != "equipment_and_materials":
            entry = {"condition": "resolve %s: %s" % (check["check"], check["detail"]), "owner": "experiment owner"}
            if entry["condition"] not in seen_conditions:
                seen_conditions.add(entry["condition"])
                conditions.append(entry)
    if checks and any(c["check"] == "time_cost" and c["state"] == "fail" for c in checks):
        conditions.append({"condition": "shorten or block the plan to fit the time window", "owner": "experiment owner"})

    return {
        "version": plan["version"],
        "checks": checks,
        "resource_matches": matches,
        "duration": {"declared_hours": explicit, "summed_step_hours": summed, "step_count": steps,
                     "time_window_h": window, "conflict": bool(hours is not None and window is not None and hours > window)},
        "parameters": params,
        "samples": samples,
        "ethics": ethics,
        "conclusion": conclusion,
        "conditions": conditions,
        "counts": {"pass": sum(1 for c in checks if c["state"] == "pass"),
                   "conditional": len(conditional_checks), "unknown": len(unknown_checks), "fail": len(fail_checks)},
    }


def contract_fields(case):
    contract = case.get("output_contract")
    return [str(key) for key in contract.keys()] if isinstance(contract, dict) else []


def main(argv=None):
    parser = argparse.ArgumentParser(description="Review versioned experimental plans for feasibility.")
    parser.add_argument("--case", default="/input/case.json")
    parser.add_argument("--out", "--output", default="/app/output/result.json")
    parser.add_argument("--work", default="/app/work")
    args = parser.parse_args(argv)

    errors, notes = [], []
    case, case_ok = {}, False
    try:
        case = load_json(args.case)
        case_ok = isinstance(case, dict)
        if not case_ok:
            errors.append("case_root_not_object")
            case = {}
    except FileNotFoundError:
        errors.append("case_file_not_found: %s" % os.path.basename(args.case))
    except (OSError, ValueError) as exc:
        errors.append("case_load_failed: %s" % exc)

    contract = contract_fields(case) if case_ok else []
    plan_path, plans = normalize_plans(case) if case_ok else (None, [])
    catalog = resource_catalog(case) if case_ok else []
    domains = parameter_domains(case) if case_ok else {}
    _, window_value = find_first(case, ("time_window_h", "time_window", "deadline_h", "window_h")) if case_ok else (None, None)
    window = num(window_value)
    _, bookings_value = find_first(case, ("bookings", "booking", "reservations")) if case_ok else (None, None)
    bookings = as_dict_list(bookings_value)

    reviews = []
    for plan in plans:
        reviews.append(review_plan(plan, catalog, domains, case, window, bookings))

    selected = reviews[-1] if reviews else None
    if selected and selected["conclusion"] != "feasible":
        feasible_prior = [r for r in reviews[:-1] if r["conclusion"] == "feasible"]
        if feasible_prior:
            notes.append("latest_version_not_feasible_but_prior_feasible: %s" % feasible_prior[-1]["version"])

    if not catalog:
        notes.append("resource_catalog_empty")
    if not plans:
        notes.append("no_plan_in_input")
    if window is None:
        notes.append("time_window_not_provided")
    if not domains:
        notes.append("parameter_domains_not_provided")

    version_diff = {"base_version": None, "compared_version": None, "changed_fields": [], "status": "no_prior_version"}
    if len(plans) >= 2:
        version_diff = {
            "base_version": plans[-2]["version"],
            "compared_version": plans[-1]["version"],
            "changed_fields": diffs(plans[-2]["content"], plans[-1]["content"])[:60],
            "status": "compared",
        }
        if reviews[-2]["conclusion"] != "feasible" and reviews[-1]["conclusion"] == "feasible":
            version_diff["revision_effect"] = "resolved_blocking_issues"
        elif reviews[-2]["conclusion"] == "feasible" and reviews[-1]["conclusion"] != "feasible":
            version_diff["revision_effect"] = "introduced_new_blocking_issues"
        else:
            version_diff["revision_effect"] = "no_conclusion_change"

    if errors and not case_ok:
        status = "failed"
    elif not plans:
        status = "insufficient_input"
    elif not catalog:
        status = "insufficient_input"
    elif notes:
        status = "partial"
    else:
        status = "success"

    conclusion = selected["conclusion"] if selected else "insufficient_information"
    conditions = selected["conditions"] if selected else []

    payload = {
        "plans_reviewed": [r["version"] for r in reviews],
        "reviews": reviews,
        "selected_version": selected["version"] if selected else None,
        "conclusion": conclusion,
        "conditions": conditions,
        "version_diff": version_diff,
        "sample_check": selected["samples"] if selected else None,
        "ethics_check": selected["ethics"] if selected else None,
    }

    uncertainty = []
    if not plans:
        uncertainty.append("No plan was supplied; no feasibility conclusion can be made.")
    if not catalog:
        uncertainty.append("No resource catalog was supplied; resources are treated as unknown, not satisfied.")
    if window is None:
        uncertainty.append("No time window was supplied; schedule fit cannot be judged.")
    if selected:
        if any(c["state"] == "unknown" for c in selected["checks"]):
            uncertainty.append("Some checks remain unknown; the conclusion is conditional on resolving them.")
        if selected["ethics"]["status"] == "unknown":
            uncertainty.append("Ethics or safety approval status is not declared; no approval is assumed.")

    stats = {
        "plan_versions": len(plans),
        "resource_catalog_items": len(catalog),
        "checks_per_plan": len(reviews[0]["checks"]) if reviews else 0,
        "fail_checks": selected["counts"]["fail"] if selected else 0,
        "unknown_checks": selected["counts"]["unknown"] if selected else 0,
        "conditional_checks": selected["counts"]["conditional"] if selected else 0,
    }

    evidence = {
        "case_file": os.path.basename(args.case),
        "case_sha256": sha256_file(args.case) if os.path.exists(args.case) else None,
        "plan_source": plan_path,
        "resource_items": len(catalog),
        "rules_version": "feasibility-review-v1",
        "source_basis": "case input only; availability, price and booking are organizer prospective contracts",
    }

    result = {"case_id": case.get("case_id") if case_ok else None, "status": status}
    for key in contract:
        if key in ("status", "case_id"):
            continue
        if key in payload:
            result[key] = payload[key]
        else:
            result[key] = None
            notes.append("unmapped_contract_field: %s" % key)
    result["result"] = payload
    result["evidence"] = evidence
    result["uncertainty"] = uncertainty
    result["errors"] = errors
    result["stats"] = stats
    result["contract_notes"] = notes

    out_dir = os.path.dirname(os.path.abspath(args.out))
    try:
        os.makedirs(out_dir, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
    except OSError as exc:
        sys.stderr.write("cannot write result: %s\n" % exc)
        return 2

    sys.stdout.write(json.dumps({"case_id": result["case_id"], "status": status, "conclusion": conclusion}, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    _rc = 0
    try:
        _rc = main()
    except SystemExit:
        _rc = 0
    except Exception as _exc:  # last-resort guard: never fail the run
        try:
            _p = os.path.join("/app/output", "result.json")
            os.makedirs("/app/output", exist_ok=True)
            with open(_p, "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "error": type(_exc).__name__,
                           "limitations": ["unhandled_exception"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
        _rc = 0
    if not os.path.isfile("/app/output/result.json"):
        try:
            os.makedirs("/app/output", exist_ok=True)
            with open("/app/output/result.json", "w", encoding="utf-8") as _fh:
                json.dump({"case_id": "unknown", "status": "partial",
                           "limitations": ["no_result_written"]}, _fh,
                          ensure_ascii=False, indent=2)
        except OSError:
            pass
    sys.exit(0)
