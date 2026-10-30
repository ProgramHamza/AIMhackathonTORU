"""Build eval/results/report4.html: every block evaluated, the hand-offs between them, and the
whole chain end to end.

Inputs (eval/results): blocks.json (python -m eval.run_blocks), pipeline-v3.json or
pipeline-v2.json (python -m eval.run_pipeline --no-cache --tag v3), and the earlier files
report2/3 used for the before/after comparison.
Usage (from backend/): python -m eval.make_report4
"""
from __future__ import annotations

from .make_report2 import PAGE, RESULTS, esc, grouped_bars, legend, load, pct, table
from .make_report3 import stacked_time_bars

OK = '<span class="ok">✓</span>'
NO = '<span class="no">✗</span>'

GLOSSARY = [
    ("Answers complete", "Of the 15 challenge questions: the answering item has the right status, links to an expected "
     "source document, and is on the screen without clicking (summary panel or ranked list)."),
    ("Needed items found", "Of the checklist items a prompt needs, how many were listed (block 5)."),
    ("Questions fully supported", "Of the 15 questions: the remarker marked a passage from a right document with the right status (blocks 6/7)."),
    ("Flag precision", "Share of marked passages that come from a document the challenge lists as a source."),
    ("Verified fact", "A fact from blocks 1-4 with an exact quote checked against the document offsets."),
    ("Hand-off check", "A property that must hold between two blocks on every prompt, e.g. every citation the final step "
     "makes refers to a passage the remarker produced, and that passage equals the document text."),
    ("Identifiers replaced", "Names, birth dates, IDs, case numbers, addresses, phone numbers, clinicians, facilities and places removed before a cloud call."),
    ("Time, prompt to full screen", "Prompt analysis + marking passages + the final check and summary; live calls, no cache. Challenge limit 10 s."),
]

FIXES = [
    ("Fact signal too broad (found in this evaluation)", "A diagnosis fact in a passage boosted every 'problem' item, so kidney function became 'found' on an unrelated sentence.",
     "A fact only confirms a passage that already matches the item, and only when its kind or label fits the item. Remarker checks back to 18/18."),
    ("Two answers not in the summary panel", "Questions 4.3 and 5.3 were on the ranked list but not among the summary lines; the metric only counted the summary.",
     "The ranked list is on screen too; the metric counts both. Free summary slots fill in ranked order."),
    ("Requests over the 3 s budget (25%)", "Both LLM calls ran on one key; the free tier throttled and retries overran.",
     "The two calls start on different keys; the prompt is ~35% smaller."),
    ("Mammography prompt missed histology", "'mammography' matched only the generic imaging node.",
     "'mammo*' activates the breast region, whose rule lists histology and staging."),
    ("Patient data in cloud calls", "Passages went out as they are, header lines included.",
     "One outbound gate de-identifies every text and refuses to send if an identifier remains."),
    ("Caches readable on disk", "Index, embeddings and summaries were plain JSON with document text.", "AES-256-GCM at rest; tampering detected."),
    ("Blocks 1-4 unused", "Verified facts, derived values and contradictions were not part of the answer.",
     "Merged: facts confirm passages and set polarity/side; derived values and accepted contradictions are shown with their sources."),
    ("Medication table header shown as a passage", "'Applikation mo mi ab na …' scored as a medication row.", "Marked as boilerplate; never evidence."),
    ("Cached timings reported as live", "A rerun was served from the summary cache (45 ms).", "The harness has --no-cache; the report uses a live run."),
    ("Evaluation crashed on quota", "The embedding step's quota error stopped the semantic evaluation.", "It warns and continues."),
]

HANDOFF_LABELS = {
    "5_to_67_items_known": ("5 → 6/7", "Every checklist item the prompt analysis produces is an item the remarker can search for"),
    "5_to_67_items_answered": ("5 → 6/7", "Every planned item comes back with a status (found / absent / not documented)"),
    "14_to_67_flags_backed_by_verified_fact": ("1-4 → 6/7", "Share of marked passages that carry a verified fact (confirmation, not a requirement)"),
    "67_to_8_flag_text_equals_document": ("6/7 → 8", "Every marked passage's text equals the document slice at its offsets (highlighting cannot drift)"),
    "8_claims_cites_resolve": ("8", "Every citation in the summary refers to a passage that exists"),
    "8_claims_cited_or_marked_absent": ("8", "Every summary line cites a passage, or says 'not documented' / 'could not be checked'"),
    "5_to_8_claim_items_on_checklist": ("5 → 8", "Every summary line belongs to an item of this request's checklist"),
    "5_to_8_critical_items_in_summary": ("5 → 8", "Every critical item of the checklist appears in the summary"),
    "14_to_8_derived_values_linked": ("1-4 → 8", "Every derived value (weight change, BMI) links to the passages it was computed from"),
    "conflicts_link_two_passages": ("1-4, 6/7 → 8", "Every conflict links at least two existing passages"),
    "gate_refusals": ("security", "Calls refused by the gate (0 = the scrubber removed everything the leak check looks for)"),
}


def tiles(items):
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><div class="big">{esc(v)}</div><div class="cap">{esc(c)}</div></div>' for v, c in items) + "</div>"


def f1(v):
    return "–" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def build() -> str:
    b = load("blocks") or {}
    run = load("pipeline-v3") or load("pipeline-v2")
    old = load("pipeline-promptcheck") or load("pipeline")
    if not run:
        raise SystemExit("run python -m eval.run_pipeline --no-cache --tag v3 first")
    s = run["summary"]
    sec = b.get("security", {})
    deid = sec.get("deidentification", {})
    inter = b.get("interactions", {})
    hand = inter.get("handoffs", {})
    b14 = b.get("blocks_1_4", {})
    b67 = b.get("blocks_6_7", {})
    b8 = b.get("block_8", {})
    b5 = b.get("block_5", {})
    units = b.get("unit_tests", {})
    unit_total = sum(v["passed"] for v in units.values())
    unit_failed = sum(v["failed"] for v in units.values())
    in_summary = sum(q.get("in_summary", q["visible"]) for q in run["questions"]) / len(run["questions"])
    parts = []

    # ---------------- headline
    parts.append("<section><h2>Headline</h2>" + tiles([
        (f"{round(s['complete'] * 15)}/15", "challenge answers complete"),
        (f"{round(in_summary * 15)}/15", "of them in the summary panel"),
        (f"{s['latency_ms_p50'] / 1000:.1f} s", "median, prompt to full screen (live)"),
        (f"{s['latency_ms_max'] / 1000:.1f} s", "slowest (limit 10 s)"),
        (pct(s["blind_must_recall"]), "needed items found, blind prompts"),
        (f"{sum(1 for v in hand.values() if v in (1.0, 0))}/{len(hand)}", "hand-off checks at 100%"),
        (f"{deid.get('identifiers_after', '–')}", "identifiers left after de-identification"),
        (f"{unit_total + b14.get('own_tests', {}).get('ran', 0)}", f"tests passing ({unit_failed} failing)"),
    ]) + "</section>")

    # ---------------- blocks 1-4
    bundle = b14.get("bundle", {})
    cats = sorted(bundle.get("facts_by_category", {}).items(), key=lambda kv: -kv[1])
    cat_rows = [(k, [v]) for k, v in cats]
    own = b14.get("own_tests", {})
    parts.append(f"""
<section><h2>1. Blocks 1-4: the evidence backend (documents → verified facts)</h2>
<p class="lead">The preparation team's package, loaded with its hashes checked. Its own test suite runs from the merged
location: <b>{own.get('ran', '–')} tests, {own.get('failures', '–')} failures, {own.get('errors', '–')} errors</b>.</p>
{table(["What", "Value"], [
    ["Documents / passages", f"{bundle.get('documents', '–')} / {bundle.get('passages', '–')}"],
    ["Verified facts", f"{bundle.get('facts', '–')} ({bundle.get('facts_by_method', {}).get('rule', 0)} by rules, {bundle.get('facts_by_method', {}).get('llm', 0)} by model, each with an exact quote)"],
    ["Quotes checked against document offsets", f"{bundle.get('quotes_verified', '–')} / {bundle.get('quotes_total', '–')}"],
    ["Facts with a model review of the cited evidence", str(bundle.get("model_checked", "–"))],
    ["Derived values (BMI, weight change)", str(bundle.get("derived_values", "–"))],
    ["Contradictions", esc(", ".join(f"{k}: {v}" for k, v in bundle.get("contradictions", {}).items()))],
    ["Processing gaps recorded", f"{bundle.get('processing_gaps', '–')} (reported, never turned into 'not documented')"],
    ["Mapped onto our sentence segments", f"{inter.get('counts', {}).get('flags_fact_backed', '–')} of {inter.get('counts', {}).get('flags', '–')} marked passages carry a fitting fact; 0 quotes failed to map"],
])}
<h3>Facts by category</h3>
{legend([("Verified facts", 1)])}{grouped_bars(cat_rows, [("Facts", 1)], fmt=lambda v: str(int(v)), maxv=max(v for _, v in cats) if cats else 1, note="Facts per category")}
</section>""")

    # ---------------- block 5
    kw = b5.get("keywords", {})
    oldt = b5.get("old_tree", {})
    llm3 = b5.get("with_llm_check", {}).get("blind3", {})
    llm2 = b5.get("with_llm_check_blind2", {}).get("blind2", {})
    sets = [x for x in ("blind", "blind2", "blind3", "blind4") if x in kw]
    rows5 = [(f"Needed items found, {x}", [oldt.get(x, {}).get("must_recall"), kw[x].get("must_recall"),
                                           (llm2 if x == "blind2" else llm3 if x == "blind3" else {}).get("must_recall")]) for x in sets]
    rows5 += [(f"Role recognised, {x}", [oldt.get(x, {}).get("role_accuracy"), kw[x].get("role_accuracy"),
                                         (llm2 if x == "blind2" else llm3 if x == "blind3" else {}).get("role_accuracy")]) for x in sets[:2]]
    series5 = [("Old tree", 1), ("Graph + vocabulary (default)", 2), ("+ Gemini prompt check", 3)]
    t5 = table(["Set", "Prompts", "Role", "Context", "Needed items", "Key items high", "All needed", "Irrelevant shown", "Checklist length", "ms"],
               [[x, kw[x]["cases"], pct(kw[x]["role_accuracy"]), pct(kw[x]["context_recall"]), pct(kw[x]["must_recall"]),
                 pct(kw[x]["top_recall"]), pct(kw[x]["cases_all_must_found"]), pct(kw[x]["forbidden_rate"]),
                 f"{kw[x]['avg_checklist_size']:.1f}", f"{kw[x]['latency_ms_p50']:.1f}"] for x in kw])
    parts.append(f"""
<section><h2>2. Block 5: understanding the prompt (role, task, context → checklist)</h2>
<p class="lead">Measured on prompts never used for tuning (blind sets). The default is the decision graph with its
generated vocabulary and no model call; the Gemini check is optional and adds 1.6-2.6 s without finding more items.</p>
{legend(series5)}{grouped_bars(rows5, series5, note="Block 5 by version and blind set")}
<h3>Default configuration on every set</h3>{t5}
</section>""")

    # ---------------- blocks 6/7
    abl = b67.get("ablations", {})
    cur = b67.get("current") or {}
    order = [("lexical", "Keywords only"), ("dense", "Keywords + embeddings"), ("rerank", "Keywords + reranker"), ("full", "Embeddings + reranker")]
    rows67 = [("Status correct", [abl.get(k, {}).get("status_accuracy") for k, _ in order]),
              ("Source document correct", [abl.get(k, {}).get("source_hit_rate") for k, _ in order]),
              ("Source recall", [abl.get(k, {}).get("source_recall") for k, _ in order]),
              ("Flag precision", [abl.get(k, {}).get("flag_precision") for k, _ in order]),
              ("Current value correct", [abl.get(k, {}).get("current_value_correct") for k, _ in order])]
    series67 = [(lbl, n + 1) for n, (_, lbl) in enumerate(order)][:3] + [("Embeddings + reranker", 1)]
    t67 = table(["Variant", "Questions fully supported", "Checks", "Flags per item", "Offsets exact", "Time per query"],
                [[lbl, abl.get(k, {}).get("questions_fully_supported", "–"), abl.get(k, {}).get("checks_ok", "–"),
                  abl.get(k, {}).get("avg_flags_per_item", "–"), abl.get(k, {}).get("offsets_exact", "–"),
                  f"{abl.get(k, {}).get('remark_ms_p50', 0):.0f} ms"] for k, lbl in order] +
                [["<b>Default now (embeddings + verified facts)</b>", cur.get("questions_fully_supported", "–"), cur.get("checks_ok", "–"),
                  cur.get("avg_flags_per_item", "–"), cur.get("offsets_exact", "–"), f"{cur.get('remark_ms_p50', 0):.0f} ms"]])
    parts.append(f"""
<section><h2>3. Blocks 6/7: marking the passages (checklist → evidence per item)</h2>
<p class="lead">18 checks derived from the 15 challenge questions: right status, a passage from a right document, the
current value where one is expected. The reranker added nothing measurable, so it stays off.</p>
{legend([(lbl, n + 1) for n, (_, lbl) in enumerate(order[:3])])}{grouped_bars([(l, v[:3]) for l, v in rows67], [(lbl, n + 1) for n, (_, lbl) in enumerate(order[:3])], note="Remarker variants")}
{t67}
</section>""")

    # ---------------- block 8
    tpl, llm = b8.get("templates_only", {}), b8.get("with_llm", {})
    rows8 = [("Right status", [tpl.get("status_ok"), llm.get("status_ok")]), ("Right source", [tpl.get("source_hit"), llm.get("source_hit")]),
             ("Visible in the summary", [tpl.get("visible"), llm.get("visible")]), ("All three", [tpl.get("all_three"), llm.get("all_three")])]
    series8 = [("Templates only", 2), ("Two parallel LLM calls + code checks", 3)]
    adversarial = units.get("test_summary", {})
    parts.append(f"""
<section><h2>4. Block 8: the check and the summary (evidence → screen)</h2>
<p class="lead">Templates alone already give {pct(tpl.get('all_three'))} of answers complete; the LLM only orders, drops
unsupported passages and connects facts. Every sentence it writes is checked in code (numbers, drugs, negation,
side, planned-vs-done) and replaced by its template if it fails.</p>
{legend(series8)}{grouped_bars(rows8, series8, note="Block 8 with and without the LLM")}
{table(["", "Templates only", "With LLM"], [["Median time", f"{tpl.get('latency_ms_p50', 0):.0f} ms", f"{llm.get('latency_ms_p50', 0) / 1000:.2f} s"],
                                            ["Adversarial claim tests (flipped negation, swapped side, planned as done, wrong dose, no citation)",
                                             f"{adversarial.get('passed', '–')} passed, {adversarial.get('failed', '–')} failed", ""]])}
</section>""")

    # ---------------- security
    rep = deid.get("replaced_by_type", {})
    rep_rows = [(k, [v]) for k, v in sorted(rep.items(), key=lambda kv: -kv[1])]
    enc = sec.get("encryption", {})
    parts.append(f"""
<section><h2>5. Security: de-identification, the gate, encryption</h2>
<p class="lead">All 8 documents ({deid.get('characters', '–')} characters): <b>{deid.get('identifiers_before', '–')}</b> direct identifiers found,
<b>{deid.get('replaced_total', '–')}</b> replacements made, <b>{deid.get('identifiers_after', '–')}</b> left, in {deid.get('ms_total', '–')} ms.
Gate refusals over {inter.get('prompts', '–')} prompts: <b>{hand.get('gate_refusals', '–')}</b>.</p>
{legend([("Replacements", 1)])}{grouped_bars(rep_rows, [("Replacements", 1)], fmt=lambda v: str(int(v)), maxv=max(rep.values()) if rep else 1, note="Replacements by type")}
{table(["What", "Result"], [
    ["Encryption at rest", f"AES-256-GCM; 8 MB encrypted in {enc.get('encrypt_ms', '–')} ms, decrypted in {enc.get('decrypt_ms', '–')} ms ({enc.get('mb_per_s', '–')} MB/s)"],
    ["Cache files encrypted", f"{enc.get('cache_files_encrypted', '–')} / {enc.get('cache_files', '–')}"],
    ["Clients behind the gate", esc(", ".join(sec.get("gate", {}).get("clients_gated", [])))],
    ["Tests", f"de-identification {units.get('test_deidentify', {}).get('passed', '–')}, gate {units.get('test_outbound_gate', {}).get('passed', '–')}, "
              f"encryption {units.get('test_vault', {}).get('passed', '–')}, key rotation {units.get('test_keys', {}).get('passed', '–')}"],
    ["Legal frame", "GDPR Art. 4(5), 5, 9, 28, 32, 35, 44-46; GTelG 2012 § 3, § 6, § 8 — <code>docs/data-protection.md</code>"],
])}
<p class="lead">This is pseudonymisation: dates of care and clinical values stay. A hospital deployment still needs a processor contract, an EU endpoint and a DPIA.</p>
</section>""")

    # ---------------- interactions
    hrows = []
    for key, val in hand.items():
        between, text = HANDOFF_LABELS.get(key, (key, key))
        if key == "gate_refusals":
            shown, ok = str(val), val == 0
        elif key == "14_to_67_flags_backed_by_verified_fact":
            shown, ok = pct(val), True
        else:
            shown, ok = pct(val), val == 1.0
        hrows.append([between, esc(text), shown, OK if ok else NO])
    counts = inter.get("counts", {})
    parts.append(f"""
<section><h2>6. Do the blocks work together? The hand-off checks</h2>
<p class="lead">Checked on {inter.get('prompts', '–')} prompts (5 situations + blind sets) along the template path, so every prompt is covered:
{counts.get('plan_items', '–')} planned items, {counts.get('flags', '–')} marked passages, {counts.get('claims', '–')} summary lines,
{counts.get('derived', '–')} derived values, {counts.get('conflicts', '–')} conflicts.</p>
{table(["Between", "Property", "Result", ""], hrows)}
</section>""")

    # ---------------- end to end
    if old:
        o = old["summary"]
        rows_ba = [("Answers complete", [o["complete"], s["complete"]]), ("Needed items found (blind)", [o["blind_must_recall"], s["blind_must_recall"]]),
                   ("Requests under 3 s", [o["latency_under_3s"], s["latency_under_3s"]]), ("Ran with the LLM", [o["llm_mode_share"], s["llm_mode_share"]])]
        series_ba = [("Before (report 3)", 2), ("Now", 3)]
        ba = legend(series_ba) + grouped_bars(rows_ba, series_ba, note="Before and after") + table(
            ["", "Before", "Now"], [["Median time", f"{o['latency_ms_p50'] / 1000:.2f} s", f"{s['latency_ms_p50'] / 1000:.2f} s"],
                                    ["Slowest", f"{o['latency_ms_max'] / 1000:.2f} s", f"{s['latency_ms_max'] / 1000:.2f} s"]])
    else:
        ba = ""
    qrows = [[q["question"], esc(", ".join(q["items"])), OK if q["status_ok"] else NO, OK if q["source_hit"] else NO,
              OK if q.get("in_summary") else "–", OK if q["complete"] else NO] for q in run["questions"]]
    trows = [(f"Situation {x['situation']}", x["timings_ms"]["prompt_analysis"], x["timings_ms"]["remarker"], x["timings_ms"]["final"]) for x in run["situations"]]
    srows = [[f"Situation {x['situation']}", x["mode"], f"{x['timings_ms']['total'] / 1000:.2f} s", str(x["summary_lines"]), str(x.get("derived", "–")),
              str(x["conflicts"]), str(x.get("fact_backed_flags", "–")), str((x.get("coverage") or {}).get("segments_searched", "–"))] for x in run["situations"]]
    blind = run.get("blind", [])
    lat = sorted(((r["id"], [r["timings_ms"]["total"] / 1000]) for r in blind), key=lambda x: -x[1][0])
    prows = [[r["id"], esc(r["prompt"]), r["mode"], f"{r['timings_ms']['total'] / 1000:.2f} s", f"{r['must_found']}/{r['must_total']}",
              str(r["statuses"].get("found", 0)), str(r["statuses"].get("not_documented", 0))] for r in blind]
    parts.append(f"""
<section><h2>7. The whole chain, end to end (live calls)</h2>
{ba}
<h3>The five challenge situations</h3>
{table(["Question", "Items", "Right status", "Right source", "In summary", "Complete"], qrows)}
{legend([("Prompt analysis", 1), ("Marking passages", 2), ("Check and summary (LLM)", 3)])}{stacked_time_bars(trows)}
{table(["", "Mode", "Total", "Summary lines", "Derived values", "Conflicts", "Fact-backed passages", "Segments searched"], srows)}
<h3>{len(blind)} blind prompts</h3>
<p class="lead">Needed items found <b>{pct(s['blind_must_recall'])}</b>, key items ranked high <b>{pct(s['blind_top_recall'])}</b>,
irrelevant items shown <b>{pct(s['blind_forbidden_rate'])}</b>, under 3 s <b>{pct(s['latency_under_3s'])}</b>.</p>
{legend([("Seconds, prompt to full screen", 3)])}{grouped_bars(lat, [("Total", 3)], fmt=lambda v: f"{v:.2f} s", maxv=max(3.0, lat[0][1][0]) if lat else 3.0, note="Seconds per blind prompt") if lat else ""}
{table(["ID", "Prompt", "Mode", "Time", "Needed items", "Found", "Not documented"], prows)}
</section>""")

    # ---------------- unit tests + fixes + limits
    urows = [[f, str(v["passed"]), str(v["failed"])] for f, v in sorted(units.items())]
    urows.append(["<b>blocks14 (evidence backend, its own suite)</b>", str(own.get("ran", "–")), str((own.get("failures", 0) or 0) + (own.get("errors", 0) or 0))])
    parts.append("<section><h2>8. Unit and integration tests</h2>" + table(["Test file", "Passed", "Failed"], urows) + "</section>")
    parts.append("<section><h2>9. Errors found and fixed in this round</h2>" + table(["Problem", "Cause", "Fix"], [[f"<b>{esc(a)}</b>", esc(b), esc(c)] for a, b, c in FIXES]) + "</section>")
    parts.append("""<section><h2>What these numbers do not prove</h2><ul class="caveat">
<li>The team wrote the test prompts, the expected items and the remarker checks; a clinician has not reviewed them.</li>
<li>Blind sets are small (12-15 prompts each), so one prompt moves a score by several points.</li>
<li>"Answers complete" is our proxy; the jury reads the answer text.</li>
<li>The hand-off checks run on the template path (no model); the LLM path is covered by the end-to-end run and the code checks in block 8.</li>
<li>De-identification is pseudonymisation; the legal notes list what a real deployment still needs.</li>
</ul></section>""")

    glossary = "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in GLOSSARY)
    page = PAGE.format(body="".join(parts), glossary=glossary)
    page = page.replace("<title>Pipeline Metrics Comparison</title>", "<title>Full System Evaluation</title>")
    page = page.replace("<h1>Pipeline metrics: what works and what is better</h1>", "<h1>Every block, every hand-off, the whole chain (report 4)</h1>")
    page = page.replace("</style>", ".tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}"
                        ".tile{border:1px solid var(--border);border-radius:10px;padding:12px}"
                        ".big{font-size:26px;font-weight:700}.cap{color:var(--text2);font-size:13px}</style>")
    return page


if __name__ == "__main__":
    out = RESULTS / "report4.html"
    out.write_text(build(), encoding="utf-8")
    print(out)
