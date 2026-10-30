"""Import a patient record uploaded from the UI (POST /api/import).

The upload uses the challenge's folder layout: patient.json, documents/<id>.json ({metadata, text})
and, optionally, the extraction files (documents.json, diagnoses.json, ...). Files are recognised by
name and content, so a whole folder or loose files both work. The record is checked, written below
backend/.cache/imports/ (gitignored), and blocks 1-4 run on it offline with rules only, so no
document text leaves the machine during the import.

CLI (try a folder without the UI)
  python -m app.importer <patient folder>
  python -m app.importer --bundle <patient folder> <out.json>   (for the server's --import-bundle)
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

from .evidence_bridge import BundleError, _import_prep, load_bundle

IMPORT_DIR = Path(__file__).resolve().parent.parent / ".cache" / "imports"
MAX_FILES = 300
MAX_FILE_CHARS = 2_000_000
MAX_TOTAL_CHARS = 20_000_000
EXTRA_FILES = {"documents.json", "diagnoses.json", "medication.json", "procedures.json", "scores-all.json",
               "scores-latest.json", "cave.json", "metadata.json"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


class ImportProblem(ValueError):
    """The upload cannot be used; the message is shown to the user."""


def _parse_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def classify(files: list[dict]) -> tuple[dict, dict[str, dict], dict[str, dict], list[str]]:
    """Uploaded {name, text} files -> (patient, documents by id, extra files by name, warnings)."""
    if not files:
        raise ImportProblem("No files received")
    if len(files) > MAX_FILES:
        raise ImportProblem(f"Too many files (at most {MAX_FILES})")
    if sum(len(str(f.get("text", ""))) for f in files) > MAX_TOTAL_CHARS:
        raise ImportProblem("The upload is too large")
    patient, documents, extras, warnings = None, {}, {}, []
    for f in files:
        name = str(f.get("name", "")).replace("\\", "/").rsplit("/", 1)[-1]
        text = f.get("text")
        if not name.lower().endswith(".json"):
            warnings.append(f"{name or 'unnamed file'}: skipped (not a .json file)")
            continue
        if not isinstance(text, str) or len(text) > MAX_FILE_CHARS:
            warnings.append(f"{name}: skipped (empty or too large)")
            continue
        try:
            data = json.loads(text)
        except ValueError:
            warnings.append(f"{name}: skipped (not valid JSON)")
            continue
        if name == "patient.json":
            patient = data
        elif isinstance(data, dict) and isinstance(data.get("text"), str) and isinstance(data.get("metadata"), dict):
            doc_id = str(data["metadata"].get("id") or name[:-5])
            if not SAFE_ID.match(doc_id):
                warnings.append(f"{name}: skipped (document id {doc_id!r} has unsupported characters)")
                continue
            if not data["text"].strip():
                warnings.append(f"{name}: skipped (document text is empty)")
                continue
            if not _parse_date(data["metadata"].get("date", "")):
                warnings.append(f"document {doc_id}: no date, so it cannot be ordered in time")
            if doc_id in documents:
                warnings.append(f"document {doc_id}: uploaded twice, the last copy is used")
            data["metadata"]["id"] = doc_id
            documents[doc_id] = data
        elif name in EXTRA_FILES:
            extras[name] = data
        else:
            warnings.append(f"{name}: skipped (not part of the patient folder format)")
    if not isinstance(patient, dict):
        raise ImportProblem("patient.json is missing")
    if not str(patient.get("name", "")).strip() or not _parse_date(patient.get("dateOfBirth", "")):
        raise ImportProblem("patient.json needs a name and a dateOfBirth (YYYY-MM-DD)")
    pid = str(patient.get("id") or "")
    if not SAFE_ID.match(pid):
        raise ImportProblem("patient.json needs an id made of letters, digits, '-' or '_'")
    if not documents:
        raise ImportProblem("No documents found: expected documents/<id>.json files with metadata and text")
    return patient, documents, extras, warnings


def write_record(patient: dict, documents: dict[str, dict], extras: dict[str, dict], root: Path | None = None) -> Path:
    """Replace this patient's import folder with the uploaded record."""
    folder = Path(root or IMPORT_DIR) / f"patient-{patient['id']}"
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "documents").mkdir(parents=True)
    (folder / "patient.json").write_text(json.dumps(patient, ensure_ascii=False, indent=1), encoding="utf-8")
    for doc_id, doc in documents.items():
        (folder / "documents" / f"{doc_id}.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    for name, data in extras.items():
        (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return folder


def build_evidence(folder: Path, patient_id: str):
    """Blocks 1-4 on the imported documents (rules only, no model calls) -> (bundle, history)."""
    _import_prep()
    from prep.handoff import build_handoff
    from prep.preparation import prepare_patient
    source = prepare_patient(folder / "documents", patient_id, "independent_synthetic", client=None, concurrency=1)
    build_handoff(source, folder / "handoff")
    return load_bundle(patient_id, folder / "handoff")


def import_files(files: list[dict], root: Path | None = None) -> dict:
    """Check and store an upload, run blocks 1-4. Returns the folder, the evidence (or None) and a report."""
    t0 = time.perf_counter()
    patient, documents, extras, warnings = classify(files)
    folder = write_record(patient, documents, extras, root)
    evidence = None
    try:
        evidence = build_evidence(folder, patient["id"])
    except (BundleError, ValueError, OSError) as e:
        warnings.append(f"Verified facts (blocks 1-4) not available: {e}")
    except Exception as e:  # noqa: BLE001 - the record stays usable without facts
        warnings.append(f"Verified facts (blocks 1-4) failed: {type(e).__name__}")
    bundle = evidence[0] if evidence else None
    return {"folder": folder, "patient": patient, "evidence": evidence, "warnings": warnings,
            "report": {"documents": len(documents), "extra_files": sorted(extras),
                       "facts": len(bundle.facts) if bundle else 0,
                       "contradictions": len(bundle.contradictions) if bundle else 0,
                       "ms": round((time.perf_counter() - t0) * 1000)}}


def stored_records(root: Path | None = None):
    """Earlier imports on disk -> (folder, evidence or None), so a restarted server keeps them."""
    for folder in sorted(Path(root or IMPORT_DIR).glob("patient-*")):
        if not (folder / "patient.json").exists():
            continue
        pid = json.loads((folder / "patient.json").read_text(encoding="utf-8")).get("id", "")
        try:
            evidence = load_bundle(pid, folder / "handoff")
        except (BundleError, ValueError, OSError):
            evidence = None
        yield folder, evidence


def files_from_folder(folder: Path) -> list[dict]:
    """A patient folder on disk -> the {name, text} list the UI uploads."""
    paths = [p for p in sorted(Path(folder).rglob("*.json")) if p.is_file()]
    return [{"name": p.relative_to(folder).as_posix(), "text": p.read_text(encoding="utf-8")} for p in paths]


def write_bundle(folder: Path, out: Path) -> int:
    """patient.json + documents/*.json of a folder -> one upload body file for the server's --import-bundle."""
    files = [f for f in files_from_folder(folder) if f["name"] == "patient.json" or f["name"].startswith("documents/")]
    classify(files)  # refuse a folder the server would refuse
    out.write_text(json.dumps({"files": files}, ensure_ascii=False), encoding="utf-8")
    return len(files)


def _main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "--bundle":
        try:
            n = write_bundle(Path(argv[1]), Path(argv[2]))
        except ImportProblem as e:
            print(f"bundle refused: {e}")
            return 1
        print(f"wrote {argv[2]} ({n} files)")
        return 0
    if len(argv) != 1:
        print(__doc__)
        return 2
    try:
        out = import_files(files_from_folder(Path(argv[0])))
    except ImportProblem as e:
        print(f"import refused: {e}")
        return 1
    print(json.dumps({"folder": str(out["folder"]), **out["report"], "warnings": out["warnings"]}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
