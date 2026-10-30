"""Keywords: the few words of a passage that answer its checklist item.

The screen shows "Aspirin 100 mg oral 1-0-0-0 (Arztbrief 04/2016)" instead of the whole
sentence and a document number, so the value can be read without opening the source. Every
keyword points at exact character offsets of the document (`Flag.highlights`), which the
source view marks in the original passage.

Where a keyword comes from, in this order (no LLM: the same passage always gets the same
keyword, also without network, and the 3 s budget is untouched):
  1. verified facts of blocks 1-4 on the passage that fit the item: a drug or allergy that fits
     by kind, or a fact whose label, value or quote contains one of the item's terms;
  2. otherwise the clause of the passage with the most item terms, at most 10 words;
  3. otherwise the passage itself when short, or its first 10 words.

Usage: annotate(rem, evidence_layer, tree, docs) after the remarker, before block 8.
"""
from __future__ import annotations

import re
from datetime import date

from .contracts import Flag, RemarkerResult
from .tree import normalize

MAX_GROUPS = 3          # facts (or fact groups sharing a quote) per keyword
QUOTE_CHARS = 80        # a fact's exact quote is shown when at most this long
CLAUSE_WORDS = 10
SHORT_PASSAGE = 70
KIND_FITS = {"medication", "allergy"}   # these fit their item by kind alone (drug lists, allergies)
SUMMARY_KINDS = {"medication", "allergy"}  # rendered from the structured value ("100 mg oral 1-0-0-0")
SKIP_CATEGORIES = {"demographics"}      # never a keyword: birth dates are identifiers

# not ":" (it joins a field to its value) and not a decimal comma ("6,4")
_CLAUSE = re.compile(r",(?!\d)|(?<!\d),|[;()]|\s(?:und|sowie)\s")
_WORD = re.compile(r"\S+")


# ---------------------------------------------------------------------------
# term matching on normalised text
# ---------------------------------------------------------------------------
def _patterns(terms) -> list[tuple[str, bool]]:
    out = []
    for raw in terms:
        prefix = raw.endswith("*")
        pat = normalize(raw.rstrip("*"))
        if len(pat) >= 2:
            out.append((pat, prefix))
    return list(dict.fromkeys(out))


def _hits(text: str, patterns) -> int:
    norm = normalize(text)
    squashed = norm.replace(" ", "")
    n = 0
    for pat, prefix in patterns:
        if len(pat) >= 4 and pat.replace(" ", "") in squashed:   # "ki67" matches "Ki-67"
            n += 1
        elif re.search(r"(?<![a-z0-9])" + re.escape(pat) + ("" if prefix else r"(?![a-z0-9])"), norm):
            n += 1
    return n


def item_patterns(tree, item_id: str, matched: list[str]) -> list[tuple[str, bool]]:
    i = tree.item_index.get(item_id) if tree is not None else None
    terms = list(matched)
    if i is not None:
        for group in tree.items[i].get("terms", {}).values():
            terms += group
    return _patterns(terms)


# ---------------------------------------------------------------------------
# 1. from verified facts
# ---------------------------------------------------------------------------
def _locate(flag: Flag, needle: str) -> tuple[int, int] | None:
    needle = needle.strip()
    if not needle:
        return None
    k = flag.text.find(needle)
    if k < 0:
        k = flag.text.lower().find(needle.lower())
    return (flag.start + k, flag.start + k + len(needle)) if k >= 0 else None


def _quote_in(flag: Flag, q) -> tuple[tuple[int, int], str] | None:
    """The part of a fact's quote that lies in this passage: (document span, its exact words).
    A quote may run past the passage when the segmenter cut the sentence; the overlap counts only
    when its characters are the same in quote and passage."""
    doc, a, b, quote = q
    if doc != flag.doc_id:
        return None
    loc = _locate(flag, quote)
    if loc:
        return loc, quote.strip()
    lo, hi = max(a, flag.start), min(b, flag.end)
    part = flag.text[lo - flag.start:hi - flag.start] if lo < hi else ""
    if not part.strip() or quote[lo - a:hi - a] != part:
        return None
    lead = len(part) - len(part.lstrip())
    part = part.strip()
    return (lo + lead, lo + lead + len(part)), part


def _distinct(texts) -> list[str]:
    """Drop a piece another piece already contains ("T2 N0" inside the sentence that states it)."""
    texts = list(dict.fromkeys(texts))
    norm = [normalize(t) for t in texts]
    return [t for i, t in enumerate(texts)
            if not any(j != i and norm[i] in norm[j] and (norm[i] != norm[j] or j < i) for j in range(len(texts)))]


def _render(fact, quote: str) -> str:
    q = quote.strip().rstrip(".")
    # "admission", "herzecho": a bare concept name says less than the document's own words
    generic = normalize(fact.summary) == normalize(fact.concept.split(":")[-1].replace("_", " "))
    if fact.kind in SUMMARY_KINDS and not generic:
        return fact.summary
    if len(q) <= QUOTE_CHARS or generic or len(fact.summary) >= len(q):
        return q
    if fact.kind == "measurement":
        return f"{fact.label} {fact.summary}"   # "Ki-67 20 %", not a bare "20 %"
    return fact.summary


def _from_facts(flag: Flag, facts, patterns, any_fact: bool = False) -> tuple[str, list[tuple[int, int]]] | None:
    """Facts whose own label or value names the item (or a drug / allergy fitting by kind).
    any_fact: no item term anywhere in the passage, so every verified fact of it may speak."""
    fitting = set(flag.fact_ids)
    picked = []
    for fa in facts:
        if fa.category in SKIP_CATEGORIES:
            continue
        quotes = [x for x in (_quote_in(flag, q) for q in fa.quotes) if x]
        if not quotes:
            continue
        span, quote = quotes[0]
        about = f"{fa.label} {fa.summary} {fa.concept.replace('_', ' ').replace(':', ' ')}"
        named = _hits(about, patterns)
        kind_fit = fa.id in fitting and fa.kind in KIND_FITS
        if named or kind_fit or any_fact:
            # a long quote that merely mentions a term (a CT report naming the allergy) does not count
            score = 2 * named + min(_hits(quote, patterns), 1) + 4 * kind_fit
            picked.append((score, fa, quote, span))
    if not picked:
        return None
    # one group per quote span: facts that share or overlap a quote are said together
    groups: list[dict] = []
    for score, fa, quote, span in sorted(picked, key=lambda p: p[3][0]):
        for g in groups:
            if span[0] < g["span"][1] and g["span"][0] < span[1]:
                g["facts"].append(fa)
                g["span"] = (min(g["span"][0], span[0]), max(g["span"][1], span[1]))
                g["score"] = max(g["score"], score)
                break
        else:
            groups.append({"span": span, "facts": [fa], "quote": quote, "score": score})
    groups = sorted(sorted(groups, key=lambda g: -g["score"])[:MAX_GROUPS], key=lambda g: g["span"][0])
    texts, spans = [], []
    for g in groups:
        if len(g["facts"]) == 1:
            fa = g["facts"][0]
            text = _render(fa, g["quote"])
        else:
            whole = flag.text[g["span"][0] - flag.start:g["span"][1] - flag.start].strip().rstrip(".")
            text = whole if len(whole) <= QUOTE_CHARS else ", ".join(
                _distinct(_render(fa, g["quote"]) for fa in g["facts"]))
        texts.append(text)
        # highlight the shown words when they stand in the passage, else the fact's quote
        spans.append(_locate(flag, text) or g["span"])
    return "; ".join(_distinct(texts)), spans


# ---------------------------------------------------------------------------
# 2. / 3. from the passage itself
# ---------------------------------------------------------------------------
def _trim(flag: Flag, a: int, b: int, patterns=()) -> tuple[str, tuple[int, int]]:
    """At most CLAUSE_WORDS words, starting one word before the first item term (the words that
    lead into a long clause are rarely the answer)."""
    chunk = flag.text[a:b]
    words = list(_WORD.finditer(chunk))
    first = 0
    if len(words) > CLAUSE_WORDS and patterns:
        first = next((max(0, k - 1) for k, w in enumerate(words) if _hits(w.group(), patterns)), 0)
        first = min(first, len(words) - CLAUSE_WORDS)
    last = min(len(words), first + CLAUSE_WORDS)
    lo = words[first].start() if words else 0
    hi = words[last - 1].end() if words else len(chunk)
    text = chunk[lo:hi].rstrip(" .:;,")
    shown = ("… " if first else "") + " ".join(text.split()) + (" …" if last < len(words) else "")
    return shown, (flag.start + a + lo, flag.start + a + lo + len(text))


def _from_text(flag: Flag, patterns) -> tuple[str, list[tuple[int, int]]]:
    bounds, last = [], 0
    for m in _CLAUSE.finditer(flag.text):
        bounds.append((last, m.start()))
        last = m.end()
    bounds.append((last, len(flag.text)))
    scored = [(_hits(flag.text[a:b], patterns), a, b) for a, b in bounds if flag.text[a:b].strip()]
    # tie: a clause with a value (185/110 mmHg) first, then the longer clause, which says more
    best = max(scored, key=lambda s: (s[0], bool(re.search(r"\d", flag.text[s[1]:s[2]])), s[2] - s[1]), default=None)
    if best and best[0] > 0 and len(scored) > 1:
        text, span = _trim(flag, best[1], best[2], patterns)
        return text, [span]
    whole = flag.text.strip()
    if len(whole) <= SHORT_PASSAGE:
        text = whole.rstrip(" .:")
        return text, [s for s in [_locate(flag, text)] if s]
    text, span = _trim(flag, 0, len(flag.text))
    return text, [span]


def _with_sentence_facts(flag: Flag, facts, text: str, spans) -> tuple[str, list[tuple[int, int]]]:
    """A clause chosen for its item term ("im Tumorboard besprochen") plus what a verified fact
    of the same sentence says ("Knie-TEP rechts nach kardiologischer Freigabe")."""
    a, b = spans[0]
    extra, extra_spans = [], []
    for fa in facts:
        if fa.category in SKIP_CATEGORIES or len(extra) >= 2:
            continue
        for span, quote in (x for x in (_quote_in(flag, q) for q in fa.quotes) if x):
            if span[0] <= a and b <= span[1]:
                shown = _render(fa, quote)
                if normalize(shown) not in normalize(text) and normalize(shown) not in map(normalize, extra):
                    extra.append(shown)
                    extra_spans.append(_locate(flag, shown) or span)
                break
    return "; ".join([text] + extra), list(spans) + extra_spans


_VALUE = re.compile(r"\d+(?:[.,/]\d+)*")


def _value_clause(flag: Flag, patterns, shown: str) -> tuple[str, list[tuple[int, int]]] | None:
    """The clause naming the item, when it holds a value the facts do not show (a blood pressure
    of 185/110 mmHg next to a fact that only says "hypertensive Krise")."""
    text, spans = _from_text(flag, patterns)
    values = set(_VALUE.findall(text))
    if not spans or not values or not _hits(text, patterns) or values <= set(_VALUE.findall(shown)):
        return None
    return text, spans


def keyword_for(flag: Flag, facts, patterns) -> tuple[str, list[tuple[int, int]]]:
    found = _from_facts(flag, facts, patterns)
    if found:
        extra = _value_clause(flag, patterns, found[0])
        return (f"{extra[0]}; {found[0]}", extra[1] + found[1]) if extra else found
    if not _hits(flag.text, patterns):
        found = _from_facts(flag, facts, patterns, any_fact=True)
        if found:
            return found
    text, spans = _from_text(flag, patterns)
    if spans and _hits(text, patterns):
        text, spans = _with_sentence_facts(flag, facts, text, spans)
    return _masked(flag, facts, text), spans


def _masked(flag: Flag, facts, text: str) -> str:
    """Words of identifier facts (a birth date) never stand in a keyword taken from the text."""
    for fa in facts:
        if fa.category in SKIP_CATEGORIES:
            for _, quote in (x for x in (_quote_in(flag, q) for q in fa.quotes) if x):
                text = text.replace(quote, "…")
    return text


def annotate(rem: RemarkerResult, evidence, tree, docs: dict[str, dict] | None = None) -> RemarkerResult:
    """Set keyword and highlights on every flag; add short document names for source links."""
    for item in rem.items + rem.custom:
        for f in item.flags:
            facts = evidence.facts_for_segment(f.segment_id) if evidence is not None else []
            key, f.highlights = keyword_for(f, facts, item_patterns(tree, item.item_id, f.matched_terms))
            f.keyword = " ".join(key.split())
    if docs:
        rem.doc_labels = doc_labels(docs)
    return rem


# ---------------------------------------------------------------------------
# short document names, e.g. "Arztbrief 04/2016"
# ---------------------------------------------------------------------------
DOC_NAMES = [  # (pattern on type + title, en, de); first match wins
    (r"histo", "Histology", "Histologie"),
    (r"augen", "Eye consult", "Augenkonsil"),
    (r"ambulan", "Outpatient letter", "Ambulanzbrief"),
    (r"arztbrief|patientenbrief|entlassung", "Discharge letter", "Arztbrief"),
    (r"langzeit-?ekg", "Long-term ECG", "Langzeit-EKG"),
    (r"24h-?rr|blutdruckmessung", "24h BP", "24h-RR"),
    (r"radiolog|röntgen|ct\b|mrt", "Radiology", "Radiologie"),
    (r"labor", "Lab report", "Laborbefund"),
]


def doc_labels(docs: dict[str, dict]) -> dict[str, dict[str, str]]:
    base = {}
    for doc_id, d in docs.items():
        hay = f"{d.get('type', '')} {d.get('title', '')}".lower()
        en = de = (d.get("title") or d.get("type") or doc_id).strip()
        for pat, e, g in DOC_NAMES:
            if re.search(pat, hay):
                en, de = e, g
                break
        when = d.get("date")
        try:
            day = date.fromisoformat(when) if isinstance(when, str) else when
        except ValueError:
            day = None
        base[doc_id] = (en, de, day)
    labels = {}
    for doc_id, (en, de, day) in base.items():
        month = day.strftime("%m/%Y") if day else ""
        clash = any(o != doc_id and b[0] == en and b[2] and day and b[2].strftime("%m/%Y") == month
                    for o, b in base.items())
        when = day.strftime("%d.%m.%Y") if clash else month
        labels[doc_id] = {"en": f"{en} {when}".strip(), "de": f"{de} {when}".strip()}
    return labels
