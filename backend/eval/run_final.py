"""End-to-end check of blocks 5-8 on the five challenge situations.

Reads the situations' prompts (D01-D05, eval/private/challenge-cases.yaml) and the expected source
documents from the challenge's cases/expected.json (not copied into this repo).

Per question it reports:
  status_ok   the mapped checklist item has the expected status (found / not documented)
  source_hit  a kept passage of that item comes from one of the expected source documents
  visible     the item is in the summary panel (answer visible without clicking)

Usage (from backend/):
  python -m eval.run_final --patient <patient dir> --expected <cases/expected.json> [--no-llm]
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import yaml
from eval.cases import load_cases

from app.prompt_analysis import PromptAnalyzer
from app.remarker import Remarker
from app.summary import Finalizer

HERE = Path(__file__).resolve().parent
SITUATION_CASE = {"1": "D01", "2": "D02", "3": "D03", "4": "D04", "5": "D05"}
# question -> checklist items that answer it, and the expected status
QUESTION_ITEMS = {
    "1.1": (["anticoagulants"], "found"),
    "1.2": (["allergies", "contrast_reaction"], "found"),
    "1.3": (["cardiac_function"], "found"),
    "2.1": (["cancer_histology", "cancer_staging"], "found"),
    "2.2": (["tumour_receptors"], "found"),
    "2.3": (["tumour_board_plan", "planned_procedures"], "found"),
    "3.1": (["glucose_lowering"], "found"),
    "3.2": (["diabetes_control"], "found"),
    "3.3": (["weight_bmi"], "found"),
    "4.1": (["prior_similar_events"], "found"),
    "4.2": (["contrast_reaction", "allergies"], "found"),
    "4.3": (["antihypertensives"], "found"),
    "5.1": (["followups_recommended"], "found"),
    "5.2": (["followups_completed"], "not_documented"),
    "5.3": (["vascular_findings"], "found"),
}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", type=Path, required=True)
    ap.add_argument("--expected", type=Path, required=True)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--tag", default="")
    args = ap.parse_args(argv)

    cases = {c["id"]: c for c in load_cases()}
    expected = {q["id"]: q for q in json.loads(args.expected.read_text(encoding="utf-8"))}
    patient = json.loads((args.patient / "patient.json").read_text(encoding="utf-8"))
    rm = Remarker.for_patient(args.patient)
    analyzer = PromptAnalyzer(rm.tree, None, "off")
    fin = Finalizer(None, None) if args.no_llm else Finalizer.from_env(use_cache=False)

    rows, situations = [], []
    for sit, case_id in SITUATION_CASE.items():
        t0 = time.perf_counter()
        plan = analyzer.analyse(cases[case_id]["prompt"])
        t1 = time.perf_counter()
        rem = rm.remark(plan)
        t2 = time.perf_counter()
        res = fin.finalize(plan, rem, patient)
        t3 = time.perf_counter()
        items = {it.item_id: it for it in res.items}
        in_summary = {c.item_id for c in res.summary}
        situations.append({
            "situation": sit, "mode": res.mode, "models": res.models,
            "plan_ms": round((t1 - t0) * 1000, 1), "remark_ms": round((t2 - t1) * 1000, 1),
            "final_ms": round((t3 - t2) * 1000, 1), "total_ms": round((t3 - t0) * 1000, 1),
            "summary_claims": len(res.summary),
            "llm_claims": sum(c.rendered_by == "llm" for c in res.summary),
            "dropped_flags": sum(len(it.dropped) for it in res.items),
            "dropped_claims": len(res.dropped_claims), "conflicts": len(res.conflicts),
            "issues": res.issues,
        })
        for qid, (item_ids, want) in QUESTION_ITEMS.items():
            if not qid.startswith(sit + "."):
                continue
            sources = set(expected[qid]["sources"])
            present = [items[i] for i in item_ids if i in items]
            status_ok = any(it.status == want for it in present) if present else want == "not_documented"
            source_hit = (want == "not_documented") or any(
                f.doc_id in sources or any(s.split("#")[0] in sources for s in f.duplicates)
                for it in present for f in it.flags[:3])
            rows.append({"question": qid, "items": item_ids, "on_checklist": bool(present),
                         "status_ok": status_ok, "source_hit": source_hit,
                         "in_summary": any(i in in_summary for i in item_ids),
                         "visible": (want == "not_documented" and status_ok) or any(i in in_summary for i in item_ids)
                         or any(it.status == want and it.flags for it in present)})

    def rate(key):
        return sum(r[key] for r in rows) / len(rows)

    totals = [s["total_ms"] for s in situations]
    report = {
        "mode": "template_only" if args.no_llm else "llm",
        "questions": rows, "situations": situations,
        "summary": {"on_checklist": rate("on_checklist"), "status_ok": rate("status_ok"),
                    "source_hit": rate("source_hit"), "visible": rate("visible"),
                    "all_three": sum(r["status_ok"] and r["source_hit"] and r["visible"] for r in rows) / len(rows),
                    "latency_ms_p50": statistics.median(totals), "latency_ms_max": max(totals)},
    }
    out = HERE / "results" / f"final-{report['mode']}{('-' + args.tag) if args.tag else ''}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in rows:
        mark = "ok" if r["status_ok"] and r["source_hit"] and r["visible"] else "--"
        print(f"{r['question']} {mark} status={r['status_ok']} source={r['source_hit']} visible={r['visible']} {r['items']}")
    for s in situations:
        print(f"situation {s['situation']}: {s['mode']} total {s['total_ms']:.0f} ms "
              f"(final {s['final_ms']:.0f}) claims {s['summary_claims']} llm {s['llm_claims']} "
              f"dropped flags {s['dropped_flags']} dropped claims {s['dropped_claims']} {s['issues'] or ''}")
    print(json.dumps(report["summary"], indent=1))


if __name__ == "__main__":
    main()
