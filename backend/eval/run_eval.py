"""Evaluate block 5 (prompt -> checklist) on eval/cases.yaml.

Usage (from backend/):
  python -m eval.run_eval --mode keywords
  python -m eval.run_eval --mode llm-auto --provider ollama --model qwen2.5:7b
  python -m eval.run_eval --mode v1 --baseline <folder with a copy of the v1 app package>

Modes
  v1          the first decision tree (bitmask rules), keyword matching only
  keywords    the graph tree, keyword matching only
  llm-auto    graph tree + LLM step only when something in the prompt is unaccounted for
  llm-always  graph tree + LLM step on every prompt
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
CASES = HERE / "cases.yaml"
RESULTS = HERE / "results"
TOP = ("critical", "high")


# ---------------------------------------------------------------------------
# Planners: each returns a uniform dict
#   roles: most specific detected roles, tasks, context: node IDs,
#   items: {item_id: priority}, unaccounted: [words], llm_ms, method, issues
# ---------------------------------------------------------------------------
def _most_specific(role_ids, parent_of):
    roles = set(role_ids)
    ancestors = set()
    for r in roles:
        p = parent_of.get(r)
        while p:
            ancestors.add(p)
            p = parent_of.get(p)
    specific = sorted(roles - ancestors)
    return specific or ["physician"]


def make_v1_planner(baseline: Path):
    sys.path.insert(0, str(baseline))
    from app.tree import DecisionTree  # noqa: E402  (the v1 copy)

    tree = DecisionTree.load()
    parent_of = {n["id"]: n.get("parent") for n in tree.nodes}

    def plan(prompt):
        hits, checklist, unmatched = tree.plan(prompt)
        return {
            "roles": _most_specific([h.node_id for h in hits if h.kind == "role"], parent_of),
            "tasks": [h.node_id for h in hits if h.kind == "task"],
            "context": [h.node_id for h in hits if h.kind == "context"],
            "items": {e.item_id: e.priority for e in checklist.entries},
            "unaccounted": unmatched,
            "llm_ms": None,
            "method": "keywords",
            "issues": [],
        }

    return plan


def make_v2_planner(mode: str, provider: str | None, model: str | None, timeout: float = 20.0,
                    generated: bool = True):
    import tempfile

    from app.llm_client import make_client
    from app.prompt_analysis import PromptAnalyzer
    from app.tree import DecisionTree, compile_tree

    if generated:
        tree = DecisionTree.load()
    else:  # the graph without machine-generated aliases and concepts
        out = Path(tempfile.gettempdir()) / "tree.nogen.json"
        tree = DecisionTree(compile_tree(out_path=out, use_generated=False))
    uses_llm = mode in ("llm-auto", "llm-always", "semantic-llm")
    client = make_client(provider, model) if uses_llm else None
    llm_mode = {"keywords": "off", "semantic": "off", "llm-auto": "auto",
                "llm-always": "always", "semantic-llm": "auto"}[mode]
    linker = None
    if mode in ("semantic", "semantic-llm"):
        from app.embeddings import EmbeddingError
        from app.semantic import SemanticLinker
        try:
            linker = SemanticLinker(tree)
            linker.build()
        except EmbeddingError as e:  # quota or network: measure without the embedding step
            print(f"WARNING: embedding step unavailable ({str(e)[:120]}); running without it.")
            linker = None
    analyzer = PromptAnalyzer(tree, client, llm_mode=llm_mode, timeout=timeout, cache_file=None,
                              linker=linker)

    def plan(prompt):
        qp = analyzer.analyse(prompt)
        kinds = {h.node_id: h.kind for h in qp.nodes}
        return {
            "roles": _most_specific([n for n, k in kinds.items() if k == "role"], tree.parent_of),
            "tasks": [n for n, k in kinds.items() if k == "task"],
            "context": [n for n, k in kinds.items() if k == "context"],
            "items": {e.item_id: e.priority for e in qp.checklist.entries},
            "unaccounted": qp.coverage.unaccounted,
            "llm_ms": qp.llm_ms,
            "semantic_ms": qp.semantic_ms,
            "semantic_links": qp.semantic_links,
            "method": qp.method,
            "issues": qp.issues,
            "custom_questions": [c.question for c in qp.custom_questions],
            "extra_terms": sum(len(v) for e in qp.checklist.entries for k, v in e.terms.items() if k == "llm"),
        }

    return plan


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score_case(case, out):
    items = out["items"]
    top_hits = [i for i in case["top"] if items.get(i) in TOP]
    must_all = case["top"] + case["must"]
    must_hits = [i for i in must_all if i in items]
    forbid_hits = [i for i in case["forbid"] if i in items]
    return {
        "role_ok": any(r in case["role_ok"] for r in out["roles"]),
        "tasks_found": sum(t in out["tasks"] for t in case["tasks"]),
        "tasks_total": len(case["tasks"]),
        "context_found": sum(c in out["context"] for c in case["context"]),
        "context_total": len(case["context"]),
        "top_found": len(top_hits),
        "top_total": len(case["top"]),
        "must_found": len(must_hits),
        "must_total": len(must_all),
        "forbid_found": len(forbid_hits),
        "forbid_total": len(case["forbid"]),
        "size": len(items),
        "missed_top": [i for i in case["top"] if i not in top_hits],
        "missed_must": [i for i in must_all if i not in items],
        "forbidden_shown": forbid_hits,
    }


def summarise(rows):
    def ratio(a, b):
        n = sum(r[a] for r in rows)
        d = sum(r[b] for r in rows)
        return n / d if d else float("nan")

    lat = [r["ms"] for r in rows]
    llm = [r["llm_ms"] for r in rows if r["llm_ms"] is not None]
    return {
        "cases": len(rows),
        "role_accuracy": sum(r["role_ok"] for r in rows) / len(rows),
        "task_recall": ratio("tasks_found", "tasks_total"),
        "context_recall": ratio("context_found", "context_total"),
        "top_recall": ratio("top_found", "top_total"),
        "must_recall": ratio("must_found", "must_total"),
        "forbidden_rate": ratio("forbid_found", "forbid_total"),
        "cases_all_must_found": sum(r["must_found"] == r["must_total"] for r in rows) / len(rows),
        "avg_checklist_size": statistics.mean(r["size"] for r in rows),
        "fully_accounted": sum(not r["unaccounted"] for r in rows) / len(rows),
        "llm_calls": len(llm),
        "latency_ms_p50": statistics.median(lat),
        "latency_ms_max": max(lat),
        "llm_ms_p50": statistics.median(llm) if llm else None,
        "llm_ms_max": max(llm) if llm else None,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="keywords", choices=["v1", "keywords", "semantic", "llm-auto", "llm-always", "semantic-llm"])
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--provider")
    ap.add_argument("--model")
    ap.add_argument("--split", default="all", choices=["all", "dev", "heldout", "fresh", "blind", "blind2", "blind3", "blind4"])
    ap.add_argument("--tag", default="")
    ap.add_argument("--no-generated", action="store_true", help="graph without generated vocabulary")
    ap.add_argument("--timeout", type=float, default=20.0, help="LLM timeout in seconds")
    args = ap.parse_args(argv)

    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))["cases"]
    if args.split != "all":
        cases = [c for c in cases if c["split"] == args.split]

    plan = (make_v1_planner(args.baseline) if args.mode == "v1"
            else make_v2_planner(args.mode, args.provider, args.model, args.timeout, not args.no_generated))

    rows = []
    for case in cases:
        t = time.perf_counter()
        out = plan(case["prompt"])
        ms = (time.perf_counter() - t) * 1000
        row = {"id": case["id"], "split": case["split"], "ms": ms, **score_case(case, out),
               "roles": out["roles"], "unaccounted": out["unaccounted"], "llm_ms": out["llm_ms"],
               "method": out["method"], "issues": out["issues"],
               "custom_questions": out.get("custom_questions", []),
               "semantic_ms": out.get("semantic_ms"), "semantic_links": out.get("semantic_links", []),
               "extra_terms": out.get("extra_terms", 0)}
        rows.append(row)
        flag = "" if row["must_found"] == row["must_total"] and not row["forbidden_shown"] else "  <-"
        print(f"{case['id']} role={'ok' if row['role_ok'] else 'NO':<2} "
              f"top {row['top_found']}/{row['top_total']} must {row['must_found']}/{row['must_total']} "
              f"forbid {row['forbid_found']} size {row['size']:>2} {ms:7.1f} ms {row['method']}{flag}")

    report = {"mode": args.mode, "provider": args.provider, "model": args.model,
              "summary": {s: summarise([r for r in rows if r["split"] == s])
                          for s in ("dev", "heldout", "fresh", "blind", "blind2", "blind3", "blind4") if any(r["split"] == s for r in rows)},
              "overall": summarise(rows), "cases": rows}
    RESULTS.mkdir(exist_ok=True)
    name = f"{args.mode}{('-' + args.tag) if args.tag else ''}.json"
    (RESULTS / name).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"overall": report["overall"], **report["summary"]}, indent=2))
    return report


if __name__ == "__main__":
    main()
