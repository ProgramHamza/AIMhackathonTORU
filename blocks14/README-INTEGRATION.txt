CLINICAL BACKEND - PRIVATE TEAM INTEGRATION PACKAGE

This is the offline evidence backend and prepared supplied-patient dataset.
It is not a running HTTP API and does not include the frontend application.
The supplied challenge data must stay private to the team; do not publish data/.
No provider credentials or model-response caches are included.

QUICK START (Python 3.12 tested; commands from the extracted folder)
  python -m venv .venv
  .venv\Scripts\python.exe -m pip install -r backend/requirements.txt
  .venv\Scripts\python.exe integration_example.py
On macOS/Linux use .venv/bin/python instead of .venv\Scripts\python.exe.
The example loads and validates the prepared package without any API calls.
For deterministic regression checks:
  .venv\Scripts\python.exe -m unittest discover -s tests -q

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
  python -m backend.handoff --input data/handoff/patient-0000-0001/source-evidence.json --output data/handoff/rebuilt
New model extraction needs your own local .env.local; never commit/share keys.
The original source documents are also retained inside the evidence bundle.

KNOWN LIMITS
The backend is partial by design: some extractions remain uncertain; candidates
are not confirmed contradictions; broad unseen-patient accuracy is not claimed.
The online query layer and end-to-end assessment scoring are not implemented here.
