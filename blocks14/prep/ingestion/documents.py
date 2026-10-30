"""Normalize without rewriting clinical content; preserve exact normalized spans."""
import hashlib
import html
import json
import re
from datetime import date
from pathlib import Path

from prep.evidence.schema import Document, Passage

NORMALIZATION_VERSION = "text-br-v1"
SEGMENTATION_VERSION = "paragraph-table-v1"
MEDICATION_HEADING = re.compile(r"^(?:Entlassungsmedikation|Medikation bei Entlassung)\s*:\s*$", re.I)
TABLE_HEADER = re.compile(r"^Applikation\s+mo\s+mi\s+ab\s+na\b", re.I)
SIGNOFF = re.compile(r"^(?:Mit (?:freundlichen|kollegialen) Grüßen|Laborbefund|Befundet:|Vidiert:)", re.I)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize(text: str) -> str:
    # Strip only known presentation markup BEFORE entity decoding, retaining literal comparisons.
    text = re.sub(r"<br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:span|b|strong|i|em|u)(?:\s[^>]*)?>", "", text, flags=re.I)
    return html.unescape(text).replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")


def load_document(path: Path) -> Document:
    raw = path.read_bytes()
    obj = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(obj.get("text"), str) or not obj["text"].strip():
        raise ValueError(f"{path.name}: nonempty text is required")
    metadata = obj.get("metadata", {})
    normalized = normalize(obj["text"])
    # An explicit letter-header date wins over metadata. Invalid header dates are not repaired.
    match = re.search(r"\bam\s+(\d{1,2})\.(\d{1,2})\.(\d{4,5})\b", normalized[:1500], re.I)
    doc_date = None
    if match:
        try:
            day, month, year = map(int, match.groups())
            doc_date = date(year, month, day)
        except ValueError:
            pass
    elif metadata.get("date"):
        try:
            doc_date = date.fromisoformat(metadata["date"])
        except (ValueError, TypeError):
            pass
    return Document(id=str(metadata.get("id", path.stem)), title=metadata.get("title", path.stem),
                    source_sha256=digest(raw), document_date=doc_date, original_text=obj["text"],
                    normalized_text=normalized, normalization_version=NORMALIZATION_VERSION)


def segment_document(document: Document) -> list[Passage]:
    """Keep narrative paragraphs intact; never split on German abbreviations or decimal dots."""
    passages = []
    text = document.normalized_text
    section = None
    in_medication = False
    paragraph_start = paragraph_end = None

    def emit(start, end, kind):
        passages.append(Passage(
            id=f"{document.id}:{document.source_sha256[:16]}:{SEGMENTATION_VERSION}:{start}-{end}",
            document_id=document.id, section=section, kind=kind, start=start, end=end, text=text[start:end]))

    def flush():
        nonlocal paragraph_start, paragraph_end
        if paragraph_start is not None:
            emit(paragraph_start, paragraph_end, "paragraph")
            paragraph_start = paragraph_end = None

    cursor = 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\n")
        stripped = body.strip()
        start = cursor + len(body) - len(body.lstrip())
        end = cursor + len(body.rstrip())
        cursor += len(line)
        if not stripped:
            flush()
            continue
        heading = bool(re.fullmatch(r"[^:\n]{1,80}:\s*", stripped))
        medication_heading = bool(MEDICATION_HEADING.fullmatch(stripped))
        if medication_heading or heading or SIGNOFF.match(stripped):
            flush()
            section = stripped.rstrip(":")
            in_medication = medication_heading
            emit(start, end, "heading")
        elif in_medication:
            flush()
            emit(start, end, "heading" if TABLE_HEADER.match(stripped) else "table_row")
        else:
            if paragraph_start is None:
                paragraph_start = start
            paragraph_end = end
    flush()
    return passages
