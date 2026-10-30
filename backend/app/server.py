"""HTTP API for the clinical-workspace frontend (standard library only).

    GET  /api/health                   -> {"ok": true, "patients": <n>}
    POST /api/assess {name, birthDate, task, lang?: "en" | "de"}
         -> {patient, documents, prompt, lang, result, plan, timings_ms}
    POST /api/import {files: [{name, text}]}   (a patient folder in the challenge's format)
         -> {patient, documents, facts, contradictions, warnings, ms}

The pipeline and the segmented documents are loaded once at startup, so a request only runs
blocks 5-8. `documents` is the frontend's document shape: sections of paragraphs whose
passages carry the same segment IDs ('<doc_id>#<n>') the result cites, so every citation
resolves to the exact text it was taken from.

Name and date of birth must match a loaded patient.json; leaving both empty selects the most
recently loaded patient (the demo flow). Imported records are stored and prepared by app.importer
and replace an earlier patient with the same ID. Binds to 127.0.0.1 only: responses contain
patient data.

CLI
  python -m app.server [--patient <dir>] [--port 8000] [--no-llm]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
import unicodedata
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import importer
from .pipeline import Pipeline
from .segmenter import Document, load_documents, segment_document
from .summary import DERIVED_LABELS

MAX_BODY = 16_384
MAX_IMPORT_BODY = 25_000_000
MAX_TASK_CHARS = 1_000
LANGS = ("en", "de")  # UI language; labels, explanations and templates follow it


def ui_document(doc: Document, meta: dict) -> dict:
    """Segments -> {sections: [{heading?, paragraphs: [[str | {id, text}]]}]}.

    A header segment opens a section (its ID stays citable as headingId); a line break between segments starts a paragraph;
    whitespace between segments on one line is kept as a plain string.
    """
    sections: list[dict] = [{"paragraphs": []}]
    para: list = []
    pos = 0

    def flush():
        nonlocal para
        if para:
            sections[-1]["paragraphs"].append(para)
        para = []

    for s in segment_document(doc):
        gap = doc.text[pos:s.start]
        pos = s.end
        if s.kind == "header":
            flush()
            sections.append({"heading": s.text, "headingId": s.segment_id, "paragraphs": []})
            continue
        if "\n" in gap:
            flush()
        elif gap and para:
            para.append(" ")
        para.append({"id": s.segment_id, "text": s.text})
    flush()
    return {
        "id": doc.doc_id,
        "title": doc.title,
        "type": meta.get("title") or doc.doc_type,
        "date": doc.date.isoformat() if doc.date else None,
        "department": meta.get("department", ""),
        "facility": meta.get("hospital", ""),
        "category": meta.get("group", ""),
        "sections": [s for s in sections if s.get("heading") or s["paragraphs"]],
    }


def _norm(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.findall(r"[a-z]+", s)


class PatientState:
    """One loaded patient: its pipeline, its documents in the frontend's shape, cached answers."""

    def __init__(self, patient_dir: Path, use_llm: bool, evidence=True):
        if evidence is True:
            self.pipeline = Pipeline.from_env(patient_dir, use_llm=use_llm)
        else:  # imported record: blocks 1-4 output built at import time, or none
            self.pipeline = Pipeline.from_env(patient_dir, use_llm=use_llm, use_evidence=False)
            if evidence:
                self.pipeline.remarker.attach_evidence(patient_dir, evidence)
        self.patient = self.pipeline.patient
        metas = {}
        for f in (patient_dir / "documents").glob("*.json"):
            m = json.loads(f.read_text(encoding="utf-8")).get("metadata", {})
            metas[m.get("id", f.stem)] = m
        self.documents = [ui_document(d, metas.get(d.doc_id, {})) for d in load_documents(patient_dir)]
        self.labels = {n["id"]: n.get("label") for n in self.pipeline.analyzer.tree.nodes}
        self.lock = threading.Lock()  # the pipeline keeps caches; one request at a time
        self.cache: dict[tuple[str, str], dict] = {}

    def matches(self, name: str, birth: str) -> bool:
        full = _norm(self.patient.get("name", ""))
        q = _norm(name)
        return bool(q) and all(t in full for t in q) and birth == self.patient.get("dateOfBirth")

    def assess(self, task: str, lang: str = "en") -> dict:
        with self.lock:
            hit = self.cache.get((task, lang))
            if hit is None:
                t0 = time.perf_counter()
                res = self.pipeline.run(task, lang)
                nodes = [{**n.model_dump(mode="json"), "label": self.labels.get(n.node_id)} for n in res.plan.nodes]
                result = res.final.model_dump(mode="json")
                for d in result["derived"]:
                    d["labels"] = DERIVED_LABELS.get(d["concept"])
                hit = {"result": result,
                       "plan": {"nodes": nodes, "method": res.plan.method, "issues": res.plan.issues},
                       "timings_ms": {**res.timings_ms,
                                      "request": round((time.perf_counter() - t0) * 1000, 1)}}
                self.cache[(task, lang)] = hit
        p = self.patient
        given, _, family = p.get("name", "").rpartition(" ")
        return {"patient": {"id": p.get("id"), "givenName": given or p.get("name", ""),
                            "familyName": family, "birthDate": p.get("dateOfBirth"),
                            "sex": p.get("sex", "")},
                "documents": self.documents, "prompt": task, "lang": lang, **hit}


class App:
    def __init__(self, patient_dir: Path | None, use_llm: bool):
        self.use_llm = use_llm
        self.patients: dict[str, PatientState] = {}  # insertion order: the last one is the default
        self.lock = threading.Lock()
        if patient_dir:
            self.add(PatientState(patient_dir, use_llm))

    def add(self, state: PatientState) -> None:
        with self.lock:
            self.patients.pop(str(state.patient.get("id")), None)
            self.patients[str(state.patient.get("id"))] = state

    def find(self, name: str, birth: str) -> PatientState | None:
        with self.lock:
            states = list(self.patients.values())
        if not name.strip() and not birth:
            return states[-1] if states else None
        return next((s for s in reversed(states) if s.matches(name, birth)), None)

    def import_files(self, files: list[dict]) -> dict:
        out = importer.import_files(files)
        state = PatientState(out["folder"], self.use_llm, evidence=out["evidence"] or False)
        self.add(state)
        p = state.patient
        return {"patient": {"id": p.get("id"), "name": p.get("name"), "birthDate": p.get("dateOfBirth"),
                            "sex": p.get("sex", "")},
                **out["report"], "documents": len(state.documents), "warnings": out["warnings"]}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/api/health":
                return self._send(200, {"ok": True, "patients": len(app.patients)})
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path == "/api/import":
                return self._import()
            if self.path != "/api/assess":
                return self._send(404, {"error": "not found"})
            length = self._length()
            if not 0 < length <= MAX_BODY:
                return self._send(400, {"error": "request body missing or too large"})
            try:
                body = json.loads(self.rfile.read(length))
                name = str(body.get("name") or "")
                birth = str(body.get("birthDate") or "")
                task = str(body.get("task") or "").strip()
                lang = body.get("lang") if body.get("lang") in LANGS else "en"
            except (ValueError, AttributeError):
                return self._send(400, {"error": "invalid JSON"})
            if not task:
                return self._send(400, {"error": "Enter the role and task"})
            if len(task) > MAX_TASK_CHARS:
                return self._send(400, {"error": "Task text is too long"})
            state = app.find(name, birth)
            if state is None:
                return self._send(404, {"error": "No patient found · check name and date of birth"})
            try:
                return self._send(200, state.assess(task, lang))
            except Exception as e:  # noqa: BLE001 - reported to the UI, logged here
                self.log_error("assess failed: %r", e)
                return self._send(500, {"error": "The assessment failed on the server"})

        def _length(self) -> int:
            try:
                return int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return -1

        def _import(self):
            length = self._length()
            if not 0 < length <= MAX_IMPORT_BODY:
                return self._send(400, {"error": "upload missing or too large"})
            try:
                files = json.loads(self.rfile.read(length)).get("files")
                if not isinstance(files, list) or not all(isinstance(f, dict) for f in files):
                    raise ValueError
            except (ValueError, AttributeError):
                return self._send(400, {"error": "invalid upload"})
            try:
                return self._send(200, app.import_files(files))
            except importer.ImportProblem as e:
                return self._send(400, {"error": str(e)})
            except Exception as e:  # noqa: BLE001 - reported to the UI, logged here
                self.log_error("import failed: %r", e)
                return self._send(500, {"error": "The import failed on the server"})

        def log_message(self, fmt, *args):  # one line per request, no request bodies
            sys.stderr.write(f"{self.log_date_time_string()} {fmt % args}\n")

    return Handler


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets a second server bind the same port and silently take requests.
    allow_reuse_address = sys.platform != "win32"


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.server")
    ap.add_argument("--patient", type=Path, default=os.environ.get("PATIENT_DIR"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args(argv)
    t = time.perf_counter()
    app = App(Path(args.patient) if args.patient else None, use_llm=not args.no_llm)
    srv = Server(("127.0.0.1", args.port), make_handler(app))
    docs = sum(len(s.documents) for s in app.patients.values())
    print(f"ready on http://127.0.0.1:{args.port} ({len(app.patients)} patient(s), {docs} documents, "
          f"startup {(time.perf_counter() - t) * 1000:.0f} ms)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
