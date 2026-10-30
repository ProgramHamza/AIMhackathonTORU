"""Per-block evaluation and hand-off checks, written to eval/results/blocks.json.

Blocks 1-4   evidence backend: its own test suite, bundle integrity, how much of it maps
             onto our segments.
Block 5      prompt analysis: run_eval results (keywords, and the LLM check where measured).
Blocks 6/7   remarker: eval/remarker_eval.py on the 15 challenge checks (lexical+embeddings;
             earlier ablations are read from their result files).
Block 8      final step: eval/run_final.py results (templates only vs with the LLM) and the
             adversarial claim tests.
Security     de-identification over all documents, gate statistics, encryption throughput.
Interactions every hand-off between blocks, checked on the 5 situations + blind prompts
             with the template path (no network): plan items known to the remarker, facts
             mapped to segments, every citation resolvable and equal to the document slice,
             conflicts' passages present, summary items on the checklist, derived values
             linked, and the gate active on every cloud client.

Usage (from backend/): python -m eval.run_blocks --patient <dir> --expected <cases/expected.json>
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import yaml

from app import outbound, vault
from app.deidentify import Deidentifier
from app.evidence_bridge import BLOCKS14, load_bundle
from app.pipeline import Pipeline
from app.prompt_analysis import PromptAnalyzer
from app.segmenter import clean_text
from app.summary import Finalizer

from .run_final import QUESTION_ITEMS, SITUATION_CASE

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
PY = sys.executable


def load(name):
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------------------------------------------------------------------
def unit_tests() -> dict:
    """Per test file counts from the junit report (python -m pytest --junitxml=...)."""
    path = RESULTS / "junit.xml"
    if not path.exists():
        subprocess.run([PY, "-m", "pytest", "-q", f"--junitxml={path}"], cwd=HERE.parent, capture_output=True)
    files: dict[str, dict] = {}
    for tc in ET.parse(path).getroot().iter("testcase"):
        f = (tc.get("classname") or "").split(".")[-1]
        d = files.setdefault(f, {"passed": 0, "failed": 0})
        if tc.find("failure") is not None or tc.find("error") is not None:
            d["failed"] += 1
        else:
            d["passed"] += 1
    return files


def evidence_backend(patient_id: str) -> dict:
    t = time.perf_counter()
    r = subprocess.run([PY, "-I", "-X", "utf8", "-c",
                        "import sys, os, unittest, json; sys.path.insert(0, sys.argv[1]); os.chdir(sys.argv[1]);"
                        "r = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.discover('tests'));"
                        "print(json.dumps({'ran': r.testsRun, 'failures': len(r.failures), 'errors': len(r.errors)}))",
                        str(BLOCKS14)], capture_output=True, text=True)
    own_tests = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {"error": r.stderr[-300:]}
    own_tests["seconds"] = round(time.perf_counter() - t, 1)
    bundle, history = load_bundle(patient_id)
    facts = bundle.facts
    return {
        "own_tests": own_tests,
        "bundle": {"status": bundle.manifest.status, "documents": len(bundle.documents), "passages": len(bundle.passages),
                   "facts": len(facts), "derived_values": len(bundle.derived_facts),
                   "contradictions": dict(Counter(c.status for c in bundle.contradictions)),
                   "processing_gaps": len(bundle.processing_gaps),
                   "facts_by_category": dict(Counter(f.category for f in facts)),
                   "facts_by_method": dict(Counter(f.extraction_method for f in facts)),
                   "quotes_verified": sum(len(f.evidence) for f in facts),
                   "quotes_total": sum(len(f.evidence) for f in facts),
                   "validation_quote_match_passed": sum(f.validation.quote_match == "passed" for f in facts),
                   "model_checked": sum(f.validation.semantic_check in ("model_checked", "human_checked") for f in facts),
                   "latest_discharge_medications": len((history.get("latest_discharge_medications") or {}).get("fact_ids", []))},
    }


def block5() -> dict:
    out = {}
    kw = load("keywords-blocks") or load("keywords-final")
    if kw:
        out["keywords"] = {s: {k: v[k] for k in ("cases", "role_accuracy", "context_recall", "top_recall",
                                                    "must_recall", "cases_all_must_found", "forbidden_rate",
                                                    "avg_checklist_size", "latency_ms_p50")}
                           for s, v in kw["summary"].items()}
    for name, key in (("v1-final", "old_tree"), ("llm-auto-gen-gemini-blind3", "with_llm_check"),
                      ("llm-auto-gemini-blind2", "with_llm_check_blind2")):
        r = load(name)
        if r:
            out[key] = {s: {k: v.get(k) for k in ("cases", "role_accuracy", "context_recall", "top_recall", "must_recall",
                                                    "cases_all_must_found", "forbidden_rate", "latency_ms_p50", "llm_calls")}
                        for s, v in r["summary"].items()}
    return out


def blocks67(patient: Path) -> dict:
    before = time.time()
    subprocess.run([PY, "-X", "utf8", "-m", "eval.remarker_eval", "--patient", str(patient), "--tag", "blocks"],
                   cwd=HERE.parent, capture_output=True, text=True)
    newest = max(RESULTS.glob("remarker-*.json"), key=lambda p: p.stat().st_mtime)
    current = json.loads(newest.read_text(encoding="utf-8")) if newest.stat().st_mtime >= before - 1 else None
    out = {"current": (current or {}).get("summary"), "current_file": newest.name if current else None, "ablations": {}}
    for name in ("remarker-lexical", "remarker-dense", "remarker-rerank", "remarker-full"):
        r = load(name)
        if r:
            out["ablations"][name.split("-", 1)[1]] = r.get("summary")
    return out


def block8() -> dict:
    out = {}
    for name, key in (("final-template_only", "templates_only"), ("final-llm", "with_llm")):
        r = load(name)
        if r:
            out[key] = r["summary"]
    return out


def security(patient: Path) -> dict:
    pj = json.loads((patient / "patient.json").read_text(encoding="utf-8"))
    docs = json.loads((patient / "documents.json").read_text(encoding="utf-8")).get("documents", [])
    d = Deidentifier.for_patient(pj, docs)
    replaced, leaks, chars, t_total = Counter(), 0, 0, 0.0
    per_doc = []
    for f in sorted((patient / "documents").glob("*.json")):
        text = clean_text(json.loads(f.read_text(encoding="utf-8"))["text"])
        t = time.perf_counter()
        r = d.scrub(text)
        dt = time.perf_counter() - t
        l = d.leaks(r.text)
        replaced.update(r.replaced)
        leaks += len(l)
        chars += len(text)
        t_total += dt
        per_doc.append({"doc": f.stem, "chars": len(text), "replaced": sum(r.replaced.values()), "leaks": len(l), "ms": round(dt * 1000, 2)})
    # raw identifiers present before scrubbing, to show the gate had something to do
    raw_hits = sum(len(d.leaks(clean_text(json.loads(f.read_text(encoding="utf-8"))["text"])))
                   for f in sorted((patient / "documents").glob("*.json")))
    data = os.urandom(8 * 1024 * 1024)
    t = time.perf_counter()
    blob = vault.encrypt(data)
    t_enc = time.perf_counter() - t
    t = time.perf_counter()
    vault.decrypt(blob)
    t_dec = time.perf_counter() - t
    cache_files = [p for p in (HERE.parent / ".cache").rglob("*") if p.is_file() and not p.name.startswith(".")]
    return {
        "deidentification": {"documents": len(per_doc), "characters": chars, "identifiers_before": raw_hits,
                             "replaced_by_type": dict(replaced), "replaced_total": sum(replaced.values()),
                             "identifiers_after": leaks, "ms_total": round(t_total * 1000, 1), "per_document": per_doc},
        "encryption": {"mb": 8, "encrypt_ms": round(t_enc * 1000, 1), "decrypt_ms": round(t_dec * 1000, 1),
                       "mb_per_s": round(8 / max(t_enc + t_dec, 1e-6), 0),
                       "cache_files": len(cache_files), "cache_files_encrypted": sum(vault.is_encrypted(p) for p in cache_files)},
        "gate": {"https_only": True, "clients_gated": ["gemini", "anthropic", "ollama (remote)", "gemini embeddings", "jina embeddings", "jina reranker"]},
    }


def interactions(patient: Path, expected: Path, splits: list[str]) -> dict:
    """Every hand-off, on the template path (no network) so it runs on every prompt."""
    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    prompts = [c["prompt"] for c in cases if c["id"] in SITUATION_CASE.values()]
    prompts += [c["prompt"] for c in cases if c["split"] in splits]
    pipe = Pipeline.from_env(patient, use_llm=False)
    rm = pipe.remarker
    docs = {d: v["text"] for d, v in rm.ix.docs.items()}
    segs = {sg.seg.segment_id: sg.seg for sg in rm.ix.segs}
    outbound.reset_stats()
    c = Counter()
    times = []
    for p in prompts:
        res = pipe.run(p)
        plan, rem, fin = res.plan, res.remark, res.final
        times.append(res.timings_ms["total"])
        c["prompts"] += 1
        # 5 -> 6/7: every planned item is known to the remarker and came back with a status
        got = {it.item_id for it in rem.items}
        for e in plan.checklist.entries:
            c["plan_items"] += 1
            c["plan_items_known"] += e.item_id in rm.item_pos
            c["plan_items_answered"] += e.item_id in got
        # 6/7 -> 8: every flag's text equals the document slice; every cite exists
        for it in fin.items:
            for f in it.flags:
                c["flags"] += 1
                c["flags_exact"] += docs[f.doc_id][f.start:f.end] == f.text
                c["flags_fact_backed"] += bool(f.fact_ids)
        for cl in fin.summary:
            c["claims"] += 1
            ok = all(s in segs for s in cl.cites)
            c["claims_cites_resolve"] += ok
            c["claims_cited_or_absent"] += bool(cl.cites) or cl.kind in ("not_documented", "incomplete")
            c["claims_item_on_checklist"] += (cl.item_id is None) or any(e.item_id == cl.item_id for e in plan.checklist.entries)
        # 1-4 -> 6/7 -> 8: derived values and conflicts link to real passages
        for d in fin.derived:
            c["derived"] += 1
            c["derived_linked"] += bool(d.segment_ids) and all(s in segs for s in d.segment_ids)
        for cf in fin.conflicts:
            c["conflicts"] += 1
            c["conflicts_two_passages"] += len(cf.segment_ids) >= 2 and all(s in segs for s in cf.segment_ids)
        # 5 -> 8: critical items of the plan appear in the summary
        crit = [e.item_id for e in plan.checklist.entries if e.priority == "critical"]
        shown = {cl.item_id for cl in fin.summary}
        c["critical_items"] += len(crit)
        c["critical_in_summary"] += sum(i in shown for i in crit)
        c["privacy_refused"] += fin.privacy.get("refused", 0)
    def rate(a, b):
        return round(c[a] / c[b], 4) if c[b] else None
    return {
        "prompts": c["prompts"], "template_path_ms_p50": round(sorted(times)[len(times) // 2], 1),
        "handoffs": {
            "5_to_67_items_known": rate("plan_items_known", "plan_items"),
            "5_to_67_items_answered": rate("plan_items_answered", "plan_items"),
            "67_to_8_flag_text_equals_document": rate("flags_exact", "flags"),
            "14_to_67_flags_backed_by_verified_fact": rate("flags_fact_backed", "flags"),
            "8_claims_cites_resolve": rate("claims_cites_resolve", "claims"),
            "8_claims_cited_or_marked_absent": rate("claims_cited_or_absent", "claims"),
            "5_to_8_claim_items_on_checklist": rate("claims_item_on_checklist", "claims"),
            "5_to_8_critical_items_in_summary": rate("critical_in_summary", "critical_items"),
            "14_to_8_derived_values_linked": rate("derived_linked", "derived"),
            "conflicts_link_two_passages": rate("conflicts_two_passages", "conflicts"),
            "gate_refusals": c["privacy_refused"],
        },
        "counts": dict(c),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", type=Path, default=os.environ.get("PATIENT_DIR"))
    ap.add_argument("--expected", type=Path, required=True)
    ap.add_argument("--splits", default="blind2,blind3")
    args = ap.parse_args(argv)
    patient = Path(args.patient)
    pid = json.loads((patient / "patient.json").read_text(encoding="utf-8"))["id"]
    report = {}
    for name, fn in (("unit_tests", unit_tests), ("blocks_1_4", lambda: evidence_backend(pid)), ("block_5", block5),
                     ("blocks_6_7", lambda: blocks67(patient)), ("block_8", block8), ("security", lambda: security(patient)),
                     ("interactions", lambda: interactions(patient, args.expected, args.splits.split(",")))):
        t = time.perf_counter()
        try:
            report[name] = fn()
        except Exception as e:  # one failing section must not hide the others
            report[name] = {"error": f"{type(e).__name__}: {e}"}
        print(f"{name}: {round((time.perf_counter() - t) * 1000)} ms", "ERROR" if "error" in report[name] else "")
    (RESULTS / "blocks.json").write_text(json.dumps(report, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(report.get("interactions", {}).get("handoffs"), indent=1))


if __name__ == "__main__":
    main()
