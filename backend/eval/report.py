"""Build an HTML comparison report from eval/results/*.json.

Usage (from backend/):
  python -m eval.report --out ../docs/prompt-analysis-report.html \
      --run "Old tree=v1-cmp" --run "Graph=keywords-nogen" ...

Each --run is "Label=result-file-stem". The first run is the baseline.
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"

SPLITS = {
    "blind3": ("New prompts (blind 3)", "12 prompts written after every change; no setup has seen them. The fairest test."),
    "blind2": ("New prompts (blind 2)", "15 prompts written before the last two rounds of improvements."),
    "blind": ("Blind 1", "15 prompts; the graph was later improved using its mistakes."),
    "fresh": ("Fresh", "15 prompts; the graph was later improved using its mistakes."),
    "heldout": ("Held-out", "20 prompts written early; their vocabulary was added later."),
    "dev": ("Development", "20 prompts used to build the graph, including the 5 challenge situations."),
}

# key, short name, plain explanation, higher is better, format
METRICS = [
    ("must_recall", "Required items found",
     "Of all the things a clinician must see for these requests, how many ended up on the checklist. "
     "100% means nothing important was left out.", True, "pct"),
    ("cases_all_must_found", "Requests with nothing missing",
     "In how many requests the checklist contained every required item. One missing item is enough "
     "to count a request as imperfect.", True, "pct"),
    ("top_recall", "Most important items ranked high",
     "The must-not-miss items should be marked critical or high, so they appear at the top of the screen.",
     True, "pct"),
    ("role_accuracy", "Who is asking: understood",
     "Whether the system recognised the right profession or specialty (e.g. anaesthetist, GP, nurse).",
     True, "pct"),
    ("context_recall", "Situation details caught",
     "Whether it noticed the situation: planned surgery, contrast, a symptom, a body region, a drug.",
     True, "pct"),
    ("forbidden_rate", "Irrelevant items shown",
     "How often an item we marked as irrelevant for that request appeared anyway (e.g. tumour receptors "
     "for an anaesthetist). Lower is better.", False, "pct"),
    ("avg_checklist_size", "Checklist length",
     "Average number of items on the checklist. Shorter is easier to read, but too short misses things.",
     None, "num"),
    ("llm_share", "Requests that called an LLM",
     "Share of requests where the slow language model had to be asked. Lower means faster.", False, "pct"),
    ("latency_ms_p50", "Typical time",
     "Median time to analyse one request (half of the requests are faster).", False, "ms"),
    ("latency_ms_max", "Slowest time",
     "The slowest request in the set.", False, "ms"),
]

CSS = """
:root{--bg:#f7f7f5;--panel:#fff;--text:#1d2329;--muted:#5d6670;--line:#d9dcdf;--bar:#8a98a8;
--best:#2f9e57;--worst:#d2453f;--base:#b9c1ca;--chip:#eef1f4}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#15181b;--panel:#1d2125;--text:#e7eaed;
--muted:#9aa4ad;--line:#343a40;--bar:#6c7a89;--best:#4cc27a;--worst:#ef6b65;--base:#4a535c;--chip:#2a3036}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:24px 16px 56px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:34px 0 8px}h3{font-size:15px;margin:22px 0 6px}
.sub{color:var(--muted);margin:0 0 16px}.panel{background:var(--panel);border:1px solid var(--line);
border-radius:12px;padding:16px;margin:12px 0}
table{border-collapse:collapse;width:100%;font-size:14px}th,td{padding:7px 8px;border-bottom:1px solid var(--line);
text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left;white-space:normal}
th{color:var(--muted);font-weight:600}.scroll{overflow-x:auto}
.best{color:var(--best);font-weight:700}.worst{color:var(--worst)}
.metric{display:grid;grid-template-columns:minmax(0,1fr);gap:4px;margin:16px 0}
.metric .expl{color:var(--muted);font-size:13.5px;margin:0 0 6px}
.row{display:grid;grid-template-columns:200px minmax(0,1fr) 70px;gap:10px;align-items:center;font-size:13.5px}
@media (max-width:640px){.row{grid-template-columns:120px minmax(0,1fr) 60px}}
.track{background:var(--chip);border-radius:6px;height:16px;overflow:hidden}
.fill{height:100%;background:var(--bar);border-radius:6px}.fill.best{background:var(--best)}
.fill.base{background:var(--base)}.val{text-align:right;font-variant-numeric:tabular-nums}
.legend{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:13px;color:var(--muted)}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 8px;margin:1px 2px;font-size:12.5px}
.k{font-weight:600}ul{margin:6px 0 0 18px;padding:0}li{margin:3px 0}
"""


def load(stem: str) -> dict:
    return json.loads((RESULTS / f"{stem}.json").read_text(encoding="utf-8"))


def split_stats(report: dict, split: str) -> dict | None:
    s = report.get("summary", {}).get(split)
    if not s:
        return None
    s = dict(s)
    s["llm_share"] = (s.get("llm_calls") or 0) / s["cases"] if s.get("cases") else 0
    return s


def overall(report: dict) -> dict:
    s = dict(report["overall"])
    s["llm_share"] = (s.get("llm_calls") or 0) / s["cases"]
    return s


def fmt(v, kind):
    if v is None or v != v:
        return "–"
    if kind == "pct":
        return f"{v * 100:.0f}%"
    if kind == "ms":
        return f"{v:,.0f} ms" if v >= 10 else f"{v:.1f} ms"
    return f"{v:.1f}"


def bars(runs, stats_by_run, key, kind, higher):
    vals = [stats_by_run[label].get(key) if stats_by_run[label] else None for label, _ in runs]
    real = [v for v in vals if v is not None and v == v]
    if not real:
        return ""
    top = max(real) or 1
    best = (max(real) if higher else min(real)) if higher is not None else None
    out = []
    for i, ((label, _), v) in enumerate(zip(runs, vals)):
        if v is None or v != v:
            width, cls = 0, ""
        else:
            width = (v / top) * 100 if kind != "ms" else max(2, (v / top) * 100)
            cls = "best" if best is not None and abs(v - best) < 1e-9 else ("base" if i == 0 else "")
        out.append(f'<div class="row"><div>{html.escape(label)}</div><div class="track">'
                   f'<div class="fill {cls}" style="width:{width:.1f}%"></div></div>'
                   f'<div class="val">{fmt(v, kind)}</div></div>')
    return "".join(out)


def table(runs, stats_by_run):
    head = "".join(f"<th>{html.escape(l)}</th>" for l, _ in runs)
    rows = []
    for key, name, _, higher, kind in METRICS:
        vals = [stats_by_run[l].get(key) if stats_by_run[l] else None for l, _ in runs]
        real = [v for v in vals if v is not None and v == v]
        best = (max(real) if higher else min(real)) if real and higher is not None else None
        worst = (min(real) if higher else max(real)) if real and higher is not None else None
        cells = []
        for v in vals:
            cls = ""
            if v is not None and best is not None and len(set(real)) > 1:
                cls = "best" if abs(v - best) < 1e-9 else ("worst" if abs(v - worst) < 1e-9 else "")
            cells.append(f'<td class="{cls}">{fmt(v, kind)}</td>')
        rows.append(f"<tr><td>{name}</td>{''.join(cells)}</tr>")
    return f'<div class="scroll"><table><tr><th>Measure</th>{head}</tr>{"".join(rows)}</table></div>'


def misses(runs, reports, split):
    rows = []
    for label, stem in runs:
        cases = [c for c in reports[stem]["cases"] if c["split"] == split]
        if not cases:
            continue
        bad = [c for c in cases if c["missed_must"] or c["missed_top"] or c["forbidden_shown"] or not c["role_ok"]]
        items = "".join(
            f'<li><span class="k">{c["id"]}</span> '
            + (f'missed: {"".join(f"<span class=chip>{m}</span>" for m in c["missed_must"])} ' if c["missed_must"] else "")
            + (f'not ranked high: {"".join(f"<span class=chip>{m}</span>" for m in c["missed_top"] if m not in c["missed_must"])} '
               if [m for m in c["missed_top"] if m not in c["missed_must"]] else "")
            + (f'irrelevant shown: {"".join(f"<span class=chip>{m}</span>" for m in c["forbidden_shown"])} ' if c["forbidden_shown"] else "")
            + ("" if c["role_ok"] else f'wrong role: {", ".join(c["roles"])}')
            + "</li>" for c in bad)
        rows.append(f"<h3>{html.escape(label)}: {len(cases) - len(bad)} of {len(cases)} requests perfect</h3>"
                    + (f"<ul>{items}</ul>" if items else "<p class=sub>No misses.</p>"))
    return "".join(rows)


def build(runs, out: Path, prompts_file: Path | None):
    reports = {stem: load(stem) for _, stem in runs}
    prompts = {}
    if prompts_file and prompts_file.exists():
        import yaml
        prompts = {c["id"]: c["prompt"] for c in yaml.safe_load(prompts_file.read_text(encoding="utf-8"))["cases"]}

    parts = [f"<h1>Prompt analysis: which setup works best</h1>"
             f"<p class=sub>How well each setup turns a clinician's request into the checklist of facts to look for. "
             f"Generated {datetime.now():%d %b %Y %H:%M}. Labels were written by the team, not by clinicians.</p>"]

    parts.append("<div class=panel><h2 style='margin-top:0'>The setups compared</h2><ul>"
                 + "".join(f"<li><span class=k>{html.escape(l)}</span>: {html.escape(DESCRIPTIONS.get(l, ''))}</li>" for l, _ in runs)
                 + "</ul></div>")

    headline = "blind3"
    stats = {l: split_stats(reports[s], headline) for l, s in runs}
    parts.append(f"<h2>{SPLITS[headline][0]}</h2><p class=sub>{SPLITS[headline][1]}</p>")
    parts.append("<div class=panel>" + table(runs, stats) + "</div>")
    parts.append("<div class=panel><div class=legend><span><span class=chip style='background:var(--best);color:#fff'>green</span> best value</span>"
                 "<span><span class=chip style='background:var(--base)'>grey</span> old tree (baseline)</span></div>")
    for key, name, expl, higher, kind in METRICS:
        b = bars(runs, stats, key, kind, higher)
        if b:
            parts.append(f'<div class=metric><div class=k>{name}</div><p class=expl>{expl}</p>{b}</div>')
    parts.append("</div>")

    parts.append("<h2>What each setup still gets wrong on the new prompts</h2><div class=panel>"
                 + misses(runs, reports, headline) + "</div>")
    if prompts:
        ids = sorted({c["id"] for c in reports[runs[0][1]]["cases"] if c["split"] == headline})
        parts.append("<details class=panel><summary>The new prompts</summary><ul>"
                     + "".join(f"<li><span class=k>{i}</span> {html.escape(prompts.get(i, ''))}</li>" for i in ids)
                     + "</ul></details>")

    parts.append("<h2>All test sets</h2><p class=sub>Earlier sets were partly used to improve the graph, so they "
                 "flatter it. The table shows required items found and requests with nothing missing.</p><div class=panel><div class=scroll><table>"
                 "<tr><th>Test set</th>" + "".join(f"<th>{html.escape(l)}</th>" for l, _ in runs) + "</tr>")
    for split, (name, expl) in SPLITS.items():
        cells = []
        for l, s in runs:
            st = split_stats(reports[s], split)
            cells.append("<td>–</td>" if not st else
                         f"<td>{fmt(st['must_recall'], 'pct')} / {fmt(st['cases_all_must_found'], 'pct')}</td>")
        parts.append(f"<tr><td>{name}<br><span class=sub style='font-size:12px'>{expl}</span></td>{''.join(cells)}</tr>")
    parts.append("</table></div></div>")

    doc = (f"<!doctype html><html lang=en><head><meta charset=utf-8>"
           f"<meta name=viewport content='width=device-width, initial-scale=1'>"
           f"<title>Prompt Analysis Report</title><style>{CSS}</style></head>"
           f"<body><div class=wrap>{''.join(parts)}</div></body></html>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out}")


DESCRIPTIONS: dict[str, str] = {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True, help="Label=result-stem[=description]")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cases", type=Path, default=Path(__file__).resolve().parent / "cases.yaml")
    args = ap.parse_args(argv)
    runs = []
    for r in args.run:
        parts = r.split("=", 2)
        runs.append((parts[0], parts[1]))
        if len(parts) == 3:
            DESCRIPTIONS[parts[0]] = parts[2]
    build(runs, args.out, args.cases)


if __name__ == "__main__":
    main()
