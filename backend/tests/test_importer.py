"""Patient import (app.importer) and the server's /api/import path. Uses the invented patient in
tests/fixtures/patient-9999-0002 (no challenge data, no network: dense search is switched off)."""
import json
from pathlib import Path

import pytest

from app import importer, remarker
from app.importer import ImportProblem, classify, files_from_folder, write_record

FIXTURE = Path(__file__).parent / "fixtures" / "patient-9999-0002"
PATIENT = {"id": "9999-0099", "name": "Erika Probe", "dateOfBirth": "1950-01-02", "sex": "female"}


def doc(doc_id, text="Diagnosen:<BR>Arterielle Hypertonie", day="2024-01-05"):
    return {"name": f"documents/{doc_id}.json",
            "text": json.dumps({"metadata": {"id": doc_id, "date": day, "title": "Brief", "type": "Arztbrief"}, "text": text})}


def upload(*docs, patient=PATIENT, extra=()):
    files = [{"name": "patient-x/patient.json", "text": json.dumps(patient)}, *docs, *extra]
    return files


def test_folder_and_loose_files_are_recognised_by_name_and_content():
    patient, docs, extras, warnings = classify(upload(doc("D1"), doc("D2"), extra=[
        {"name": "x/documents.json", "text": json.dumps({"documents": []})}]))
    assert patient["id"] == "9999-0099" and sorted(docs) == ["D1", "D2"] and list(extras) == ["documents.json"]
    assert warnings == []


@pytest.mark.parametrize("files,message", [
    ([doc("D1")], "patient.json is missing"),
    (upload(patient={"id": "9999-0099", "name": "X"}), "dateOfBirth"),
    (upload(doc("D1"), patient={**PATIENT, "id": "../../evil"}), "id"),
    (upload(), "No documents"),
    ([], "No files"),
])
def test_unusable_uploads_are_refused(files, message):
    with pytest.raises(ImportProblem, match=message):
        classify(files)


def test_bad_files_are_skipped_with_a_note():
    bad_json = {"name": "documents/D3.json", "text": "{not json"}
    bad_id = {"name": "documents/D4.json",
              "text": json.dumps({"metadata": {"id": "../D4", "date": "2024-01-01"}, "text": "x"})}
    other = {"name": "notes.txt", "text": "hello"}
    undated = doc("D5", day="")
    _, docs, _, warnings = classify(upload(doc("D1"), bad_json, bad_id, other, undated))
    assert sorted(docs) == ["D1", "D5"]
    joined = " ".join(warnings)
    assert "D3.json" in joined and "unsupported characters" in joined and "notes.txt" in joined and "no date" in joined


def test_path_like_names_never_leave_the_import_folder(tmp_path):
    files = upload({"name": "../../outside/D1.json", "text": doc("D1")["text"]},
                   extra=[{"name": "..\\..\\cave.json", "text": "{}"}])
    folder = write_record(*classify(files)[:3], root=tmp_path)
    written = {p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()}
    assert written == {"patient-9999-0099/patient.json", "patient-9999-0099/documents/D1.json",
                       "patient-9999-0099/cave.json"}
    assert folder == tmp_path / "patient-9999-0099"


def test_reimport_replaces_the_old_record(tmp_path):
    write_record(*classify(upload(doc("D1"), doc("D2")))[:3], root=tmp_path)
    folder = write_record(*classify(upload(doc("D3")))[:3], root=tmp_path)
    assert sorted(p.name for p in (folder / "documents").iterdir()) == ["D3.json"]


def test_fixture_round_trip_runs_blocks_1_to_4_offline(tmp_path):
    out = importer.import_files(files_from_folder(FIXTURE), root=tmp_path)
    assert out["report"]["documents"] == 4 and out["patient"]["name"] == "Franz Testmann"
    assert out["evidence"] is not None and out["report"]["facts"] > 0
    assert (tmp_path / "patient-9999-0002" / "handoff" / "manifest.json").exists()


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """Server App with imports and the remarker index under tmp_path and no embedding API."""
    def no_embedder(*a, **k):
        raise remarker.EmbeddingError("disabled in tests")
    monkeypatch.setattr(remarker, "GeminiEmbedder", no_embedder)
    monkeypatch.setattr(remarker, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(importer, "IMPORT_DIR", tmp_path / "imports")
    from app.server import App
    return App(None, use_llm=False)


def test_server_imports_and_assesses_the_new_patient(offline):
    app = offline
    report = app.import_files(files_from_folder(FIXTURE))
    assert report["patient"]["birthDate"] == "1948-02-11" and report["documents"] == 4
    assert app.find("", "") is app.find("Franz Testmann", "1948-02-11") is not None
    assert app.find("Franz Testmann", "1999-01-01") is None
    res = app.find("Testmann", "1948-02-11").assess("Pulmonologist, COPD follow-up")
    items = {i["item_id"]: i for i in res["result"]["items"]}
    assert items["respiratory_status"]["status"] == "found"
    assert items["allergies"]["status"] == "found"
    assert any("no allergies are known" in c["explanation"] for c in res["result"]["conflicts"])


def test_imports_survive_a_server_restart(offline):
    offline.import_files(files_from_folder(FIXTURE))
    from app.server import App
    again = App(None, use_llm=False)
    again.load_imports()
    assert again.find("Franz Testmann", "1948-02-11") is not None


def test_a_stored_import_never_replaces_a_patient_loaded_at_startup(offline, tmp_path):
    offline.import_files(files_from_folder(FIXTURE))
    from app.server import App, PatientState
    again = App(None, use_llm=False)
    startup = PatientState(FIXTURE, use_llm=False, evidence=False)
    again.add(startup)
    again.load_imports()
    assert again.find("Franz Testmann", "1948-02-11") is startup


def test_knee_case_drug_table_plans_sides_and_allergy(offline):
    """Invented patient 9999-0003: brand-name anticoagulant only in the discharge table, a planned
    anaesthesia visit, knee side rechts vs links, allergy vs 'keine bekannt' (no embeddings)."""
    app = offline
    app.import_files(files_from_folder(Path(__file__).parent / "fixtures" / "patient-9999-0003"))
    res = app.find("Eva Probst", "1952-09-30").assess("Anaesthetist, pre-operative check before knee replacement")
    items = {i["item_id"]: i for i in res["result"]["items"]}
    assert items["anticoagulants"]["flags"][0]["text"].startswith("Eliquis 5mg")
    assert items["previous_anaesthesia"]["status"] == "not_documented"
    assert items["current_medication"]["status"] == "found"
    kinds = sorted(c["kind"] for c in res["result"]["conflicts"])
    assert kinds == ["laterality", "status"]
