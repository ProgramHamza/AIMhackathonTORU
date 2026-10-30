from datetime import date

from app.segmenter import Document, clean_text, segment_document
from app.server import ui_document

RAW = ("Frau<BR>Testpatientin<BR><BR>Diagnosen:<BR>Diabetes Mellitus Typ II<BR>Art. Hypertonie<BR><BR>"
       "Befunde:<BR>Gewicht: 70 kg<BR>Die Patientin kam zur Kontrolle. Es zeigte sich kein Befund.")


def _passages(doc):
    for s in doc["sections"]:
        if s.get("headingId"):
            yield s["headingId"], s["heading"]
        for p in s["paragraphs"]:
            for g in p:
                if isinstance(g, dict):
                    yield g["id"], g["text"]


def test_every_segment_is_a_citable_passage_with_its_exact_text():
    doc = Document("D1", "Brief", "Arztbrief", date(2016, 4, 15), clean_text(RAW))
    ui = ui_document(doc, {"department": "Interne"})
    segs = {s.segment_id: s.text for s in segment_document(doc)}
    assert dict(_passages(ui)) == segs
    assert [s.get("heading") for s in ui["sections"]][1:] == ["Diagnosen:", "Befunde:"]
    assert ui["date"] == "2016-04-15" and ui["department"] == "Interne"


def test_sentences_on_one_line_share_a_paragraph():
    doc = Document("D1", "Brief", "Arztbrief", None, clean_text(RAW))
    last = ui_document(doc, {})["sections"][-1]["paragraphs"][-1]
    assert [g if isinstance(g, str) else g["text"] for g in last] == [
        "Die Patientin kam zur Kontrolle.", " ", "Es zeigte sich kein Befund."]
