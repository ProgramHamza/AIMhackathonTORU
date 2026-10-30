"""Build eval/results/report5.html: the whole system against simple baselines.

Needs eval/results/baselines.json (python -m eval.run_baselines ...).
Usage (from backend/): python -m eval.make_report5
"""
from __future__ import annotations

from .make_report2 import PAGE, RESULTS, esc, grouped_bars, legend, load, pct, table

SYSTEMS = ["ours", "ours_nollm", "llm_only", "rules_only"]
SLOT = {"ours": 3, "ours_nollm": 1, "llm_only": 2, "rules_only": 4}
VERDICT = {"correct": '<span class="ok">correct</span>', "partial": "partial", "missing": '<span class="no">missing</span>',
           "wrong": '<span class="no">wrong</span>'}

GLOSSARY = [
    ("Answer score", "The 15 challenge questions, graded against the expected answers: correct = 1, partial = 0.5 "
     "(e.g. the drug without its dose), missing or wrong = 0."),
    ("Wrong answers", "The screen says something that contradicts the expected answer. Worse than missing: a clinician could act on it."),
    ("Needed topics addressed", "On the 27 blind prompts: share of the topics the request needs that the screen answers or marks 'not documented'."),
    ("Irrelevant topics shown", "On the blind prompts: share of clearly irrelevant topics shown anyway. Lower is better."),
    ("Contradiction score", "Real contradictions found (out of 7 known) minus false alarms, as the challenge counts it."),
    ("Traceability", "Share of the screen's facts whose quote is found word for word in the document it cites. Checked in code."),
    ("Unsupported numbers", "Facts containing a number that is not in the cited document: a likely invented or altered value. Checked in code."),
    ("Time", "From the request to the finished screen, live calls, no cache."),
    ("Data sent to the cloud", "Characters per request that left the device (after de-identification)."),
]


RUNS = [  # earlier saved runs, oldest first; the current baselines.json comes last
    ("baselines-v1", "Run 1: first"),
    ("baselines-v2", "Run 2: template fix"),
]
CURRENT_RUN = "Run 3: keywords"


def before_after(runs, by_q, qids) -> str:
    """Our system across the saved runs: what each change did to the same 32 prompts."""
    names = [n for n, _ in runs]
    sums = [d["summary"] for _, d in runs]
    verdicts = []
    for _, d in runs:
        v = {}
        for r in d["rows"]:
            if r["kind"] == "situation":
                for x in ("ours", "ours_nollm"):
                    v.update({(q, x): a for q, a in r["systems"][x]["answers"].items()})
        verdicts.append(v)
    ms = lambda v: f"{v / 1000:.2f} s"
    num = lambda v: f"{v:,.0f}"
    spec = [("Answer score", "answer_score", pct), ("Needed topics addressed", "needed_addressed", pct),
            ("Irrelevant topics shown", "irrelevant_shown", pct), ("Traceability", "traceability", pct),
            ("Unsupported numbers per screen", "unsupported_numbers_per_screen", lambda v: f"{v:g}"),
            ("Median time", "latency_ms_p50", ms), ("Slowest", "latency_ms_max", ms),
            ("Under 3 s", "under_3s", pct), ("Characters sent per request", "chars_sent_per_request", num)]
    tables = []
    for x in ("ours", "ours_nollm"):
        rows = [[name] + [fmt(sm[x][key]) for sm in sums] for name, key, fmt in spec]
        tables.append(f"<h3>{esc(sums[-1][x]['label'])}</h3>{table([''] + names, rows)}")
    changed = [[q] + [" → ".join(VERDICT.get(v.get((q, x), ""), "–") for v in verdicts) for x in ("ours", "ours_nollm")]
               for q in qids if any(len({v.get((q, x)) for v in verdicts}) > 1 for x in ("ours", "ours_nollm"))]
    return f"""
<section><h2>5. What each change did</h2>
<p class="lead"><b>Run 1 to 2, the template fix:</b> the first run left 5 answers partial although the search had found every
needed passage. The summary line of an item quoted at most 2 of them, older documents were hidden even when they held the
detail (the pathology report's receptor percentages, the only HbA1c value), and two passages saying the same thing could fill
both slots. Since run 2 a drug list quotes every current drug, other items quote verified facts first from any date, and repeats
are skipped; the judge sees up to 700 characters per screen line instead of 260, for every system alike.</p>
<p class="lead"><b>Run 2 to 3, keywords:</b> every line now shows the few words that answer the item ("Aspirin 100 mg oral
1-0-0-0 (Arztbrief 04/2016)") instead of the whole sentence with a document number. The words come from the verified facts of
blocks 1-4 or, without a fitting fact, from the clause naming the item; each keyword keeps the document offsets of its words,
so the source view can highlight them. No LLM is involved. The sentence splitter also no longer cuts at "wg." (wegen).</p>
{"".join(tables)}
<h3>Questions whose grade changed</h3>
{table(["Question"] + [esc(sums[-1][x]["label"]) for x in ("ours", "ours_nollm")], changed) if changed else '<p class="lead">None.</p>'}
</section>"""


def build() -> str:
    data = load("baselines")
    if not data:
        raise SystemExit("eval/results/baselines.json missing: run python -m eval.run_baselines first")
    s, rows = data["summary"], data["rows"]
    series = [(s[x]["label"], SLOT[x]) for x in SYSTEMS]
    parts = []

    # headline: one tile per system with its answer score
    tiles = "".join(f'<div class="tile"><div class="big">{s[x]["answers_correct"]}/{s[x]["questions_graded"]}</div>'
                    f'<div class="cap">{esc(s[x]["label"])}: correct answers ({s[x]["answers_partial"]} partial, '
                    f'{s[x]["answers_wrong"]} wrong)</div></div>' for x in SYSTEMS)
    parts.append(f'<section><h2>Headline</h2><div class="tiles">{tiles}</div></section>')

    quality = [("Answer score (15 questions)", [s[x]["answer_score"] for x in SYSTEMS]),
               ("Needed topics addressed (blind)", [s[x]["needed_addressed"] for x in SYSTEMS]),
               ("Traceability (exact quote)", [s[x]["traceability"] for x in SYSTEMS]),
               ("Requests under 3 s", [s[x]["under_3s"] for x in SYSTEMS])]
    parts.append(f"""
<section><h2>1. Quality at a glance</h2>
<p class="lead">Same prompts for every system: the 5 challenge situations and 27 blind prompts. Higher is better for all four bars.</p>
{legend(series)}{grouped_bars(quality, series, note="Quality by system")}
</section>""")

    # full metric table
    def fmt(x, key, kind="pct"):
        v = s[x].get(key)
        if v is None:
            return "–"
        return pct(v) if kind == "pct" else (f"{v / 1000:.2f} s" if kind == "s" else str(v))
    metric_rows = [
        ["<b>Answer score</b>"] + [fmt(x, "answer_score") for x in SYSTEMS],
        ["Correct / partial / missing / wrong"] + [f"{s[x]['answers_correct']} / {s[x]['answers_partial']} / {s[x]['answers_missing']} / {s[x]['answers_wrong']}" for x in SYSTEMS],
        ["<b>Needed topics addressed</b> (blind)"] + [fmt(x, "needed_addressed") for x in SYSTEMS],
        ["Irrelevant topics shown (blind, lower is better)"] + [fmt(x, "irrelevant_shown") for x in SYSTEMS],
        ["<b>Contradiction score</b> (found − false alarms)"] + [str(s[x]["contradiction_score"]) for x in SYSTEMS],
        ["Real contradictions found"] + [esc(", ".join(s[x]["contradictions_found"]) or "none") for x in SYSTEMS],
        ["False alarms"] + [str(s[x]["contradiction_false_alarms"]) for x in SYSTEMS],
        ["<b>Traceability</b> (quote found word for word)"] + [fmt(x, "traceability") for x in SYSTEMS],
        ["Facts linked to a document"] + [fmt(x, "linked_share") for x in SYSTEMS],
        ["Unsupported numbers per screen"] + [str(s[x]["unsupported_numbers_per_screen"]) for x in SYSTEMS],
        ["Screens with an unsupported number"] + [str(s[x]["screens_with_unsupported_numbers"]) for x in SYSTEMS],
        ["Lines per screen"] + [str(s[x]["statements_per_screen"]) for x in SYSTEMS],
        ["'Not documented' lines per screen"] + [str(s[x]["not_documented_lines_per_screen"]) for x in SYSTEMS],
        ["<b>Median time</b>"] + [fmt(x, "latency_ms_p50", "s") for x in SYSTEMS],
        ["Slowest"] + [fmt(x, "latency_ms_max", "s") for x in SYSTEMS],
        ["Under 10 s (challenge limit)"] + [fmt(x, "under_10s") for x in SYSTEMS],
        ["Model calls per request"] + [str(s[x]["llm_calls_per_request"]) for x in SYSTEMS],
        ["Characters sent to the cloud per request"] + [f"{s[x]['chars_sent_per_request']:,}" for x in SYSTEMS],
        ["Identifiers removed per request (by our gate)"] + [str(s[x]["identifiers_removed_per_request"]) for x in SYSTEMS],
        ["Requests that failed"] + [str(s[x]["errors"]) for x in SYSTEMS],
        ["Screens graded by the judge"] + [fmt(x, "graded_share") for x in SYSTEMS],
    ]
    parts.append(f"""
<section><h2>2. Every metric</h2>
{table(["Metric"] + [s[x]["label"] for x in SYSTEMS], metric_rows)}
</section>""")

    # answers per question
    sit = [r for r in rows if r["kind"] == "situation"]
    qids = sorted({q for r in sit for x in SYSTEMS for q in r["systems"][x]["answers"]}, key=lambda q: [int(p) for p in q.split(".")])
    by_q = {}
    for r in sit:
        for x in SYSTEMS:
            for q, v in r["systems"][x]["answers"].items():
                by_q[(q, x)] = v
    qrows = [[q] + [VERDICT.get(by_q.get((q, x), ""), "–") for x in SYSTEMS] for q in qids]
    verdict_rows = [(v.capitalize(), [s[x][f"answers_{v}"] / max(s[x]["questions_graded"], 1) for x in SYSTEMS])
                    for v in ("correct", "partial", "missing", "wrong")]
    parts.append(f"""
<section><h2>3. The 15 challenge questions</h2>
<p class="lead">Graded by one judge call per situation that saw all four screens, shuffled and unlabelled.</p>
{legend(series)}{grouped_bars(verdict_rows, series, note="Verdict shares by system")}
{table(["Question"] + [s[x]["label"] for x in SYSTEMS], qrows)}
</section>""")

    # speed and cost
    lat = [("Median time (s)", [s[x]["latency_ms_p50"] / 1000 for x in SYSTEMS]),
           ("Slowest (s)", [s[x]["latency_ms_max"] / 1000 for x in SYSTEMS])]
    maxlat = max(max(v) for _, v in lat) or 1
    sent = [("Characters sent per request", [s[x]["chars_sent_per_request"] for x in SYSTEMS])]
    maxsent = max(sent[0][1]) or 1
    parts.append(f"""
<section><h2>4. Speed, cost and data exposure</h2>
<p class="lead">The one-call baseline sends the whole record with every request; our system sends only the passages the task needs.</p>
{legend(series)}{grouped_bars(lat, series, fmt=lambda v: f"{v:.2f} s", maxv=maxlat, note="Time by system")}
{grouped_bars(sent, series, fmt=lambda v: f"{int(v):,}", maxv=maxsent, note="Characters sent per request")}
</section>""")

    # blind prompts per prompt
    runs = [(label, d) for name, label in RUNS if (d := load(name))] + [(CURRENT_RUN, data)]
    if len(runs) > 1:
        parts.append(before_after(runs, by_q, qids))

    bl = [r for r in rows if r["kind"] == "blind"]
    brows = []
    for r in bl:
        cells = []
        for x in SYSTEMS:
            n = r["systems"][x]["needed"]
            cells.append(f"{sum(n.values())}/{len(n)}" if n else "–")
        brows.append([r["key"], esc(r["prompt"])] + cells)
    parts.append(f"""
<section><h2>6. Blind prompts: needed topics addressed</h2>
{table(["ID", "Prompt"] + [s[x]["label"] for x in SYSTEMS], brows)}
</section>""")

    parts.append("""<section><h2>What the comparison shows</h2><ul class="caveat">
<li><b>Our system answers all 15 questions correctly, and never invents.</b> No partial, missing or wrong answers; its screens
contain no number that is absent from the cited document, and every quote is found word for word.</li>
<li><b>The one-call LLM baseline misses most of what a task needs</b> (needed topics addressed about a third of the time on unseen
prompts), paraphrases about 1 quote in 25, and finds one contradiction plus one false alarm, although it sees the whole record.
Its results vary from run to run: across the three runs it found 1 to 2 contradictions and 22 to 33% of needed topics.</li>
<li><b>The rules baseline is instant and always traceable</b>, but it misses half of the needed topics, cannot say "not documented"
reliably and finds no contradictions.</li>
<li><b>Our system with and without the LLM score the same here.</b> The decision graph, the remarker and the verified facts do the
work the judge measures; the LLM orders the list and writes the summary panel. It costs about 1.6 s and 2 calls.</li>
<li><b>Keywords cost two blind topics</b> (run 3, section 5): the judge marked imaging findings for C10 and bleeding history for
C15 as no longer addressed (107 of 109 needed topics, 98%). For C10 the screen shows the same passages as in run 2; for C15 the
shortened line keeps the antiplatelet drug but loses the sentence around it. Every source is still one click away, with the
keyword's words highlighted.</li>
<li><b>The 5 partial answers of the first run are fixed</b> (section 5): the search had found every needed passage, but the summary
line showed too few of them. The fix changed only which found passages are quoted; the graph and the search are unchanged.</li>
<li><b>15 of 15 is on questions the team also used while building.</b> The blind prompts (needed topics 98%) are the fairer test of
generalisation; a new patient record would be the real one.</li>
<li><b>Data sent to the cloud:</b> our two parallel calls both carry the selected passages, and the summary call repeats them in its
template lines, so a request sends more characters than the whole record. It is de-identified either way; removing the repetition
is a cheap saving.</li>
</ul></section>
<section><h2>How the comparison was made, and its limits</h2><ul class="caveat">
<li><b>Baseline A</b> gets the whole record (8 documents) and the request in one Gemini Flash-Lite call (the same model our final step uses) and
returns facts with document IDs and quotes, 'not documented' items and contradictions. No graph, no retrieval, no checks.</li>
<li><b>Baseline B</b> maps words in the request to topics with if/else rules and shows every sentence containing a topic keyword (generic German
clinical words, nothing specific to this patient), up to 4 per topic.</li>
<li><b>Grading</b> is done by a Gemini model: the same family as Baseline A, which may favour its style. Traceability, unsupported numbers,
time, calls and data volume are checked in code and do not depend on the judge.</li>
<li>The team wrote the blind prompts and their needed topics; the known contradictions come from reading the documents and from the evidence backend.</li>
<li>All runs used free API keys; no billing was enabled. Every text, including the judge's input, passed the de-identification gate.</li>
</ul></section>""")

    glossary = "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in GLOSSARY)
    page = PAGE.format(body="".join(parts), glossary=glossary)
    page = page.replace("<title>Pipeline Metrics Comparison</title>", "<title>System Versus Baselines</title>")
    page = page.replace("<h1>Pipeline metrics: what works and what is better</h1>", "<h1>The whole system against baselines (report 5)</h1>")
    page = page.replace("</style>", ":root{--s4:#eda100}"
                        "@media (prefers-color-scheme: dark){:root:where(:not([data-theme=\"light\"])){--s4:#c98500}}"
                        ":root[data-theme=\"dark\"]{--s4:#c98500}"
                        ".sw.s4, rect.s4 {background: var(--s4); fill: var(--s4);}"
                        ".tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px}"
                        ".tile{border:1px solid var(--border);border-radius:10px;padding:12px}"
                        ".big{font-size:26px;font-weight:700}.cap{color:var(--text2);font-size:13px}</style>")
    return page


if __name__ == "__main__":
    out = RESULTS / "report5.html"
    out.write_text(build(), encoding="utf-8")
    print(out)
