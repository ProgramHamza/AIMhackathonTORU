"""Build eval/results/report2.html: comparison charts and tables from the eval result files.

Usage (from backend/): python -m eval.make_report2
"""
from __future__ import annotations

import html
import json
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"

VERSIONS = [  # (label, file prefix, css series slot)
    ("Old tree (v1)", "v1", 1),
    ("Graph, keywords only", "keywords", 2),
    ("Graph + Gemini check", "llm-auto-gemini", 3),
]
METRICS = [  # key, label, plain explanation, higher_is_better
    ("role_accuracy", "Role recognised",
     "Did it understand who is asking (anaesthetist, GP, …)? Share of prompts with the right role.", True),
    ("must_recall", "Needed items found",
     "Of all the checklist items a prompt needs (allergies, blood thinners, …), how many ended up on the checklist.", True),
    ("top_recall", "Key items ranked high",
     "Of the items that matter most, how many were marked critical or high (not buried at the bottom).", True),
    ("cases_all_must_found", "Prompts fully covered",
     "Share of prompts where nothing needed was missing. Stricter than 'needed items found'.", True),
    ("context_recall", "Context recognised",
     "Did it catch the situation details: the procedure, body part, symptoms, contrast, …", True),
    ("forbidden_rate", "Irrelevant items shown",
     "How often an item we marked as clearly irrelevant was shown anyway (e.g. tumour receptors for an anaesthetist). Lower is better.", False),
]
SPLITS = [
    ("dev", "Development set", "We tuned the tree on these. Scores here are flattering."),
    ("heldout", "Held-out set", "Written early; the vocabulary was later extended to cover them, so also flattering."),
    ("fresh", "Fresh set", "Written after a freeze, but the tree was tuned on its misses afterwards."),
    ("blind", "Blind set 1", "Never tuned on when measured."),
    ("blind2", "Blind set 2", "Newest prompts, never tuned on. The fairest comparison."),
]


def load(name):
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def split_summary(prefix, split):
    for name in (f"{prefix}-{split}", f"{prefix}-final"):
        r = load(name)
        if r and split in r.get("summary", {}):
            return r["summary"][split]
    return None


def pct(v):
    return "–" if v is None or v != v else f"{v * 100:.0f}%"


def esc(s):
    return html.escape(str(s))


# ---------------------------------------------------------------------------
# SVG charts (horizontal grouped bars, values printed, native hover titles)
# ---------------------------------------------------------------------------
def grouped_bars(rows, series, fmt=pct, maxv=1.0, width=720, note=""):
    """rows: [(label, [value per series])]; series: [(name, slot)]"""
    bar_h, gap, group_gap, left, right = 14, 2, 18, 190, 70
    group_h = len(series) * (bar_h + gap) - gap
    height = len(rows) * (group_h + group_gap) + 10
    plot_w = width - left - right
    out = [f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="{esc(note)}">']
    for gx in (0, 0.25, 0.5, 0.75, 1.0):
        x = left + plot_w * gx
        out.append(f'<line class="grid" x1="{x:.1f}" x2="{x:.1f}" y1="0" y2="{height - 6}"/>')
    y = 4
    for label, values in rows:
        out.append(f'<text class="rowlabel" x="{left - 10}" y="{y + group_h / 2 + 4:.1f}" text-anchor="end">{esc(label)}</text>')
        for (name, slot), v in zip(series, values):
            if v is None or v != v:
                out.append(f'<text class="val" x="{left + 4}" y="{y + bar_h - 3}">not measured</text>')
            else:
                w = max(plot_w * min(v, maxv) / maxv, 3)
                out.append(f'<g class="mark"><title>{esc(label)} – {esc(name)}: {fmt(v)}</title>'
                           f'<rect class="s{slot}" x="{left}" y="{y}" width="{w:.1f}" height="{bar_h}" rx="3"/>'
                           f'<rect class="hit" x="{left}" y="{y - 1}" width="{plot_w}" height="{bar_h + 2}"/>'
                           f'<text class="val" x="{left + w + 6:.1f}" y="{y + bar_h - 3}">{fmt(v)}</text></g>')
            y += bar_h + gap
        y += group_gap - gap
    out.append("</svg>")
    return "".join(out)


def legend(series):
    return '<div class="legend">' + "".join(
        f'<span><i class="sw s{slot}"></i>{esc(n)}</span>' for n, slot in series) + "</div>"


def table(headers, rows):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


# ---------------------------------------------------------------------------
def sections() -> list[str]:
    """The report's sections as HTML strings (reused by make_report3)."""
    series = [(label, slot) for label, _, slot in VERSIONS]
    parts = []

    # --- 1. decision tree on the fairest set
    b2 = [split_summary(prefix, "blind2") for _, prefix, _ in VERSIONS]
    rows = [(m_label, [s.get(key) if s else None for s in b2]) for key, m_label, _, _ in METRICS]
    chart1 = grouped_bars(rows, series, note="Decision tree versions on blind set 2")
    t1 = table(["Metric", "What it means"] + [n for n, _ in series] + ["Better"],
               [[f"<b>{esc(lbl)}</b>", esc(expl)] + [pct(s.get(k)) if s else "–" for s in b2] +
                ["higher" if hib else "lower"] for k, lbl, expl, hib in METRICS])
    size_time = table(
        ["", "What it means"] + [n for n, _ in series],
        [["<b>Checklist length</b>", "Average number of items shown. Longer finds more but is more to read."] +
         [f"{s['avg_checklist_size']:.1f}" if s else "–" for s in b2],
         ["<b>Time per prompt</b>", "How long understanding the prompt takes (median)."] +
         [(f"{s['latency_ms_p50']:.0f} ms" if s['latency_ms_p50'] >= 10 else f"{s['latency_ms_p50']:.1f} ms") if s else "–"
          for s in b2],
         ["<b>LLM calls</b>", "How many of the 15 prompts needed the Gemini check."] +
         [f"{int(s.get('llm_calls') or 0)} of {s['cases']}" if s else "–" for s in b2]])
    parts.append(f"""
<section>
<h2>1. Understanding the prompt: which decision tree is better?</h2>
<p class="lead">Measured on <b>blind set 2</b>: 15 prompts written after the last change and never used
for tuning, so it is the fairest test. <b>The graph with the Gemini check wins on every measure</b>; the
graph alone already fixes most of the old tree's misses.</p>
{legend(series)}
{chart1}
{t1}
<h3>Cost of the improvement</h3>
{size_time}
</section>""")

    # --- 2. needed items found across sets (shows the tuning effect)
    rows2, trows = [], []
    for split, s_label, s_expl in SPLITS:
        vals = [split_summary(prefix, split) for _, prefix, _ in VERSIONS]
        rows2.append((s_label, [v.get("must_recall") if v else None for v in vals]))
        trows.append([f"<b>{esc(s_label)}</b>", esc(s_expl)] + [pct(v.get("must_recall")) if v else "–" for v in vals]
                     + [str(next((v["cases"] for v in vals if v), "–"))])
    parts.append(f"""
<section>
<h2>2. Why the test set matters</h2>
<p class="lead">The same metric, <b>needed items found</b>, on every set we have. On the sets we tuned on, the
graph scores 100%. On prompts it never saw, it scores lower: that gap is how much the tuning flatters.
Trust the blind sets.</p>
{legend(series)}
{grouped_bars(rows2, series, note="Needed items found per evaluation set")}
{table(["Set", "What it is"] + [n for n, _ in series] + ["Prompts"], trows)}
</section>""")

    # --- 3. final step
    fl, ft = load("final-llm"), load("final-template_only")
    if fl and ft:
        fseries = [("Templates only (no LLM)", 2), ("With Gemini (two parallel calls)", 3)]
        frows = [
            ("On the checklist", [ft["summary"]["on_checklist"], fl["summary"]["on_checklist"]]),
            ("Right status", [ft["summary"]["status_ok"], fl["summary"]["status_ok"]]),
            ("Linked to a right source", [ft["summary"]["source_hit"], fl["summary"]["source_hit"]]),
            ("Visible in the summary", [ft["summary"]["visible"], fl["summary"]["visible"]]),
            ("All three at once", [ft["summary"]["all_three"], fl["summary"]["all_three"]]),
        ]
        expl = {
            "On the checklist": "The item that answers the question is on the list for this role and task.",
            "Right status": "Found when the documents have it, 'not documented' when they don't (e.g. no record of the follow-up ultrasound).",
            "Linked to a right source": "A top passage for the item comes from a document the challenge lists as a source.",
            "Visible in the summary": "The answer shows in the summary panel without clicking, as the challenge requires.",
            "All three at once": "Right status, right source and visible: the closest we have to the challenge's 'correct answer'.",
        }
        qrows = []
        tq = {q["question"]: q for q in ft["questions"]}
        for q in fl["questions"]:
            t = tq[q["question"]]
            ok = lambda r: '<span class="ok">✓ yes</span>' if r else '<span class="no">✗ no</span>'
            qrows.append([q["question"], esc(", ".join(q["items"])), ok(t["visible"] and t["status_ok"] and t["source_hit"]),
                          ok(q["visible"] and q["status_ok"] and q["source_hit"])])
        srows = [[f"Situation {s['situation']}", f"{s['plan_ms']:.0f} ms", f"{s['remark_ms']:.0f} ms",
                  f"{s['final_ms']:.0f} ms", f"<b>{s['total_ms'] / 1000:.2f} s</b>", str(s["dropped_flags"])]
                 for s in fl["situations"]]
        lat_rows = [(f"Situation {s['situation']}", [s["total_ms"] / 1000]) for s in fl["situations"]]
        parts.append(f"""
<section>
<h2>3. The final step: summary with and without the LLM</h2>
<p class="lead">On the five challenge situations (15 questions). <b>With Gemini, all 15 answers are complete;
templates alone get 13</b>, because two answers sit on the checklist but not in the summary. Gemini's
ranking check moves them up.</p>
{legend(fseries)}
{grouped_bars(frows, fseries, note="Final step with and without the LLM")}
{table(["Measure", "What it means", fseries[0][0], fseries[1][0]],
       [[f"<b>{esc(l)}</b>", esc(expl[l]), pct(v[0]), pct(v[1])] for l, v in frows])}
<h3>Per question</h3>
{table(["Question", "Checklist items that answer it", fseries[0][0], fseries[1][0]], qrows)}
<h3>Speed, end to end (prompt → full screen)</h3>
<p>Challenge limit: 10 s. Our target: under 3 s. Median <b>{fl['summary']['latency_ms_p50'] / 1000:.2f} s</b>,
slowest <b>{fl['summary']['latency_ms_max'] / 1000:.2f} s</b>. Without the LLM: {ft['summary']['latency_ms_p50']:.0f} ms.</p>
{legend([("Seconds, prompt to full screen", 3)])}
{grouped_bars(lat_rows, [("Total", 3)], fmt=lambda v: f"{v:.2f} s", maxv=3.0, note="Seconds per situation")}
{table(["", "Prompt analysis", "Remarker", "Final step (LLM)", "Total", "Passages dropped by the check"], srows)}
</section>""")

    # --- 4. what works
    w = '<span class="ok">✓ works</span>'
    parts.append(f"""
<section>
<h2>4. Which models and keys work</h2>
<p class="lead">Checked today with one small request each.</p>
{table(["Model / service", "Key 1 (API_KEY)", "Key 2 (GEMINI_API_KEY_2)", "Speed", "Used for"], [
    ["Gemini 3.5 Flash", '<span class="no">✗ quota used up</span>', w, "≈1.8 s", "Prompt check (when quota allows)"],
    ["Gemini Flash-Lite", w, w, "≈0.75–0.85 s", "Final step, both calls"],
    ["Gemini embeddings (embedding-2)", w + " (quota was out earlier)", w, "≈0.8 s", "Remarker, built once per patient"],
    ["Jina reranker", "–", "–", "–", "Tested by the remarker session: no measured gain, left off"],
    ["Mistral 7B, local", "–", "–", "too slow on this laptop's CPU", "Only a last-resort fallback; doesn't fit in free RAM with a large context"],
    ["Claude", "–", "–", "–", "Ready in code; no key yet"],
])}
</section>""")

    return parts


def glossary_html() -> str:
    return "".join(f"<dt>{esc(lbl)}</dt><dd>{esc(expl)}</dd>" for _, lbl, expl, _ in METRICS)


def build() -> str:
    return PAGE.format(body="".join(sections()), glossary=glossary_html())


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Metrics Comparison</title>
<style>
:root {{ color-scheme: light; --surface:#fcfcfb; --panel:#ffffff; --text:#0b0b0b; --text2:#52514e; --muted:#8a897f;
  --grid:#e7e6e1; --border:#e2e1dc; --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --ok:#008300; --no:#c83232; }}
@media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) {{ color-scheme: dark; --surface:#1a1a19;
  --panel:#222220; --text:#f0efec; --text2:#c3c2b7; --muted:#8f8e86; --grid:#33332f; --border:#3a3a36;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --ok:#4fbf4f; --no:#ec7070; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface:#1a1a19; --panel:#222220; --text:#f0efec; --text2:#c3c2b7;
  --muted:#8f8e86; --grid:#33332f; --border:#3a3a36; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --ok:#4fbf4f; --no:#ec7070; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--surface); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 28px 16px 60px; }}
h1 {{ font-size: 24px; margin: 0 0 6px; }} h2 {{ font-size: 19px; margin: 0 0 6px; }} h3 {{ font-size: 15px; margin: 22px 0 6px; }}
.sub {{ color: var(--text2); margin: 0 0 22px; }}
section {{ background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 18px; margin: 0 0 18px; }}
.lead {{ color: var(--text2); margin: 0 0 12px; }}
.legend {{ display:flex; flex-wrap:wrap; gap:6px 18px; font-size:13px; color:var(--text2); margin: 4px 0 6px; }}
.legend span {{ display:inline-flex; align-items:center; gap:6px; }}
.sw {{ width:12px; height:12px; border-radius:3px; display:inline-block; }}
.sw.s1, rect.s1 {{ background: var(--s1); fill: var(--s1); }} .sw.s2, rect.s2 {{ background: var(--s2); fill: var(--s2); }}
.sw.s3, rect.s3 {{ background: var(--s3); fill: var(--s3); }}
.chart {{ width: 100%; height: auto; display:block; margin: 4px 0 10px; }}
.chart .grid {{ stroke: var(--grid); stroke-width: 1; }}
.chart text {{ font-size: 12px; fill: var(--text2); }} .chart .rowlabel {{ fill: var(--text); font-size: 12.5px; }}
.chart .val {{ fill: var(--text); font-weight: 600; }}
.chart .hit {{ fill: transparent; }} .chart .mark:hover rect:not(.hit) {{ opacity: .8; }}
.tablewrap {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
th, td {{ text-align: left; padding: 7px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }}
th {{ color: var(--text2); font-weight: 600; }}
.ok {{ color: var(--ok); font-weight: 600; }} .no {{ color: var(--no); font-weight: 600; }}
dl {{ margin: 0; }} dt {{ font-weight: 600; margin-top: 8px; }} dd {{ margin: 2px 0 0; color: var(--text2); }}
.caveat li {{ margin: 4px 0; color: var(--text2); }}
@media (max-width: 600px) {{ .chart .rowlabel {{ font-size: 11px; }} }}
</style></head>
<body><main>
<h1>Pipeline metrics: what works and what is better</h1>
<p class="sub">Clinical documentation app, blocks 5–8. All numbers come from the evaluation runs in
<code>backend/eval/results</code>. Hover a bar to see its value.</p>
<section><h2>The metrics in one sentence each</h2><dl>{glossary}</dl></section>
{body}
<section><h2>What these numbers do not prove</h2><ul class="caveat">
<li>The team wrote the test prompts and the expected answers, not doctors. A clinician should review them.</li>
<li>Blind sets are small (12–15 prompts), so one prompt moves a score by about 7 points.</li>
<li>The final-step check uses our own proxy (item, status, source document, visible), not the jury's reading of the
answer text. The jury may judge wording and completeness differently.</li>
<li>Gemini answers vary a little between runs; latency depends on the network and the free-tier quota.</li>
</ul></section>
</main></body></html>"""


if __name__ == "__main__":
    out = RESULTS / "report2.html"
    out.write_text(build(), encoding="utf-8")
    print(out)
