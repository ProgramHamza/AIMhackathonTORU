"""De-identification: identifiers go, clinical content stays. All strings are invented."""
from datetime import date

import pytest

from app.deidentify import Deidentifier

PATIENT = {"id": "9999-0042", "name": "Erika Beispiel", "dateOfBirth": "1961-07-23", "sex": "female"}
DOCS = [{"hospital": "Testspital Nord", "department": "3. Medizinische Abteilung", "division": "Innere Medizin"}]


@pytest.fixture
def deid():
    return Deidentifier.for_patient(PATIENT, DOCS)


@pytest.mark.parametrize("text,gone,token", [
    ("Frau Erika Beispiel, geb. 23.07.1961, kommt zur Kontrolle.", ["Erika", "Beispiel", "23.07.1961"], "[DOB]"),
    ("Patientin Beispiel Erika (23/07/1961)", ["Beispiel", "23/07/1961"], "[NAME]"),
    ("born 1961-07-23, female", ["1961-07-23"], "[DOB]"),
    ("geboren am 23. Juli 1961", ["23. Juli 1961"], "[DOB]"),
    ("Patient(in): NN_9999-0042 VN_9999-0042 | Patienten-ID: 9999-0042", ["NN_9999-0042", "VN_9999-0042", "9999-0042"], "[ID]"),
    ("Fall: 20190203 Fallzahl: 20190415", ["20190203", "20190415"], "[CASE]"),
    ("SVNR 1234 230761", ["1234 230761"], "[SVNR]"),
    ("Kontakt: erika.beispiel@example.org, Tel.: +43 1 234 56 78", ["example.org", "234 56 78"], "[PHONE]"),
    ("Teststraße 12/4\nPLZ Ort\n1090 Wien", ["Teststraße 12/4", "PLZ Ort", "1090 Wien"], "[ADDRESS]"),
    ("befundet: Dr. Hans Mustermann\nvidiert: OA Dr. Maier", ["Mustermann", "Maier"], "[CLINICIAN]"),
    ("Zuweisung freigegeben durch / Tel.: Arzt / 0047", ["0047"], "[PHONE]"),
    ("Prim. Dr. X. und ARZT XX unterschreiben", ["ARZT XX"], "[CLINICIAN]"),
    ("Testspital Nord, 3. Medizinische Abteilung", ["Testspital Nord"], "[FACILITY]"),
    ("ORTXXX, am 28.06.2015\nOrtXX, am 13.06.2015\nWien, am 05.04.2016", ["ORTXXX", "OrtXX", "Wien"], "[PLACE]"),
    ("Beispielpatientin, 56-jährige Pat.", ["Beispielpatientin"], "[NAME]"),
    ("Zuweiser: Dr Arzt\nEntnahmedatum: 21.03.2019", ["Dr Arzt"], "[CLINICIAN]"),
    ("OA XYZ Prim. Dr. X. Mustermann", ["XYZ", "Mustermann"], "[CLINICIAN]"),
])
def test_identifiers_are_replaced(deid, text, gone, token):
    out = deid.scrub(text)
    for g in gone:
        assert g not in out.text, (g, out.text)
    assert token in out.text
    assert deid.leaks(out.text) == []


def test_clinical_content_survives(deid):
    text = ("Aufnahme am 03/02/2019 | Entlassen am 08/02/2019\nHbA1c 6,4%\nCandesartan 8mg oral 1 0 0 0 ST\n"
            "Schädel-CT (04.02.2019): nativ. EF 60%. 60%ige Stenose der A. carotis interna links.\n"
            "56-jährige Pat., Größe: 164 cm, Gewicht: 71 kg, BMI 26.4. Nächste Kontrolle in 2 Monaten.")
    out = deid.scrub(text)
    assert out.text == text, out.text  # nothing here identifies the person


def test_dates_of_care_keep_but_birth_date_goes(deid):
    out = deid.scrub("geb. am 23.07.1961, Aufnahme am 12.06.2015")
    assert "23.07.1961" not in out.text and "12.06.2015" in out.text


def test_leaks_detects_raw_identifiers(deid):
    assert deid.leaks("Erika Beispiel") and deid.leaks("23.07.1961") and deid.leaks("NN_9999-0042")
    assert deid.leaks("geb. 01.01.2000")  # any birth-date phrase, even for another person
    assert not deid.leaks("EF 60% am 12.06.2015")


def test_scrub_is_idempotent_and_counts(deid):
    once = deid.scrub("Erika Beispiel, geb. 23.07.1961, NN_9999-0042")
    twice = deid.scrub(once.text)
    assert once.text == twice.text and not twice.changed
    assert once.replaced["NAME"] >= 1 and once.replaced["DOB"] >= 1 and once.replaced["ID"] >= 1


def test_generic_patterns_work_without_patient_context():
    d = Deidentifier()
    out = d.scrub("Beispielpatientin NN_9001-0001, geb. 02.09.1957, Fallzahl: 20190203, Dr. Arzt")
    assert "9001-0001" not in out.text and "02.09.1957" not in out.text and "20190203" not in out.text
    assert "Dr. Arzt" not in out.text and d.leaks(out.text) == []


def test_name_match_is_whole_word(deid):
    # "Beispiel" is the patient's surname; the common word inside another token must stay
    assert deid.scrub("Beispielmedikation").text == "Beispielmedikation"


def test_for_patient_handles_missing_fields():
    d = Deidentifier.for_patient({}, [])
    assert d.scrub("nothing personal here").text == "nothing personal here"
    assert Deidentifier.for_patient({"dateOfBirth": "not-a-date", "name": ""}, None).leaks("x") == []


@pytest.mark.parametrize("text", [
    "Which drugs lower her blood sugar?",
    "64 kg during her hospital stay in March 2019",
    "Atemwege frei, Zugangsweg rechts, Ringknorpel unauffällig",
    "Monitoring ring finger, Einweg-Katheter",
    "Blutdruckmessung im Liegen, Kontrolle in 2 Wochen",
])
def test_clinical_words_are_not_addresses(deid, text):
    assert deid.scrub(text).text == text


@pytest.mark.parametrize("text", ["Hauptstraße 12/4", "Teststraße 12", "Mozartgasse 3a", "Straße XY/AB", "Ringweg 7 / 2"])
def test_streets_are_addresses(deid, text):
    assert "[ADDRESS]" in deid.scrub(text).text


def test_clinician_pattern_stops_at_line_end(deid):
    out = deid.scrub("Zuweiser: Dr Arzt\nEntnahmedatum: 21.03.2019")
    assert "Entnahmedatum: 21.03.2019" in out.text and "Arzt" not in out.text


def test_dob_variants_cover_common_formats():
    d = Deidentifier(dob=date(1961, 7, 23))
    for s in ("23.07.1961", "23/07/1961", "1961-07-23", "23.7.1961", "23 July 1961", "July 23, 1961", "07/23/1961"):
        assert "[DOB]" in d.scrub(s).text, s
