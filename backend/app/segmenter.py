"""Block 1 (interim): document cleaning and segmentation.

The other team owns block 1; this version follows the agreed Segment contract so the
remarker can run now. Offsets always refer to the *cleaned* document text, which is the
single coordinate system for highlighting and quote checks.

Steps
  1. clean: <BR> -> newline, HTML entities unescaped, nothing else changed.
  2. lines are classified: header ("Diagnosen:"), field ("Gewicht: 66 kg"), table row
     (inside a medication list), boilerplate (address, salutation, signature), or text.
  3. hard-wrapped text lines are joined back into paragraphs, then split into sentences
     (German abbreviations such as "li.", "Dr.", "St.p." do not end a sentence).
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .contracts import Segment

KNOWN_HEADERS = {
    "befundzusammenfassung", "gesamtbeurteilung", "zusammenfassung", "interpretation",
    "histopathologischer befund", "radiologischer befund", "ambulanter patientenbrief",
    "konsil fuer augenheilkunde", "langzeit-ekg", "24h-rr-messung", "laborbefund",
}
BOILERPLATE = re.compile(
    r"^(frau|herr|beispielpatientin|strasse\b|straße\b|plz\b|ort\b|patient\(in\)|fall\b|fall-id|fallzahl|"
    r"patienten-id|sehr geehrte|mit freundlichen|mit kollegialen|oa\b|prim\b|arzt\b|"
    r"befund(et)?:\s*dr|vidiert|zuweiser|zuweisung freigegeben|nn_|parameter$|fettgedruckte|"
    r"\w*,? am \d{1,2}\.\d{1,2}\.\d{4}|beispielpatientin, geb)", re.IGNORECASE)
TABLE_HEADER = re.compile(r"medikation", re.IGNORECASE)
TABLE_END = re.compile(r"^(mit freundlichen|mit kollegialen)", re.IGNORECASE)
FIELD = re.compile(r"^([A-Za-zÄÖÜäöüß][\wÄÖÜäöüß .()/-]{1,38}?):\s+\S")
NO_SPLIT_ABBR = {
    "dr", "prof", "st", "z", "ca", "bzw", "inkl", "vs", "geb", "nr", "li", "re", "bds", "sin",
    "ggf", "pat", "oa", "prim", "ua", "usw", "zb", "sog", "evtl", "art", "a", "v", "p", "n",
    "mell", "diab", "gem", "vd", "lt", "ventr", "kalk", "tel", "abs", "max", "min", "mo", "mi", "ab", "na", "s", "i",
    "wg", "bzgl", "insb", "bspw", "vgl", "zust",
}
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ0-9(])")
DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


def clean_text(raw: str) -> str:
    return html.unescape(raw.replace("<BR>", "\n").replace("\r", ""))


@dataclass
class Document:
    doc_id: str
    title: str
    doc_type: str
    date: date | None
    text: str  # cleaned


def load_documents(patient_dir: Path) -> list[Document]:
    docs = []
    for f in sorted((patient_dir / "documents").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        meta = d.get("metadata", {})
        try:
            ddate = date.fromisoformat(meta.get("date", ""))
        except ValueError:
            ddate = None
        docs.append(Document(meta.get("id", f.stem), meta.get("title", ""), meta.get("type", ""),
                             ddate, clean_text(d.get("text", ""))))
    return docs


def _is_header(line: str) -> bool:
    s = line.strip()
    if s.endswith(":") and 2 < len(s) <= 60 and re.match(r"[A-Za-zÄÖÜäöüß]{2}", s):
        return True
    return s.lower().rstrip(":") in KNOWN_HEADERS


def _split_sentences(text: str, base: int):
    """Yield (start, end) of sentences inside text, offsets shifted by base."""
    start = 0
    for m in SENTENCE_END.finditer(text):
        before = text[:m.start()].rstrip()
        word = re.findall(r"([A-Za-zÄÖÜäöüß]+)\.$", before)
        if word and word[-1].lower() in NO_SPLIT_ABBR:
            continue
        if text[start:m.start()].strip():
            yield base + start, base + m.start()
        start = m.end()
    if text[start:].strip():
        yield base + start, base + len(text.rstrip())


def segment_document(doc: Document) -> list[Segment]:
    text = doc.text
    lines = []  # (start, end, stripped text)
    pos = 0
    for raw in text.split("\n"):
        lead = len(raw) - len(raw.lstrip())
        s = raw.strip()
        if s:
            lines.append((pos + lead, pos + lead + len(s), s))
        pos += len(raw) + 1

    segments: list[Segment] = []
    section = ""
    in_table = False

    def add(start, end, kind, label=""):
        segments.append(Segment(
            segment_id=f"{doc.doc_id}#{len(segments):03d}", doc_id=doc.doc_id, start=start,
            end=end, text=text[start:end], kind=kind, section=section, label=label,
            doc_date=doc.date))

    i = 0
    while i < len(lines):
        start, end, s = lines[i]
        if BOILERPLATE.match(s):
            if TABLE_END.match(s):
                in_table = False
            add(start, end, "boilerplate")
            i += 1
            continue
        if _is_header(s):
            section = s.rstrip(":").strip()
            in_table = bool(TABLE_HEADER.search(section))
            add(start, end, "header")
            i += 1
            continue
        if in_table:
            add(start, end, "table_row")
            i += 1
            continue
        # join hard-wrapped lines into one paragraph
        j = i
        while j + 1 < len(lines):
            cur = lines[j][2]
            nxt = lines[j + 1][2]
            if BOILERPLATE.match(nxt) or _is_header(nxt) or FIELD.match(nxt):
                break
            wrapped = not re.search(r"[.:!?;)]$", cur) and (nxt[:1].islower() or len(cur) >= 60)
            if not wrapped:
                break
            j += 1
        pstart, pend = start, lines[j][1]
        para = text[pstart:pend]
        fm = FIELD.match(para)
        if fm and j == i and len(para) <= 160:
            add(pstart, pend, "field", label=fm.group(1).strip())
        else:
            for a, b in _split_sentences(para, pstart):
                sub = text[a:b]
                fm2 = FIELD.match(sub)
                add(a, b, "field" if fm2 and len(sub) <= 160 else "sentence",
                    label=fm2.group(1).strip() if fm2 and len(sub) <= 160 else "")
        i = j + 1
    return segments


def dates_in(text: str) -> list[date]:
    out = []
    for d, m, y in DATE_RE.findall(text):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    return out
