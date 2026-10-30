"""Keywords and short document names. All texts are invented."""
from datetime import date

from app.contracts import Flag, LocalizedText
from app.evidence_bridge import FactLite
from app.final_contracts import ItemResult
from app.keywords import _patterns, doc_labels, keyword_for
from app.segmenter import Document, segment_document
from app.summary import template_claim

DOC = ("Vorgeschichte. Stabil eingestellter Diabetes Typ II mit HbA1c von 6,4%, sonst unauffällig. "
       "Aspirin 100mg oral 1 0 0 0 ST\n"
       "Die Patientin wurde besprochen und eine Kontrolle des Blutdrucks in 2 Wochen wird empfohlen. "
       "Patientin geb. am 01.02.1950 kommt zur Aufnahme.")


def flag_for(sentence, doc_id="D1", fact_ids=(), terms=()):
    start = DOC.index(sentence)
    return Flag(segment_id=f"{doc_id}#1", doc_id=doc_id, start=start, end=start + len(sentence), text=sentence,
                section="", doc_date=date(2020, 1, 1), ridx=0.9, signals={}, matched_terms=list(terms),
                polarity="affirmed", fact_ids=list(fact_ids))


def fact(fid, kind, label, summary, quote, category="laboratory", concept="x"):
    start = DOC.index(quote)
    return FactLite(id=fid, category=category, concept=concept, label=label, kind=kind, assertion="affirmed",
                    status="active", laterality="", when=None, summary=summary, structured={},
                    quotes=[("D1", start, start + len(quote), quote)])


def text_at(spans):
    return [DOC[a:b] for a, b in spans]


def test_measurement_fact_gives_its_exact_words_and_highlight():
    s = "Stabil eingestellter Diabetes Typ II mit HbA1c von 6,4%, sonst unauffällig."
    hb = fact("F1", "measurement", "HbA1c", "6.4 %", "HbA1c von 6,4%", concept="hba1c")
    key, spans = keyword_for(flag_for(s, fact_ids=["F1"]), [hb], _patterns(["hba1c"]))
    assert key == "HbA1c von 6,4%" and text_at(spans) == ["HbA1c von 6,4%"]


def test_drug_fits_by_kind_and_shows_the_rendered_dose():
    s = "Aspirin 100mg oral 1 0 0 0 ST"
    ass = fact("F2", "medication", "Aspirin", "Aspirin 100 mg oral 1-0-0-0", s, category="medications")
    key, spans = keyword_for(flag_for(s, fact_ids=["F2"]), [ass], _patterns(["blood thinner"]))
    assert key == "Aspirin 100 mg oral 1-0-0-0" and text_at(spans) == [s]


def test_birth_date_fact_is_never_a_keyword():
    s = "Patientin geb. am 01.02.1950 kommt zur Aufnahme."
    dob = fact("F3", "attribute", "Geburtsdatum", "1950-02-01", "01.02.1950", category="demographics",
               concept="birth_date")
    key, _ = keyword_for(flag_for(s, fact_ids=["F3"]), [dob], _patterns(["geburtsdatum", "aufnahme"]))
    assert "1950" not in key


def test_clause_with_the_item_term_and_the_longer_clause_on_a_tie():
    s = "Die Patientin wurde besprochen und eine Kontrolle des Blutdrucks in 2 Wochen wird empfohlen."
    key, spans = keyword_for(flag_for(s), [], _patterns(["kontrolle*"]))
    assert key == "eine Kontrolle des Blutdrucks in 2 Wochen wird empfohlen"
    assert text_at(spans) == [key]


def test_short_passage_whole_long_passage_first_words():
    s = "Aspirin 100mg oral 1 0 0 0 ST"
    assert keyword_for(flag_for(s), [], [])[0] == s
    long = "Stabil eingestellter Diabetes Typ II mit HbA1c von 6,4%, sonst unauffällig."
    key, spans = keyword_for(flag_for(long), [], _patterns(["nichts"]))
    assert key.endswith(" …") and len(key.split()) == 11 and DOC[spans[0][0]:spans[0][1]] == key[:-2]


def test_quote_running_past_the_passage_still_counts():
    s = "Stabil eingestellter Diabetes Typ II mit HbA1c"   # the segmenter cut the sentence here
    hb = fact("F4", "attribute", "Recorded HbA1c", "HbA1c von 6,4%", "HbA1c von 6,4%, sonst unauffällig.")
    hb.quotes = [("D1", DOC.index("Stabil eingestellter"), DOC.index("sonst") + 5, DOC[DOC.index("Stabil eingestellter"):DOC.index("sonst") + 5])]
    key, spans = keyword_for(flag_for(s, fact_ids=["F4"]), [hb], _patterns(["hba1c"]))
    assert spans and all(s.find(t) >= 0 for t in text_at(spans))


def test_abbreviation_wg_does_not_end_a_sentence():
    text = "Einweisungsdiagnose wg. Synkope mit Sturz. Stabil eingestellter Diabetes."
    segs = segment_document(Document("D9", "Brief", "Arztbrief", date(2020, 1, 1), text))
    assert segs[0].text.startswith("Einweisungsdiagnose wg. Synkope mit Sturz")


def test_doc_labels_name_month_and_add_the_day_on_a_clash():
    labels = doc_labels({
        "A": {"type": "Arztbrief(Inter.)", "title": "Stat. Patientenbrief", "date": "2016-04-15"},
        "B": {"type": "HistoBefund", "title": "Histologie-Befund", "date": "2016-04-13"},
        "C": {"type": "Arztbrief(Inter.)", "title": "Stat. Patientenbrief", "date": "2016-04-02"},
        "D": {"type": "Sonstiger Befund", "title": "Langzeit-EKG", "date": None},
    })
    assert labels["B"] == {"en": "Histology 04/2016", "de": "Histologie 04/2016"}
    assert labels["A"]["de"] == "Arztbrief 15.04.2016" and labels["C"]["de"] == "Arztbrief 02.04.2016"
    assert labels["D"]["en"] == "Long-term ECG"


def test_template_line_shows_keyword_and_document_name():
    s = "Aspirin 100mg oral 1 0 0 0 ST"
    f = flag_for(s)
    f.keyword = "Aspirin 100 mg oral 1-0-0-0"
    it = ItemResult(item_id="x", label=LocalizedText(en="Blood thinners", de="Blutverdünner"), priority="critical",
                    status="found", order=0, flags=[f])
    c = template_claim(it, "de", "T1", "current", {"D1": {"en": "Discharge letter 01/2020", "de": "Arztbrief 01/2020"}})
    assert c.text == "Blood thinners: Aspirin 100 mg oral 1-0-0-0 (Arztbrief 01/2020)".replace("Blood thinners", "Blutverdünner")
    assert c.cites == ["D1#1"]


def test_value_clause_joins_a_fact_without_the_value():
    s = "Die Patientin wurde besprochen und eine Kontrolle des Blutdrucks in 2 Wochen wird empfohlen."
    plan = fact("F5", "event", "Kontrolle", "Kontrolle", "Kontrolle des Blutdrucks", category="care_plans",
                concept="followup:kontrolle")
    key, spans = keyword_for(flag_for(s), [plan], _patterns(["kontrolle*"]))
    assert "in 2 Wochen" in key and len(spans) == 2


def test_decimal_comma_does_not_split_a_clause():
    s = "Stabil eingestellter Diabetes Typ II mit HbA1c von 6,4%, sonst unauffällig."
    key, _ = keyword_for(flag_for(s), [], _patterns(["hba1c"]))
    assert key.endswith("HbA1c von 6,4%")
