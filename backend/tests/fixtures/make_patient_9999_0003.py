"""Writes tests/fixtures/patient-9999-0003: an INVENTED patient in the challenge's folder format.

Nothing here comes from the challenge data. Knee replacement pre-op case with planted problems:
a brand-name anticoagulant only in the discharge table, a planned anaesthesia visit that is not a
previous anaesthesia, the knee side documented differently (rechts / links), and an allergy
contradicted by "Allergien: keine bekannt".

    python tests/fixtures/make_patient_9999_0003.py
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "patient-9999-0003"
PATIENT = {"id": "9999-0003", "name": "Eva Probst", "sex": "female", "age": 74, "dateOfBirth": "1952-09-30"}


def br(*lines: str) -> str:
    return "<BR>".join(lines)


DOCS = [
    ("9999000301", "2024-05-10", "Stat. Patientenbrief (Interne)", "Arztbrief(Inter.)", br(
        "Patient(in): NN_9999-0003",
        "Diagnosen:",
        "Vorhofflimmern, paroxysmal",
        "Chronische Niereninsuffizienz Stadium G3a",
        "Gonarthrose rechts",
        "Allergien: Penicillin (Urtikaria)",
        "Verlauf:",
        "Kardioversion nicht erforderlich, Frequenzkontrolle mit Bisoprolol.",
        "Medikation bei Entlassung:",
        "Eliquis 5mg oral 1 0 1 0 ST",
        "Bisoprolol 2,5mg oral 1 0 0 0 ST",
        "Pantoloc 40mg oral 1 0 0 0 ST",
        "Empfehlungen:",
        "Orthopädische Vorstellung zur Planung einer Knie-TEP rechts.",
    )),
    ("9999000302", "2024-09-02", "Ambulanter Patientenbrief", "Ambulanzbrief(Inter.)", br(
        "Orthopädische Ambulanz",
        "Allergien: keine bekannt",
        "Diagnose: Gonarthrose links",
        "Procedere:",
        "Knie-TEP geplant am 14.10.2024.",
        "Pausieren der Antikoagulation nach Rücksprache mit der Anästhesie.",
        "Präoperative Vorstellung in der Anästhesieambulanz am 30.09.2024.",
    )),
]


def main():
    (OUT / "documents").mkdir(parents=True, exist_ok=True)
    (OUT / "patient.json").write_text(json.dumps(PATIENT, ensure_ascii=False, indent=2), encoding="utf-8")
    for doc_id, day, title, dtype, text in DOCS:
        meta = {"id": doc_id, "title": title, "version": "1", "date": day, "type": dtype, "group": "Befund",
                "division": "Innere Medizin", "hospital": "Testklinikum Süd", "department": "Orthopädie"}
        (OUT / "documents" / f"{doc_id}.json").write_text(json.dumps({"metadata": meta, "text": text}, ensure_ascii=False, indent=2),
                                                          encoding="utf-8")


if __name__ == "__main__":
    main()
