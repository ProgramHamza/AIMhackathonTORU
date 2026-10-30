"""Report 5: the whole system against simple baselines, on the same prompts.

Systems
  ours        the full pipeline (default configuration, live LLM calls, no cache)
  ours_nollm  the same pipeline with templates only (no model call at all)
  llm_only    baseline A: whole record + request, one Gemini call (eval/baselines.py)
  rules_only  baseline B: if/else keyword rules (eval/baselines.py)

Grading
  - One judge call per prompt (Gemini; Flash, Flash-Lite as fallback) sees all screens,
    shuffled and anonymous, and grades: the challenge questions (5 situations, against
    cases/expected.json), the needed and the irrelevant checklist topics (blind prompts),
    and which listed conflicts are real (against eval/private/known_contradictions.yaml).
  - Code checks: exact quotes (traceability), numbers absent from the cited source,
    screen length, time, model calls, characters sent to the cloud, identifiers removed.
Only the free keys in .env are used; nothing enables billing. Every text passes the
outbound gate, the judge's included.

Usage (from backend/):
  python -m eval.run_baselines --patient <dir> --expected <cases/expected.json>
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from collections import Counter
from pathlib import Path

import yaml

from app import outbound
from app.llm_client import GeminiClient, LLMError
from app.pipeline import Pipeline
from app.summary import summary_keys
from app.tree import DecisionTree

from .baselines import LLMOnlyBaseline, RulesBaseline, Screen, code_metrics, screen_from_final, _docs_text
from .run_final import QUESTION_ITEMS, SITUATION_CASE

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
SYSTEMS = ["ours", "ours_nollm", "llm_only", "rules_only"]
LABELS = {"ours": "Our system", "ours_nollm": "Our system, no LLM", "llm_only": "Baseline A: one LLM call",
          "rules_only": "Baseline B: if/else rules"}

JUDGE_SYSTEM = """\
You grade screens produced by different systems for a clinician. Each screen is a numbered
list of lines. Judge only what the lines say; do not reward length.

For each screen:
1. answers: for each question, compare with the expected answer.
   correct = the screen states the expected answer (wording may differ; for "not documented"
   answers, the screen must say it is not documented or clearly show it is absent);
   partial = part of it, or the answer without a key detail (dose, date, side);
   missing = not on the screen; wrong = the screen states something that contradicts it.
2. needed: for each needed topic, is it addressed (stated, or explicitly "not documented")?
3. irrelevant: for each listed irrelevant topic, is it shown anyway?
4. conflicts: for every line that reports a contradiction or conflict, give its line number
   and which known contradiction it is (K1, K2, ...) or "false_alarm" if it matches none.
Return every screen; "id" is the screen's letter only (A, B, ...).
"""
JUDGE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["screens"],
    "properties": {"screens": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["id", "answers", "needed", "irrelevant", "conflicts"],
        "properties": {
            "id": {"type": "string"},
            "answers": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["q", "verdict"],
                                                   "properties": {"q": {"type": "string"},
                                                                  "verdict": {"type": "string", "enum": ["correct", "partial", "missing", "wrong"]}}}},
            "needed": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["topic", "addressed"],
                                                  "properties": {"topic": {"type": "string"}, "addressed": {"type": "boolean"}}}},
            "irrelevant": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["topic", "shown"],
                                                      "properties": {"topic": {"type": "string"}, "shown": {"type": "boolean"}}}},
            "conflicts": {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["line", "match"],
                                                    "properties": {"line": {"type": "integer"}, "match": {"type": "string"}}}},
        }}}},
}


def judge_client() -> GeminiClient | None:
    keys = summary_keys()
    if not keys:
        return None
    c = GeminiClient("gemini-3.5-flash", api_key=keys[0])
    c.api_keys = keys
    c.models = ["gemini-3.5-flash", "gemini-flash-lite-latest"]
    return c


LINE_CHARS = 700  # per screen line shown to the judge; the same for every system


def render_screen(sid: str, screen: Screen, limit: int = 60) -> str:
    lines = [f"SCREEN {sid}"]
    for n, s in enumerate(screen.statements[:limit], 1):
        src = f" [doc {s.doc_id}]" if s.doc_id else ""
        lines.append(f"{n}. {' '.join(s.text.split())[:LINE_CHARS]}{src}")
    if not screen.statements:
        lines.append("(empty screen)" + (f" error: {screen.error}" if screen.error else ""))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--patient", type=Path, required=True)
    ap.add_argument("--expected", type=Path, required=True)
    ap.add_argument("--splits", default="blind2,blind3")
    ap.add_argument("--pace", type=float, default=8.0)
    ap.add_argument("--limit", type=int, default=0, help="only the first N prompts (smoke test)")
    args = ap.parse_args(argv)

    cases = yaml.safe_load((HERE / "cases.yaml").read_text(encoding="utf-8"))["cases"]
    by_id = {c["id"]: c for c in cases}
    expected = {q["id"]: q for q in json.loads(args.expected.read_text(encoding="utf-8"))}
    known = yaml.safe_load((HERE / "private" / "known_contradictions.yaml").read_text(encoding="utf-8"))
    tree = DecisionTree.load()
    item_q = {it["id"]: it["question"] for it in tree.items}

    jobs = [("situation", sit, by_id[cid]) for sit, cid in SITUATION_CASE.items()]
    jobs += [("blind", c["id"], c) for c in cases if c["split"] in args.splits.split(",")]
    if args.limit:
        jobs = jobs[:args.limit]

    ours = Pipeline.from_env(args.patient, use_llm=True)
    ours.finalizer.use_cache = False
    ours_nollm = Pipeline.from_env(args.patient, use_llm=False)
    llm_only = LLMOnlyBaseline(args.patient)
    rules = RulesBaseline(args.patient)
    judge = judge_client()
    docs = {d: v["text"] for d, v in _docs_text(args.patient).items()}
    rng = random.Random(7)

    rows = []
    for kind, key, case in jobs:
        prompt = case["prompt"]
        screens: dict[str, Screen] = {}
        sent: dict[str, dict] = {}
        for system in SYSTEMS:
            outbound.reset_stats()
            if system == "ours":
                res = ours.run(prompt)
                screens[system] = screen_from_final(system, res, calls=2 if ours.finalizer.check_client else 0)
            elif system == "ours_nollm":
                res = ours_nollm.run(prompt)
                screens[system] = screen_from_final(system, res, calls=0)
            elif system == "llm_only":
                screens[system] = llm_only.run(prompt)
            else:
                screens[system] = rules.run(prompt)
            st = outbound.stats()
            sent[system] = {"chars": st.get("chars_sent", 0), "identifiers_removed": sum(st["replaced"].values()),
                            "refused": st["refused"]}

        # judge: all screens of this prompt in one call, shuffled and anonymous
        order = SYSTEMS[:]
        rng.shuffle(order)
        anon = {s: chr(ord("A") + n) for n, s in enumerate(order)}
        task = [f"Clinician request: {prompt}"]
        if kind == "situation":
            qs = [q for q in QUESTION_ITEMS if q.startswith(key + ".")]
            task.append("Questions and expected answers:\n" + "\n".join(
                f"{q}: {expected[q]['question']} EXPECTED: {expected[q]['answer']}" for q in qs))
            task.append("Known contradictions in the documents:\n" + "\n".join(f"{k['id']}: {k['text']}" for k in known))
        else:
            needed = case["top"] + case["must"]
            task.append("Needed topics:\n" + "\n".join(f"{i}: {item_q.get(i, i)}" for i in needed))
            task.append("Irrelevant topics:\n" + "\n".join(f"{i}: {item_q.get(i, i)}" for i in case["forbid"]))
            task.append("Known contradictions in the documents:\n" + "\n".join(f"{k['id']}: {k['text']}" for k in known))
        user = "\n\n".join(task) + "\n\n" + "\n\n".join(render_screen(anon[s], screens[s]) for s in order)
        grades, judge_err = {}, None
        if judge:
            try:
                r = judge.complete_json(JUDGE_SYSTEM, user, JUDGE_SCHEMA, 90)
                back = {v: k for k, v in anon.items()}
                for g in r.data.get("screens", []):
                    gid = str(g.get("id", "")).upper().replace("SCREEN", "").strip(" :.")
                    if gid in back:
                        grades[back[gid]] = g
            except LLMError as e:
                judge_err = str(e)[:200]

        row = {"kind": kind, "key": key, "prompt": prompt, "judge_error": judge_err, "systems": {}}
        for system in SYSTEMS:
            sc = screens[system]
            g = grades.get(system, {})
            conflict_lines = {n: s for n, s in enumerate(sc.statements[:60], 1) if s.kind == "conflict"}
            matches = [c for c in g.get("conflicts", []) if isinstance(c, dict)]
            row["systems"][system] = {
                "ms": round(sc.ms, 1), "llm_calls": sc.llm_calls, "error": sc.error,
                **code_metrics(sc, docs), **sent[system],
                "answers": {a["q"]: a["verdict"] for a in g.get("answers", []) if isinstance(a, dict)},
                "needed": {n["topic"]: n["addressed"] for n in g.get("needed", []) if isinstance(n, dict)},
                "irrelevant": {n["topic"]: n["shown"] for n in g.get("irrelevant", []) if isinstance(n, dict)},
                "conflicts": [m.get("match") for m in matches],
                "conflict_lines_shown": len(conflict_lines),
                "graded": bool(g),
            }
        rows.append(row)
        s = row["systems"]
        print(f"{key:>3} " + " | ".join(f"{x}: {s[x]['ms'] / 1000:.1f}s {sum(v == 'correct' for v in s[x]['answers'].values())}c "
                                        f"{sum(s[x]['needed'].values())}/{len(s[x]['needed'])}n" for x in SYSTEMS)
              + (f"  judge error: {judge_err}" if judge_err else ""), flush=True)
        time.sleep(args.pace)

    summary = summarise(rows, known)
    out = RESULTS / "baselines.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))


def summarise(rows, known) -> dict:
    known_ids = {k["id"] for k in known}
    out = {}
    for system in SYSTEMS:
        sit = [r["systems"][system] for r in rows if r["kind"] == "situation"]
        bl = [r["systems"][system] for r in rows if r["kind"] == "blind"]
        allr = sit + bl
        verdicts = Counter(v for x in sit for v in x["answers"].values())
        n_q = sum(len(x["answers"]) for x in sit) or 1
        matched = {m for x in sit for m in x["conflicts"] if m in known_ids}
        false_alarms = sum(1 for x in sit for m in x["conflicts"] if m not in known_ids)
        needed = [v for x in bl for v in x["needed"].values()]
        irrelevant = [v for x in bl for v in x["irrelevant"].values()]
        findings = sum(x["findings"] for x in allr) or 1
        times = [x["ms"] for x in allr]
        out[system] = {
            "label": LABELS[system],
            "questions_graded": sum(len(x["answers"]) for x in sit),
            "answers_correct": verdicts["correct"], "answers_partial": verdicts["partial"],
            "answers_missing": verdicts["missing"], "answers_wrong": verdicts["wrong"],
            "answer_score": round((verdicts["correct"] + 0.5 * verdicts["partial"]) / n_q, 4),
            "contradictions_found": sorted(matched), "contradiction_false_alarms": false_alarms,
            "contradiction_score": len(matched) - false_alarms,
            "needed_addressed": round(sum(needed) / len(needed), 4) if needed else None,
            "irrelevant_shown": round(sum(irrelevant) / len(irrelevant), 4) if irrelevant else None,
            "traceability": round(sum(x["quote_exact"] for x in allr) / findings, 4),
            "linked_share": round(sum(x["linked_to_document"] for x in allr) / findings, 4),
            "unsupported_numbers_per_screen": round(statistics.mean(x["unsupported_numbers"] for x in allr), 2),
            "screens_with_unsupported_numbers": sum(x["unsupported_numbers"] > 0 for x in allr),
            "statements_per_screen": round(statistics.mean(x["statements"] for x in allr), 1),
            "not_documented_lines_per_screen": round(statistics.mean(x["not_documented_lines"] for x in allr), 1),
            "latency_ms_p50": round(statistics.median(times), 1), "latency_ms_max": round(max(times), 1),
            "under_10s": round(sum(t < 10000 for t in times) / len(times), 4),
            "under_3s": round(sum(t < 3000 for t in times) / len(times), 4),
            "llm_calls_per_request": round(statistics.mean(x["llm_calls"] for x in allr), 2),
            "chars_sent_per_request": round(statistics.mean(x["chars"] for x in allr)),
            "identifiers_removed_per_request": round(statistics.mean(x["identifiers_removed"] for x in allr), 1),
            "errors": sum(1 for x in allr if x["error"]),
            "graded_share": round(sum(x["graded"] for x in allr) / len(allr), 4),
        }
    return out


if __name__ == "__main__":
    main()
