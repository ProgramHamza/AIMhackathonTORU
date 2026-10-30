"""Evaluate the remarker on the 15 challenge questions.

Usage (from backend/, with PATIENT_DIR set or --patient):
  python -m eval.remarker_eval                 # default: lexical + embeddings
  python -m eval.remarker_eval --rerank        # ablations reuse cached API results
  python -m eval.remarker_eval --no-dense

Prints per-check results (IDs and scores only, no document text) and a summary.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import yaml

from app.prompt_analysis import PromptAnalyzer
from app.remarker import Remarker
from app.tree import DecisionTree

HERE = Path(__file__).resolve().parent


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", type=Path, default=os.environ.get("PATIENT_DIR"))
    ap.add_argument("--no-dense", action="store_true")
    ap.add_argument("--rerank", action="store_true", help="add the Jina reranker (off by default)")
    ap.add_argument("--tag", default="")
    args = ap.parse_args(argv)

    checks = yaml.safe_load((HERE / "remarker_cases.yaml").read_text(encoding="utf-8"))["checks"]
    prompts = {c["id"]: c["prompt"] for c in yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))["cases"]}
    tree = DecisionTree.load()
    t = time.perf_counter()
    rm = Remarker.for_patient(args.patient, tree, dense=not args.no_dense, rerank=args.rerank)
    ready_ms = (time.perf_counter() - t) * 1000
    analyzer = PromptAnalyzer(tree, None, "off")

    results = {}
    latency = []
    for case in sorted({c["case"] for c in checks}):
        t = time.perf_counter()
        plan = analyzer.analyse(prompts[case])
        res = rm.remark(plan)
        latency.append((time.perf_counter() - t) * 1000)
        results[case] = res

    rows = []
    offsets_ok = flags_total = 0
    for c in checks:
        res = results[c["case"]]
        ev = next((e for e in res.items if e.item_id == c["item"]), None)
        if ev is None:
            rows.append({**c, "on_checklist": False, "status_ok": False, "source_hit": False,
                         "source_recall": 0.0, "precision": None, "current_ok": None, "flags": 0})
            continue
        docs_flagged = set()
        in_source = 0
        for f in ev.flags:
            flags_total += 1
            text = rm.ix.docs[f.doc_id]["text"]
            offsets_ok += text[f.start:f.end] == f.text
            fdocs = {f.doc_id} | {s.split("#")[0] for s in f.duplicates}
            docs_flagged |= fdocs
            in_source += bool(fdocs & set(c["sources"]))
        expected = set(c["sources"])
        current_ok = None
        if c.get("current"):
            cur = {f.doc_id for f in ev.flags if f.current and f.polarity in ("affirmed", "past", "planned")}
            current_ok = cur == {c["current"]}
        rows.append({**c, "on_checklist": True, "status_ok": ev.status == c["status"],
                     "got_status": ev.status,
                     "source_hit": bool(docs_flagged & expected) if expected else not ev.flags or ev.status == c["status"],
                     "source_recall": len(docs_flagged & expected) / len(expected) if expected else None,
                     "precision": in_source / len(ev.flags) if ev.flags and expected else None,
                     "current_ok": current_ok, "flags": len(ev.flags),
                     "top": [(f.segment_id, f.ridx, f.polarity) for f in ev.flags[:3]]})

    for r in rows:
        mark = "ok " if r["status_ok"] and r["source_hit"] and r.get("current_ok") is not False else "XX "
        print(f"{mark}{r['q']:<4} {r['item']:<24} status {r.get('got_status', '-'):<15} "
              f"(want {r['status']}) recall {r['source_recall'] if r['source_recall'] is None else round(r['source_recall'], 2)} "
              f"prec {r['precision'] if r['precision'] is None else round(r['precision'], 2)} "
              f"current {r['current_ok']} flags {r['flags']} {r.get('top', '')}")

    def mean(key):
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(vals) / len(vals), 3) if vals else None

    questions = sorted({r["q"] for r in rows})
    q_ok = sum(all(r["status_ok"] and r["source_hit"] and r.get("current_ok") is not False
                   for r in rows if r["q"] == q) for q in questions)
    summary = {
        "mode": {"dense": not args.no_dense, "rerank": args.rerank},
        "questions_fully_supported": f"{q_ok}/{len(questions)}",
        "checks_ok": f"{sum(r['status_ok'] and r['source_hit'] and r.get('current_ok') is not False for r in rows)}/{len(rows)}",
        "status_accuracy": mean("status_ok"),
        "source_hit_rate": mean("source_hit"),
        "source_recall": mean("source_recall"),
        "flag_precision": mean("precision"),
        "current_value_correct": mean("current_ok"),
        "avg_flags_per_item": round(statistics.mean(r["flags"] for r in rows), 2),
        "offsets_exact": f"{offsets_ok}/{flags_total}",
        "contradiction_candidates": len(next(iter(results.values())).contradictions),
        "index_ready_ms": round(ready_ms, 1),
        "remark_ms_p50": round(statistics.median(latency), 1),
        "remark_ms_max": round(max(latency), 1),
        "api_calls_per_query": max(r.api_calls for r in results.values()),
        "build_info": rm.ix.build_info,
    }
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    out = HERE / "results" / f"remarker{('-' + args.tag) if args.tag else ''}.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, default=str), encoding="utf-8")
    return summary


if __name__ == "__main__":
    main()
