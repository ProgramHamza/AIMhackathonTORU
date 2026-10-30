"""Build a private-team integration ZIP using an explicit file allowlist."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile


README = '''CLINICAL BACKEND - PRIVATE TEAM INTEGRATION PACKAGE

This is the offline evidence backend and prepared supplied-patient dataset.
It is not a running HTTP API and does not include the frontend application.
The supplied challenge data must stay private to the team; do not publish data/.
No provider credentials or model-response caches are included.

QUICK START (Python 3.12 tested; commands from the extracted folder)
  python -m venv .venv
  .venv\\Scripts\\python.exe -m pip install -r backend/requirements.txt
  .venv\\Scripts\\python.exe integration_example.py
On macOS/Linux use .venv/bin/python instead of .venv\\Scripts\\python.exe.
The example loads and validates the prepared package without any API calls.
For deterministic regression checks:
  .venv\\Scripts\\python.exe -m unittest discover -s tests -q

HOW TO INTEGRATE
1. Import load_patient from integration_example.py and call it once at startup.
2. Use returned evidence.facts and evidence.documents for role/task retrieval.
3. presentation_facts are source-linked display candidates; their grouping is
   recorded in reconciliation.groups. Original facts remain available by ID.
4. Use history.json for latest discharge medications and measurement history.
   Default as-of is 2016-04-15, not today. Medication lists do not prove use.
5. Display only accepted_contradictions by default; review_candidates are a
   separate unresolved workflow. Derived values link their input fact IDs.
6. Build your role/task interpretation, retrieval, summary and HTTP layer on top.
   frontend/assessment-contract.d.ts is a reference for the current UI shape.

PACKAGE CONTENTS
  backend/                  Preparation, evidence models and postprocessing
  contracts/                JSON Schemas and category/alias catalogues
  data/handoff/patient-0000-0001/   Ready-to-load versioned patient package
  docs/                     Detailed preparation and evidence contracts
  tests/ and evaluation/    Independent regression fixtures and tooling
  integration_example.py   Validated loader and concise smoke test

DATA RULES
- Check package hashes and evidence versions; do not mix index versions.
- source-evidence.json is the input for contradiction-report.json.
- evidence.json is the final bundle for normalization/reconciliation/history.
- Send exact normalized document text and quote spans to the source viewer.
  Offsets are Unicode code points; JavaScript indexing is UTF-16, so convert.
- Do not turn processing gaps or missing extracted facts into not documented.
  That requires query-specific search/review of the supplied original documents.
- Preserve negation, uncertainty, family-member subject, planned/completed status.
- A document date is not automatically an examination/measurement date.
- Patient source review notes are in review/; these are assistant reviews,
  not clinician certification and not runtime answer templates.

REBUILD WITHOUT MODEL CALLS
  python -m prep.handoff --input data/handoff/patient-0000-0001/source-evidence.json --output data/handoff/rebuilt
New model extraction needs your own local .env.local; never commit/share keys.
The original source documents are also retained inside the evidence bundle.

KNOWN LIMITS
The backend is partial by design: some extractions remain uncertain; candidates
are not confirmed contradictions; broad unseen-patient accuracy is not claimed.
The online query layer and end-to-end assessment scoring are not implemented here.
'''

EXAMPLE = '''"""Validated startup loader; this example performs no model/network calls."""
import hashlib
import json
from pathlib import Path
from prep.evidence.schema import EvidenceBundle
from prep.evidence.normalization import NormalizationIndex, bundle_hash
from prep.evidence.reconciliation import ReconciliationIndex, presentation_facts
from prep.evidence.contradictions import ContradictionReport


def load_patient(directory=None):
    root = Path(directory) if directory else Path(__file__).resolve().parent / 'data/handoff/patient-0000-0001'
    manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (root/name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Invalid package file or checksum')
    def read(name):
        return (root/name).read_text(encoding='utf-8-sig')
    source = EvidenceBundle.model_validate_json(read('source-evidence.json'))
    evidence = EvidenceBundle.model_validate_json(read('evidence.json'))
    normalization = NormalizationIndex.model_validate_json(read('normalization.json'))
    reconciliation = ReconciliationIndex.model_validate_json(read('reconciliation.json'))
    report = ContradictionReport.model_validate_json(read('contradiction-report.json'))
    normalization.validate_against(evidence)
    reconciliation.validate_against(evidence)
    report.validate_against(source)
    history = json.loads(read('history.json'))
    if manifest['evidence_version'] != evidence.manifest.evidence_version or history['source_evidence_version'] != evidence.manifest.evidence_version or history['source_bundle_sha256'] != bundle_hash(evidence):
        raise ValueError('Mixed evidence/index versions')
    return {'evidence':evidence, 'normalization':normalization, 'reconciliation':reconciliation,
        'history':history, 'facts_by_id':{f.id:f for f in evidence.facts},
        'presentation_facts':presentation_facts(evidence,reconciliation),
        'accepted_contradictions':[c for c in evidence.contradictions if c.status=='accepted'],
        'review_candidates':[c for c in evidence.contradictions if c.status=='candidate']}


if __name__ == '__main__':
    patient = load_patient()
    evidence = patient['evidence']
    print(json.dumps({'patient_id':evidence.manifest.patient_id, 'as_of':patient['history']['as_of'],
        'documents':len(evidence.documents), 'facts':len(evidence.facts), 'derived_values':len(evidence.derived_facts),
        'accepted_contradictions':len(patient['accepted_contradictions']),
        'review_candidates':len(patient['review_candidates']), 'model_calls':0},indent=2))
'''


def main():
    root=Path(__file__).resolve().parents[1]
    exports=root/'exports'
    exports.mkdir(exist_ok=True)
    destination=exports/'clinical-backend-integration.zip'
    entries={}
    for folder in ('backend','contracts','docs','tests','evaluation'):
        for path in (root/folder).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py','.json','.md','.txt'):
                entries[path.relative_to(root).as_posix()]=path.read_bytes()
    for path in (root/'data/handoff/patient-0000-0001').glob('*.json'):
        entries[path.relative_to(root).as_posix()]=path.read_bytes()
    for name in ('patient-source-review.json','encounter-date-review.json'):
        entries['review/'+name]=(root/'data/evaluation'/name).read_bytes()
    entries['frontend/assessment-contract.d.ts']=(root/'frontend/assessment-contract.d.ts').read_bytes()
    entries['README-INTEGRATION.txt']=README.encode('utf-8')
    entries['integration_example.py']=EXAMPLE.encode('utf-8')
    entries['.gitignore']=b'.venv/\n__pycache__/\ndata/\nreview/\n.env\n.env.*\n'
    for name,raw in entries.items():
        if name.startswith('.env') or re.search(rb'sk-proj-[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{25,}|AQ\.[A-Za-z0-9_-]{30,}',raw):
            raise ValueError('Potential credential detected; package not written')
    entries['FILE-CHECKSUMS.json']=json.dumps({n:hashlib.sha256(b).hexdigest() for n,b in entries.items()},indent=2).encode()
    with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,raw in sorted(entries.items()):
            archive.writestr(name,raw)
    with tempfile.TemporaryDirectory(prefix='integration-check-',dir=exports) as directory:
        checked=Path(directory).resolve()
        assert checked.is_relative_to(exports.resolve())
        with zipfile.ZipFile(destination) as archive:
            assert archive.testzip() is None
            assert all((checked/n).resolve().is_relative_to(checked) for n in archive.namelist())
            archive.extractall(checked)
        subprocess.run([sys.executable,'integration_example.py'],cwd=checked,check=True)
        subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],cwd=checked,check=True)
    print(json.dumps({'zip':str(destination),'files':len(entries),'bytes':destination.stat().st_size,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':
    main()
