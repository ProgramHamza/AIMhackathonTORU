"""Writes tests/fixtures/patient-9999-0002: an INVENTED patient in the challenge's folder format.

Nothing here comes from the challenge data. The record is built to test imports and to find
checklist gaps on a case unlike the test patient: COPD on oxygen, atrial fibrillation on
phenprocoumon (INR), chronic kidney disease, penicillin allergy, two planted contradictions
(allergy present vs "keine bekannt", ejection fraction 45 % vs 55 %).

    python tests/fixtures/make_patient_9999_0002.py
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "patient-9999-0002"
HOSPITAL = "Testklinikum Süd"

PATIENT = {
    "id": "9999-0002", "name": "Franz Testmann", "sex": "male", "age": 78, "dateOfBirth": "1948-02-11",
    "latestAdmission": {"id": "9999-0102", "type": "inpatient",
                        "admission": {"date": "2023-11-16", "time": "10:15:00"},
                        "discharge": {"date": "2023-11-20", "time": "11:00:00"}},
}


def br(*lines: str) -> str:
    return "<BR>".join(lines)


DOCS = [
    ("9999000201", "2023-11-20", "Stat. Patientenbrief (Interne)", "Arztbrief(Inter.)", "Innere Medizin - Pneumologie", br(
        "Testklinikum Süd, 2. Medizinische Abteilung",
        "Patient(in): NN_9999-0002",
        "Sehr geehrte Frau Kollegin, sehr geehrter Herr Kollege!",
        "Wir berichten über den stationären Aufenthalt von Herrn NN_9999-0002, geb. am 11.02.1948, vom 16.11.2023 bis 20.11.2023.",
        "Diagnosen:",
        "Infektexazerbation einer COPD GOLD 3, Gruppe E",
        "Vorhofflimmern, permanent, CHA2DS2-VASc-Score 4",
        "Chronische Niereninsuffizienz Stadium G3b",
        "Arterielle Hypertonie",
        "Diabetes mellitus Typ 2, nicht insulinpflichtig",
        "Allergien:",
        "Penicillin-Allergie (generalisiertes Exanthem 2009)",
        "Anamnese:",
        "Der Patient wurde wegen zunehmender Atemnot und gelblichem Auswurf seit 4 Tagen aufgenommen. "
        "Raucheranamnese 45 pack years, Nichtraucher seit 2019.",
        "Status bei Aufnahme:",
        "RR 145/85 mmHg, HF 88/min arrhythmisch, SpO2 89% unter Raumluft, Temperatur 37.9°C",
        "Größe: 176 cm, Gewicht: 82 kg",
        "Verlauf:",
        "Unter Therapie mit Prednisolon 40 mg für 5 Tage, inhalativer Bronchodilatation und Doxycyclin "
        "(Penicillin-Allergie) besserte sich die Atemnot rasch.",
        "Die Antikoagulation mit Marcoumar wurde fortgeführt, INR bei Entlassung 2,6.",
        "Echokardiographisch zeigte sich eine leicht reduzierte linksventrikuläre Funktion mit einer EF von 55%.",
        "Labor:",
        "Kreatinin 1,8 mg/dl, eGFR 38 ml/min/1,73m², Kalium 5,1 mmol/l, HbA1c 7,2%, CRP 48 mg/l",
        "Medikation bei Entlassung:",
        "Marcoumar 3mg oral nach INR-Plan",
        "Spiriva 18mcg inhalativ 1 0 0 0",
        "Symbicort 160/4,5 inhalativ 2 0 2 0 Hub",
        "Bisoprolol 5mg oral 1 0 0 0",
        "Ramipril 5mg oral 1 0 0 0",
        "Metformin 500mg oral 1 0 1 0",
        "Furosemid 40mg oral 1 0 0 0",
        "Empfehlungen:",
        "INR-Kontrolle wöchentlich beim Hausarzt, Ziel-INR 2-3.",
        "Kontrolle der Nierenfunktion und des Kaliums in 2 Wochen.",
        "Lungenfunktionsprüfung in 3 Monaten in der pneumologischen Ambulanz.",
        "Bei eGFR unter 30 ml/min ist Metformin abzusetzen.",
        "Mit freundlichen kollegialen Grüßen",
    )),
    ("9999000202", "2023-11-17", "Echokardiographie", "Sonstiger Befund", "Innere Medizin - Kardiologie", br(
        "Echokardiographie",
        "Fragestellung: LV-Funktion bei Vorhofflimmern?",
        "Befund:",
        "Linker Ventrikel normal groß, global leicht reduzierte systolische Funktion, EF 45%.",
        "Mittelgradige Mitralinsuffizienz.",
        "Linker Vorhof deutlich dilatiert.",
        "Rechter Ventrikel normal, kein Perikarderguss.",
        "Beurteilung: Leicht reduzierte LV-Funktion (EF 45%) bei Vorhofflimmern.",
    )),
    ("9999000203", "2024-02-10", "Laborbefund", "Laborbefund", "Zentrallabor", br(
        "Laborbefund",
        "Kreatinin 2,1 mg/dl (erhöht)",
        "eGFR 31 ml/min/1,73m²",
        "Kalium 5,4 mmol/l (erhöht)",
        "INR 3,4 (über Zielbereich)",
        "Hämoglobin 12,1 g/dl",
        "HbA1c 7,0%",
    )),
    ("9999000204", "2024-02-14", "Ambulanter Patientenbrief", "Ambulanzbrief(Inter.)", "Innere Medizin - Pneumologie", br(
        "Pneumologische Ambulanz",
        "Patient(in): NN_9999-0002",
        "Allergien: keine bekannt",
        "Anamnese:",
        "Kontrolle nach Exazerbation. Belastungsdyspnoe nach 1 Stockwerk, keine erneute Exazerbation.",
        "Lungenfunktion:",
        "FEV1 1,32 l (42% des Sollwerts), FEV1/FVC 0,51",
        "Blutgase unter Raumluft: pO2 54 mmHg",
        "Gewicht: 79 kg",
        "Beurteilung:",
        "COPD GOLD 3 mit chronischer respiratorischer Insuffizienz.",
        "Procedere:",
        "Umstellung von Symbicort auf Trimbow 87/5/9 inhalativ 2 0 2 0 Hub.",
        "Einleitung einer Langzeit-Sauerstofftherapie mit 2 l/min, mindestens 16 Stunden pro Tag.",
        "Pneumokokken- und Influenza-Impfung empfohlen.",
        "Nächste Kontrolle in 3 Monaten.",
    )),
]


def main():
    (OUT / "documents").mkdir(parents=True, exist_ok=True)
    (OUT / "patient.json").write_text(json.dumps(PATIENT, ensure_ascii=False, indent=2), encoding="utf-8")
    listing = []
    for doc_id, day, title, dtype, division, text in DOCS:
        meta = {"id": doc_id, "title": title, "version": "1", "date": day, "type": dtype, "group": "Befund",
                "division": division, "hospital": HOSPITAL, "department": "2. Medizinische Abteilung",
                "admission": {"id": "9999-0102", "type": "inpatient"}}
        (OUT / "documents" / f"{doc_id}.json").write_text(json.dumps({"metadata": meta, "text": text}, ensure_ascii=False, indent=2),
                                                          encoding="utf-8")
        listing.append({k: meta[k] for k in ("id", "title", "version", "date", "type", "group", "division", "hospital")})
    (OUT / "documents.json").write_text(json.dumps({"documents": listing}, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
