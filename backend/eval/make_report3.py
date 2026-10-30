"""Build eval/results/report3.html: the whole pipeline (blocks 5-8) end to end, with the
default configuration, plus the earlier comparisons from report2.

Needs eval/results/pipeline.json and pipeline-nollm.json (python -m eval.run_pipeline).
Usage (from backend/): python -m eval.make_report3
"""
from __future__ import annotations

from .make_report2 import (PAGE, RESULTS, esc, glossary_html, grouped_bars, legend, load, pct,
                           sections, table)

OK = '<span class="ok">✓</span>'
NO = '<span class="no">✗</span>'

FIXED = [
    ("Unrelated conflicts in the summary",
     "The carotid left/right contradiction appeared in a dentist's summary.",
     "The remarker now records which checklist items each contradiction concerns; the summary "
     "shows a conflict only for those. All conflicts stay in the conflicts list."),
    ("Relevant conflict hidden",
     "The first relevance rule (shared passage only) hid the carotid conflict from the follow-up GP, "
     "who needs the side of the stenosis.",
     "Same fix: relevance comes from the remarker's item scores, not only shared passages."),
    ("Stale cached summaries",
     "After a code change, the summary cache still served the old answer.",
     "The cache key now includes a version number and the conflicts' items."),
    ("Evaluation crashed on quota",
     "When the embedding quota ran out, the semantic evaluation stopped with an error.",
     "It now warns and measures without the embedding step."),
]

PIPE_METRICS = [
    ("Answers complete", "Of the 15 challenge questions: right status, linked to an expected source "
     "document and visible in the summary. Our stand-in for the jury's 'correct answer'."),
    ("Time, prompt to full screen", "From typing the request to the finished screen: prompt "
     "analysis + marking passages + the final check and summary. The challenge limit is 10 s."),
    ("Needed items found (blind)", "On prompts never used for tuning: how many of the needed "
     "checklist items made it onto the list."),
    ("Ran with the LLM", "Share of requests where both LLM calls of the final step answered in time "
     "(the rest used the template fallback)."),
]


def stacked_time_bars(rows, width=720):
    """rows: [(label, prompt_ms, remarker_ms, final_ms)] -> horizontal stacked bars in seconds."""
    left, right, bar_h, gap = 120, 70, 16, 12
    maxv = max(3.0, max((p + r + f) / 1000 for _, p, r, f in rows))
    plot_w = width - left - right
    height = len(rows) * (bar_h + gap) + 24
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Time per situation">']
    for s in range(0, int(maxv) + 1):
        x = left + plot_w * s / maxv
        out.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{height - 18}"/>'
                   f'<text x="{x:.1f}" y="{height - 4}" text-anchor="middle">{s} s</text>')
    y = 4
    for label, p, r, f in rows:
        out.append(f'<text class="rowlabel" x="{left - 10}" y="{y + bar_h - 4}" text-anchor="end">{esc(label)}</text>')
        x = left
        for ms, slot, name in ((p, 1, "Prompt analysis"), (r, 2, "Marking passages"), (f, 3, "Check and summary")):
            w = plot_w * (ms / 1000) / maxv
            if w > 0:
                out.append(f'<g class="mark"><title>{esc(label)} – {name}: {ms / 1000:.2f} s</title>'
                           f'<rect class="s{slot}" x="{x:.1f}" y="{y}" width="{max(w - 2, 1.5):.1f}" height="{bar_h}" rx="3"/></g>')
            x += w
        out.append(f'<text class="val" x="{x + 6:.1f}" y="{y + bar_h - 4}">{(p + r + f) / 1000:.2f} s</text>')
        y += bar_h + gap
    out.append("</svg>")
    return "".join(out)


def build() -> str:
    run, base = load("pipeline"), load("pipeline-nollm")
    if not run:
        raise SystemExit("eval/results/pipeline.json missing: run python -m eval.run_pipeline first")
    s = run["summary"]
    parts = []

    tiles = [
        (f"{round(s['complete'] * 15)}/15", "challenge answers complete"),
        (f"{s['latency_ms_p50'] / 1000:.1f} s", "median, prompt to full screen"),
        (f"{s['latency_ms_max'] / 1000:.1f} s", "slowest request (limit 10 s)"),
        (pct(s["blind_must_recall"]), "needed items found on blind prompts"),
    ]
    parts.append('<section><h2>Headline</h2><div class="tiles">' + "".join(
        f'<div class="tile"><div class="big">{esc(v)}</div><div class="cap">{esc(c)}</div></div>'
        for v, c in tiles) + "</div></section>")

    # --- default configuration
    rem = {k: load(f"remarker-{k}") for k in ("lexical", "dense", "rerank", "full")}
    rsum = {k: (v or {}).get("summary", v or {}) for k, v in rem.items()}
    kw3, llm3 = load("keywords-gen"), load("llm-auto-gen-gemini-blind3")
    kw3s = (kw3 or {}).get("summary", {}).get("blind3", {})
    llm3s = (llm3 or {}).get("summary", {}).get("blind3", {})
    fl, ft = load("final-llm"), load("final-template_only")
    cfg_rows = [
        ["<b>Understanding the prompt</b> (block 5)",
         "Decision graph with the generated vocabulary, plus a Gemini check only when words are unknown or no role is named",
         "Keywords only; embeddings for unknown words (not measurable: quota)",
         f"Blind set 3: context recognised {pct(llm3s.get('context_recall'))} with the check vs "
         f"{pct(kw3s.get('context_recall'))} without; needed items {pct(llm3s.get('must_recall'))} both."],
        ["<b>Marking passages</b> (blocks 6/7)", "Keywords + embeddings, no reranker",
         "Keywords only; with reranker; both",
         f"Questions fully supported: embeddings {rsum['dense'].get('questions_fully_supported', '–')}, "
         f"keywords only {rsum['lexical'].get('questions_fully_supported', '–')}, with reranker "
         f"{rsum['full'].get('questions_fully_supported', '–')} at the same precision and extra API calls."],
        ["<b>Check and summary</b> (block 8)", "Two parallel Gemini Flash-Lite calls + code checks, template fallback",
         "Templates only",
         (f"Answers complete {pct(fl['summary']['all_three'])} with the LLM vs "
          f"{pct(ft['summary']['all_three'])} templates only.") if fl and ft else "–"],
    ]
    parts.append(f"""
<section>
<h2>1. The default configuration and why</h2>
<p class="lead">Each stage uses the variant that measured best. All of them are the defaults in
<code>app/pipeline.py</code>; one command runs the whole chain.</p>
{table(["Stage", "Default", "Alternatives measured", "Why"], cfg_rows)}
</section>""")

    # --- five situations
    qb = {q["question"]: q for q in (base or {}).get("questions", [])}
    qrows = [[q["question"], esc(", ".join(q["items"])),
              (OK if qb[q["question"]]["complete"] else NO) if q["question"] in qb else "–",
              OK if q["complete"] else NO] for q in run["questions"]]
    trows = [(f"Situation {x['situation']}", x["timings_ms"]["prompt_analysis"], x["timings_ms"]["remarker"],
              x["timings_ms"]["final"]) for x in run["situations"]]
    srows = [[f"Situation {x['situation']}", x["mode"], x["prompt_method"],
              f"{x['timings_ms']['total'] / 1000:.2f} s", str(x["summary_lines"]),
              str(x["statuses"].get("found", 0)), str(x["statuses"].get("not_documented", 0)),
              OK if x["conflict_in_summary"] else "–", str(len(x["issues"]))] for x in run["situations"]]
    parts.append(f"""
<section>
<h2>2. The five challenge situations, end to end</h2>
<p class="lead">Each situation typed as a clinician would, run through all four blocks.
<b>{round(s['complete'] * 15)} of 15 answers complete</b> with the default configuration
({round(base['summary']['complete'] * 15) if base else '–'} without the LLM).</p>
{table(["Question", "Checklist items that answer it", "Without LLM", "Default"], qrows)}
<h3>Where the time goes</h3>
{legend([("Prompt analysis", 1), ("Marking passages", 2), ("Check and summary (LLM)", 3)])}
{stacked_time_bars(trows)}
{table(["", "Mode", "Prompt via", "Total", "Summary lines", "Items found", "Not documented",
        "Conflict shown", "Issues"], srows)}
</section>""")

    # --- blind prompts
    blind = run.get("blind", [])
    if blind:
        bb = {r["id"]: r for r in (base or {}).get("blind", [])}

        def agg(rows, a, b):
            d = sum(r[b] for r in rows)
            return sum(r[a] for r in rows) / d if d else None
        mrows = [
            ("Role recognised", [sum(r["role_ok"] for r in bb.values()) / len(bb) if bb else None,
                                 sum(r["role_ok"] for r in blind) / len(blind)]),
            ("Needed items found", [agg(list(bb.values()), "must_found", "must_total") if bb else None,
                                    agg(blind, "must_found", "must_total")]),
            ("Key items ranked high", [agg(list(bb.values()), "top_found", "top_total") if bb else None,
                                       agg(blind, "top_found", "top_total")]),
            ("Irrelevant items shown", [agg(list(bb.values()), "forbid_found", "forbid_total") if bb else None,
                                        agg(blind, "forbid_found", "forbid_total")]),
        ]
        bseries = [("Without LLM", 2), ("Default (with Gemini)", 3)]
        lat = sorted(((r["id"], [r["timings_ms"]["total"] / 1000]) for r in blind), key=lambda x: -x[1][0])
        prows = [[r["id"], esc(r["prompt"]), r["mode"], f"{r['timings_ms']['total'] / 1000:.2f} s",
                  f"{r['must_found']}/{r['must_total']}", str(r["statuses"].get("found", 0)),
                  str(r["statuses"].get("not_documented", 0)), str(r["summary_lines"]),
                  esc("; ".join(i[:80] for i in r["issues"][:2])) or "–"] for r in blind]
        parts.append(f"""
<section>
<h2>3. New prompts the system never saw (blind sets 2 and 3)</h2>
<p class="lead">{len(blind)} prompts written after tuning, with other roles and wordings. The full screen
is built for each; the bars compare the checklist with and without the Gemini prompt check.</p>
{legend(bseries)}
{grouped_bars(mrows, bseries, note="Blind prompts with and without the LLM")}
<h3>Time per prompt, slowest first</h3>
{legend([("Seconds, prompt to full screen", 3)])}
{grouped_bars(lat, [("Total", 3)], fmt=lambda v: f"{v:.2f} s", maxv=max(3.0, lat[0][1][0]) if lat else 3.0,
              note="Seconds per blind prompt")}
{table(["ID", "Prompt", "Mode", "Time", "Needed items", "Found", "Not documented", "Summary lines", "Issues"], prows)}
</section>""")

    parts.append("<section><h2>4. Errors found while running everything together, and fixed</h2>" +
                 table(["Problem", "What happened", "Fix"], [[f"<b>{esc(a)}</b>", esc(b), esc(c)] for a, b, c in FIXED]) +
                 "</section>")
    parts.append('<section><h2>5. Earlier comparisons (from report2)</h2><p class="lead">How the decision '
                 'tree versions and the final step compare, kept for reference.</p></section>')
    parts += sections()

    glossary = "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in PIPE_METRICS) + glossary_html()
    page = PAGE.format(body="".join(parts), glossary=glossary)
    page = page.replace("<title>Pipeline Metrics Comparison</title>", "<title>Pipeline End To End</title>")
    page = page.replace("<h1>Pipeline metrics: what works and what is better</h1>",
                        "<h1>The whole pipeline, end to end (report 3)</h1>")
    page = page.replace("</style>", ".tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}"
                        ".tile{border:1px solid var(--border);border-radius:10px;padding:12px}"
                        ".big{font-size:28px;font-weight:700}.cap{color:var(--text2);font-size:13px}</style>")
    return page


if __name__ == "__main__":
    out = RESULTS / "report3.html"
    out.write_text(build(), encoding="utf-8")
    print(out)
