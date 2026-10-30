"""End-to-end evaluation of the default pipeline (app/pipeline.py, blocks 5-8 together).

Part A, the five challenge situations: per question, is the answering item on the
checklist with the right status, linked to an expected source document, and visible in
the summary (see eval/run_final.py for the question -> item mapping).
Part B, blind prompts from eval/cases.yaml: checklist quality (as in run_eval.py) plus
what the full screen looks like: item statuses, summary size, conflicts, issues, timings.

The free Gemini tier limits requests per minute, so prompts are paced (--pace seconds).

Usage (from backend/):
  python -m eval.run_pipeline --patient <patient dir> --expected <cases/expected.json>
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from pathlib import Path

import yaml
from eval.cases import load_cases

from app.pipeline import Pipeline

from .run_eval import _most_specific, score_case
from .run_final import QUESTION_ITEMS, SITUATION_CASE

HERE = Path(__file__).resolve().parent


def screen_stats(res) -> dict:
    f = res.final
    return {
        "mode": f.mode, "prompt_method": res.plan.method, "models": f.models,
        "statuses": dict(Counter(it.status for it in f.items)),
        "summary_lines": len(f.summary), "llm_lines": sum(c.rendered_by == "llm" for c in f.summary),
        "dropped_flags": sum(len(it.dropped) for it in f.items), "dropped_claims": len(f.dropped_claims),
        "conflicts": len(f.conflicts), "conflict_in_summary": any(c.kind == "conflict" for c in f.summary),
        "custom_questions": len(res.plan.custom_questions), "issues": f.issues,
        "timings_ms": res.timings_ms,
        "derived": len(f.derived), "coverage": f.coverage, "privacy": f.privacy,
        "fact_backed_flags": sum(1 for it in f.items for fl in it.flags if fl.fact_ids),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", type=Path, required=True)
    ap.add_argument("--expected", type=Path, required=True)
    ap.add_argument("--splits", default="blind3", help="comma-separated blind splits for part B")
    ap.add_argument("--pace", type=float, default=8.0, help="seconds between prompts (rate limits)")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-cache", action="store_true", help="fresh LLM calls (live timings)")
    args = ap.parse_args(argv)

    cases = load_cases()
    by_id = {c["id"]: c for c in cases}
    expected = {q["id"]: q for q in json.loads(args.expected.read_text(encoding="utf-8"))}
    t = time.perf_counter()
    pipe = Pipeline.from_env(args.patient, use_llm=not args.no_llm)
    if args.no_cache:
        pipe.finalizer.use_cache = False
    startup_ms = (time.perf_counter() - t) * 1000
    parent_of = pipe.analyzer.tree.parent_of

    situations, questions = [], []
    for sit, case_id in SITUATION_CASE.items():
        res = pipe.run(by_id[case_id]["prompt"])
        items = {it.item_id: it for it in res.final.items}
        in_summary = {c.item_id for c in res.final.summary}
        situations.append({"situation": sit, **screen_stats(res)})
        for qid, (item_ids, want) in QUESTION_ITEMS.items():
            if not qid.startswith(sit + "."):
                continue
            sources = set(expected[qid]["sources"])
            present = [items[i] for i in item_ids if i in items]
            status_ok = any(it.status == want for it in present) if present else want == "not_documented"
            source_hit = want == "not_documented" or any(
                f.doc_id in sources or any(s.split("#")[0] in sources for s in f.duplicates)
                for it in present for f in it.flags[:3])
            # on screen without clicking: in the summary panel, or in the ranked list with a passage
            in_summary_hit = any(i in in_summary for i in item_ids)
            visible = (want == "not_documented" and status_ok) or in_summary_hit or \
                any(it.status == want and it.flags for it in present)
            questions.append({"question": qid, "items": item_ids, "status_ok": status_ok,
                              "source_hit": source_hit, "visible": visible, "in_summary": in_summary_hit,
                              "complete": status_ok and source_hit and visible})
        print(f"situation {sit}: {situations[-1]['mode']} {res.timings_ms['total']:.0f} ms")
        time.sleep(args.pace)

    blind = []
    for split in args.splits.split(","):
        for case in [c for c in cases if c["split"] == split]:
            res = pipe.run(case["prompt"])
            kinds = {h.node_id: h.kind for h in res.plan.nodes}
            out = {"roles": _most_specific([n for n, k in kinds.items() if k == "role"], parent_of),
                   "tasks": [n for n, k in kinds.items() if k == "task"],
                   "context": [n for n, k in kinds.items() if k == "context"],
                   "items": {e.item_id: e.priority for e in res.plan.checklist.entries}}
            row = {"id": case["id"], "split": split, "prompt": case["prompt"], **score_case(case, out),
                   **screen_stats(res)}
            blind.append(row)
            print(f"{case['id']}: {row['mode']} {row['timings_ms']['total']:.0f} ms "
                  f"must {row['must_found']}/{row['must_total']}")
            time.sleep(args.pace)

    def ratio(rows, a, b):
        d = sum(r[b] for r in rows)
        return sum(r[a] for r in rows) / d if d else None

    totals = [s["timings_ms"]["total"] for s in situations] + [r["timings_ms"]["total"] for r in blind]
    report = {
        "config": {"prompt_analysis": "graph + generated vocabulary + Gemini check (auto)",
                   "remarker": "lexical + embeddings, no reranker",
                   "final": "two parallel Gemini Flash-Lite calls" if not args.no_llm else "templates only"},
        "startup_ms": round(startup_ms), "situations": situations, "questions": questions, "blind": blind,
        "summary": {
            "complete": sum(q["complete"] for q in questions) / len(questions),
            "status_ok": sum(q["status_ok"] for q in questions) / len(questions),
            "source_hit": sum(q["source_hit"] for q in questions) / len(questions),
            "visible": sum(q["visible"] for q in questions) / len(questions),
            "blind_role_accuracy": sum(r["role_ok"] for r in blind) / len(blind) if blind else None,
            "blind_must_recall": ratio(blind, "must_found", "must_total"),
            "blind_top_recall": ratio(blind, "top_found", "top_total"),
            "blind_forbidden_rate": ratio(blind, "forbid_found", "forbid_total"),
            "llm_mode_share": sum(r["mode"] == "llm" for r in situations + blind) / len(situations + blind),
            "latency_ms_p50": statistics.median(totals), "latency_ms_max": max(totals),
            "latency_under_3s": sum(t < 3000 for t in totals) / len(totals),
            "latency_under_10s": sum(t < 10000 for t in totals) / len(totals),
        },
    }
    name = f"pipeline{'-nollm' if args.no_llm else ''}{('-' + args.tag) if args.tag else ''}.json"
    (HERE / "results" / name).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report["summary"], indent=1))


if __name__ == "__main__":
    main()
