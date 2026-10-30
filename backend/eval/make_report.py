"""Build reports/metrics.html from eval/results/*.json (metrics only, no document text).

  python -m eval.make_report
"""
from __future__ import annotations

import html
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
OUT = HERE.parent / "reports" / "metrics.html"

SYSTEMS = [("Old tree", "--s1"), ("Graph (keywords)", "--s2"), ("Graph + Gemini", "--s3")]
SETS = ["dev", "heldout", "fresh", "blind", "blind2", "blind3"]
SET_NAMES = {"dev": "Dev", "heldout": "Held-out", "fresh": "Fresh", "blind": "Blind 1",
             "blind2": "Blind 2", "blind3": "Blind 3"}


def load(name):
    p = RESULTS / f"{name}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def split(result, s):
    return (result or {}).get("summary", {}).get(s)


def esc(x):
    return html.escape(str(x))


def pct(v):
    return "–" if v is None else f"{round(100 * v)}%"


# ---------------------------------------------------------------------------
# SVG charts
# ---------------------------------------------------------------------------
def grouped_bars(title, categories, series, ymax=1.0, fmt=pct, height=260):
    """categories: [label]; series: [(name, css var, [value or None])]."""
    W, H = 720, height
    left, right, top, bottom = 44, 12, 16, 46
    pw, ph = W - left - right, H - top - bottom
    n_cat, n_ser = len(categories), len(series)
    group_w = pw / n_cat
    bar_w = min(34, (group_w - 18) / n_ser - 2)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}" class="chart">']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        y = top + ph * (1 - t)
        parts.append(f'<line x1="{left}" x2="{W - right}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{left - 6}" y="{y + 4:.1f}" class="tick" text-anchor="end">{fmt(t * ymax)}</text>')
    for c, cat in enumerate(categories):
        gx = left + c * group_w + (group_w - n_ser * (bar_w + 2)) / 2
        for s, (name, var, values) in enumerate(series):
            v = values[c]
            x = gx + s * (bar_w + 2)
            if v is None:
                parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{top + ph - 4}" class="na" text-anchor="middle">n/a</text>')
                continue
            h = max(1.5, ph * min(v, ymax) / ymax)
            y = top + ph - h
            r = min(4, bar_w / 2, h)
            path = (f"M{x:.1f},{top + ph:.1f} V{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
                    f"H{x + bar_w - r:.1f} Q{x + bar_w:.1f},{y:.1f} {x + bar_w:.1f},{y + r:.1f} V{top + ph:.1f} Z")
            parts.append(f'<path d="{path}" style="fill:var({var})" class="bar">'
                         f'<title>{esc(name)} · {esc(cat)}: {fmt(v)}</title></path>')
            parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{y - 4:.1f}" class="val" text-anchor="middle">{fmt(v)}</text>')
        parts.append(f'<text x="{left + c * group_w + group_w / 2:.1f}" y="{H - bottom + 18}" class="cat" '
                     f'text-anchor="middle">{esc(cat)}</text>')
    parts.append(f'<line x1="{left}" x2="{W - right}" y1="{top + ph}" y2="{top + ph}" class="axis"/>')
    parts.append("</svg>")
    legend = "".join(f'<span class="key"><i style="background:var({var})"></i>{esc(name)}</span>'
                     for name, var, _ in series) if n_ser > 1 else ""
    return f'<figure><figcaption>{esc(title)}</figcaption><div class="legend">{legend}</div>{"".join(parts)}</figure>'


def hbars(title, rows, unit="ms"):
    """rows: [(label, value, note)] - one series, horizontal, linear scale."""
    W = 720
    left, right, bar_h, gap = 230, 90, 22, 10
    H = 16 + len(rows) * (bar_h + gap)
    vmax = max(v for _, v, _ in rows) or 1
    pw = W - left - right
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(title)}" class="chart">']
    for i, (label, v, note) in enumerate(rows):
        y = 8 + i * (bar_h + gap)
        w = max(2, pw * v / vmax)
        r = min(4, w / 2)
        path = (f"M{left},{y} H{left + w - r:.1f} Q{left + w:.1f},{y} {left + w:.1f},{y + r} "
                f"V{y + bar_h - r} Q{left + w:.1f},{y + bar_h} {left + w - r:.1f},{y + bar_h} H{left} Z")
        parts.append(f'<text x="{left - 8}" y="{y + 15}" class="cat" text-anchor="end">{esc(label)}</text>')
        parts.append(f'<path d="{path}" style="fill:var(--s1)" class="bar"><title>{esc(label)}: {v:,.0f} {unit} – {esc(note)}</title></path>')
        parts.append(f'<text x="{left + w + 6:.1f}" y="{y + 15}" class="val">{v:,.0f} {unit}</text>')
    parts.append("</svg>")
    return f'<figure><figcaption>{esc(title)}</figcaption>{"".join(parts)}</figure>'


def table(headers, rows, cls=""):
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tablewrap"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


# ---------------------------------------------------------------------------
def build() -> str:
    v1 = load("v1-final") or {}
    v1b2, v1b3 = load("v1-blind2"), load("v1-blind3")
    kw = load("keywords-final2")
    llm = load("llm-auto-gemini-final")
    llm_b2, llm_b3 = load("llm-auto-gemini-blind2"), load("llm-auto-gemini-blind3")

    def v1_split(s):
        return split(v1, s) or split(v1b2, s) or split(v1b3, s) or (v1b3 or {}).get("overall") if s == "blind3" else split(v1, s) or split(v1b2, s)

    def llm_split(s):
        return split(llm, s) or split(llm_b2, s) or split(llm_b3, s)

    systems_by_set = {s: [v1_split(s), split(kw, s), llm_split(s)] for s in SETS}

    # --- Part A, chart 1: the unseen set ---
    b3 = systems_by_set["blind3"]
    metrics_a = [("Right role", "role_accuracy"), ("Required items found", "must_recall"),
                 ("Key items ranked high", "top_recall"), ("Prompts with everything", "cases_all_must_found")]
    chart_a = grouped_bars(
        "Unseen prompts (Blind 3, 12 prompts): how well each version understands the request",
        [m for m, _ in metrics_a],
        [(name, var, [(b3[i] or {}).get(key) for _, key in metrics_a]) for i, (name, var) in enumerate(SYSTEMS)])
    rows_a = []
    for i, (name, _) in enumerate(SYSTEMS):
        m = b3[i] or {}
        rows_a.append([esc(name), pct(m.get("role_accuracy")), pct(m.get("must_recall")),
                       pct(m.get("top_recall")), pct(m.get("cases_all_must_found")),
                       pct(m.get("forbidden_rate")), f"{m.get('avg_checklist_size', 0):.1f}",
                       f"{m.get('latency_ms_p50', 0):,.0f} ms"])
    table_a = table(["Version", "Right role", "Required items found", "Key items ranked high",
                     "Prompts with everything", "Irrelevant items shown", "Checklist length",
                     "Time per prompt (median)"], rows_a)

    # --- Part A, chart 2: across sets ---
    chart_b = grouped_bars(
        "Required items found, per test set (older sets were used to improve the graph)",
        [SET_NAMES[s] for s in SETS],
        [(name, var, [(systems_by_set[s][i] or {}).get("must_recall") for s in SETS])
         for i, (name, var) in enumerate(SYSTEMS)])
    rows_b = []
    for s in SETS:
        cells = [SET_NAMES[s], str((systems_by_set[s][1] or {}).get("cases", "–"))]
        for i in range(3):
            m = systems_by_set[s][i]
            cells.append(pct(m.get("must_recall")) if m else "–")
        cells.append("no (never seen)" if s == "blind3" else "yes")
        rows_b.append(cells)
    table_b = table(["Test set", "Prompts", "Old tree", "Graph (keywords)", "Graph + Gemini",
                     "Used to tune the current graph?"], rows_b)

    # --- Part B: remarker ---
    configs = [("Keywords only", "remarker-lexical"), ("Keywords + reranker", "remarker-rerank"),
               ("Keywords + embeddings", "remarker-dense"), ("Everything", "remarker-full")]
    rm = [(label, load(f)) for label, f in configs]
    rm = [(label, r) for label, r in rm if r]

    def checks_ok(r):
        a, b = r["summary"]["checks_ok"].split("/")
        return int(a) / int(b)

    chart_c = grouped_bars("Remarker: share of the 18 answer checks passed, by configuration",
                           [label for label, _ in rm], [("Checks passed", "--s1", [checks_ok(r) for _, r in rm])],
                           height=230)
    rows_c = []
    for label, r in rm:
        s = r["summary"]
        rows_c.append([esc(label), s["checks_ok"], s["questions_fully_supported"], pct(s["status_accuracy"]),
                       pct(s["source_recall"]), pct(s["flag_precision"]), pct(s["current_value_correct"]),
                       f"{s['avg_flags_per_item']:.1f}", s["offsets_exact"],
                       f"{s['remark_ms_p50']:.0f} ms", str(s["api_calls_per_query"])])
    table_c = table(["Configuration", "Checks passed", "Questions fully supported", "Right status",
                     "Source documents found", "Flags from the right documents", "Current value right",
                     "Flags per item", "Highlights exact", "Time per query", "API calls per query"], rows_c)

    # per-question grid
    q_rows = {}
    for label, r in rm:
        for row in r["rows"]:
            ok = row["status_ok"] and row["source_hit"] and row.get("current_ok") is not False
            q_rows.setdefault((row["q"], row["item"], row["status"]), {})[label] = ok
    grid = table(["Question", "Checklist item", "Expected"] + [label for label, _ in rm],
                 [[esc(q), esc(item.replace("_", " ")), esc(st.replace("_", " "))]
                  + [('<span class="ok">✓ pass</span>' if v.get(label) else '<span class="bad">✗ fail</span>')
                     for label, _ in rm]
                  for (q, item, st), v in sorted(q_rows.items())], cls="grid")

    # --- Part C: speed ---
    llm_ms = (llm_split("blind3") or {}).get("llm_ms_p50") or 1600
    full = dict(rm).get("Everything", {}).get("summary", {})
    chart_d = hbars("Time per step, typical query (milliseconds, same scale)", [
        ("Understand the prompt (keywords)", max(1, (split(kw, "blind3") or {}).get("latency_ms_p50", 1)), "always runs"),
        ("Remark the documents", full.get("remark_ms_p50", 9), "always runs, no API call"),
        ("Load everything at startup", 162, "once per server start"),
        ("Custom question (embedding call)", 880, "only when the prompt asks something no item covers; cached afterwards"),
        ("Gemini check of the prompt", llm_ms, "only when words were not understood"),
    ])
    rows_d = [
        ["Typical prompt, everything understood", "≈ 10 ms", "0"],
        ["Prompt with unknown words (Gemini check)", f"≈ {llm_ms / 1000:.1f} s", "1 (Gemini)"],
        ["… plus a custom question", f"≈ {(llm_ms + 880) / 1000:.1f} s", "2 (Gemini + 1 embedding)"],
        ["Offline index build, first time ever", "≈ 4 min (free-tier pacing)", "5 embedding + 44 rerank calls"],
        ["Offline index build, later", "≈ 0.3 s", "0 (everything cached)"],
    ]
    table_d = table(["Situation", "Time", "API calls"], rows_d)

    glossary = [
        ("Right role", "Did it understand who is asking (anaesthetist, GP, …)? 100% = every prompt got the right role."),
        ("Required items found", "Of the facts a doctor must see for this request (we listed them per prompt), how many are on the checklist? Higher is better; a miss means the screen could leave out something important."),
        ("Key items ranked high", "Are the most important ones (for example blood thinners before surgery) marked critical or high, so they show at the top?"),
        ("Prompts with everything", "Share of prompts where not a single required item was missing. Stricter than the item average."),
        ("Irrelevant items shown", "Items we listed as useless for that request (for example tumour receptors for an anaesthetist) that still appeared. Lower is better; 0% everywhere."),
        ("Checklist length", "How many items the screen asks about. Longer lists find more but are noisier for the doctor."),
        ("Checks passed (remarker)", "For the 15 challenge questions: did the remarker mark a passage from a document that really contains the answer, with the right status? 18 checks, because some questions need two items."),
        ("Right status", "Found / not documented decided correctly. The two \"not documented\" answers (kidney function, the follow-up ultrasound) are the hard part."),
        ("Source documents found", "Of the documents that hold an answer, how many does the remarker point to?"),
        ("Flags from the right documents", "Of the passages it marks, how many come from a document that holds the answer. The rest are related but not the answer; lower means more noise."),
        ("Current value right", "For drugs: is the dose from the newest letter (April 2016) marked as current, and the older one as history?"),
        ("Highlights exact", "Every marked passage is checked character by character against the document, so the click-through highlight is exact."),
        ("API calls per query", "Calls to paid or rate-limited cloud services for one question. 0 means it runs entirely from the cached index."),
    ]
    gloss = "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in glossary)

    return TEMPLATE.format(chart_a=chart_a, table_a=table_a, chart_b=chart_b, table_b=table_b,
                           chart_c=chart_c, table_c=table_c, grid=grid, chart_d=chart_d,
                           table_d=table_d, glossary=gloss)


TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Metrics</title>
<style>
:root {{ color-scheme: light; --surface:#fcfcfb; --panel:#ffffff; --text:#0b0b0b; --text2:#52514e; --muted:#8a8984;
  --grid:#e6e5e0; --axis:#b9b8b2; --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --ok:#0a7a3c; --bad:#b3261e; }}
@media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) {{ color-scheme: dark; --surface:#1a1a19; --panel:#222220;
  --text:#f0efec; --text2:#c3c2b7; --muted:#8f8e86; --grid:#33332f; --axis:#55544f; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --ok:#5fd08f; --bad:#f28b82; }} }}
:root[data-theme="dark"] {{ color-scheme: dark; --surface:#1a1a19; --panel:#222220; --text:#f0efec; --text2:#c3c2b7; --muted:#8f8e86;
  --grid:#33332f; --axis:#55544f; --s1:#3987e5; --s2:#d95926; --s3:#199e70; --ok:#5fd08f; --bad:#f28b82; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--surface); color:var(--text); font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
main {{ max-width: 980px; margin: 0 auto; padding: 28px 16px 60px; }}
h1 {{ font-size: 24px; margin: 0 0 4px; }} h2 {{ font-size: 19px; margin: 36px 0 6px; }}
p.lead, .note {{ color: var(--text2); }} .note {{ font-size: 14px; }}
figure {{ margin: 18px 0 8px; background: var(--panel); border: 1px solid var(--grid); border-radius: 10px; padding: 12px 14px; }}
figcaption {{ font-weight: 600; margin-bottom: 4px; }}
.chart {{ width: 100%; height: auto; display: block; }}
.grid {{ stroke: var(--grid); stroke-width: 1; }} .axis {{ stroke: var(--axis); stroke-width: 1; }}
.tick, .na {{ fill: var(--muted); font-size: 11px; }} .cat {{ fill: var(--text2); font-size: 12px; }}
.val {{ fill: var(--text); font-size: 11.5px; font-weight: 600; }}
.bar {{ stroke: var(--panel); stroke-width: 2; }} .bar:hover {{ opacity: .85; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 13px; color: var(--text2); margin-bottom: 4px; }}
.key i {{ display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 6px; vertical-align: -1px; }}
.tablewrap {{ overflow-x: auto; margin: 8px 0 4px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
th, td {{ text-align: left; padding: 6px 10px; border-bottom: 1px solid var(--grid); white-space: nowrap; }}
th {{ color: var(--text2); font-weight: 600; }}
.ok {{ color: var(--ok); font-weight: 600; }} .bad {{ color: var(--bad); font-weight: 600; }}
dl {{ display: grid; grid-template-columns: minmax(150px, 220px) 1fr; gap: 6px 18px; }}
dt {{ font-weight: 600; }} dd {{ margin: 0; color: var(--text2); }}
@media (max-width: 640px) {{ dl {{ grid-template-columns: 1fr; }} dd {{ margin-bottom: 8px; }} }}
.box {{ background: var(--panel); border: 1px solid var(--grid); border-radius: 10px; padding: 12px 16px; }}
</style></head><body><main>
<h1>Pipeline metrics</h1>
<p class="lead">How well the two blocks we built work: the decision tree (understands the request) and the remarker
(marks the passages in the documents). All numbers come from our own evaluation runs. The labels were written by the team,
not by doctors, and the data is one synthetic patient, so treat them as a guide, not proof.</p>

<h2>What the metrics mean</h2>
<div class="box"><dl>{glossary}</dl></div>

<h2>1. Decision tree: understanding the request</h2>
<p class="note">Three versions: the <b>old tree</b> (first version, simple rules), the <b>graph</b> (current version, keywords only,
about 1 ms), and the <b>graph + Gemini</b> (Gemini checks prompts with unknown words). The fair test is <b>Blind 3</b>:
12 prompts written after the current graph was frozen and never used to tune it.</p>
{chart_a}
{table_a}
<p class="note">Across all test sets the graph looks perfect on the older sets, because those sets were used to improve it.
Only the last column of the chart below is an honest test of the current version.</p>
{chart_b}
{table_b}

<h2>2. Remarker: marking the right passages</h2>
<p class="note">Checked on the 15 challenge questions (cases/expected.json). Four configurations of the same code:
keywords only, plus the Jina reranker, plus Gemini embeddings, or everything.</p>
{chart_c}
{table_c}
<p class="note">Per question. The only failure without embeddings is kidney function: without semantic search the remarker
cannot be sure a fact is absent, so it says "processing incomplete" instead of "not documented". That is deliberate.</p>
{grid}

<h2>3. Speed</h2>
<p class="note">Everything heavy happens once, offline, and is cached. A typical query needs no API call.</p>
{chart_d}
{table_d}

<h2>Conclusions</h2>
<div class="box"><ul>
<li><b>Use the graph.</b> On unseen prompts it beats the old tree on every metric and shows no irrelevant items.</li>
<li><b>Gemini helps on unusual wording</b> (more required items found on unseen prompts) but costs about 1.5–2 s, so it only runs when words are not understood.</li>
<li><b>Use embeddings in the remarker.</b> They are what lets it say "not documented" with confidence, and they cost no API call at query time.</li>
<li><b>The reranker adds almost nothing here</b> and costs 44 extra calls per patient build; it can stay off.</li>
<li><b>Remarking takes about 10 ms per query</b>, far under the 2-second target. The slowest step is the optional Gemini prompt check.</li>
<li><b>Limits:</b> one synthetic patient, small test sets, labels written by us. A doctor should review the labels and write a blind set.</li>
</ul></div>
</main></body></html>
"""


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
