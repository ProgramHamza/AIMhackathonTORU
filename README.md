# Clinical summary desk (AIM Healthcare Hackathon, Track 1)

A clinician types role and task ("anaesthetist, pre-operative check before breast surgery") and
gets one screen with the patient facts that task needs, each linked to its source passage.

## Layout

```
backend/               Python, blocks 5-8 and the interim blocks they need
  app/
    contracts.py         shared data models (Pydantic)
    tree.py              block 5a: decision graph (compile, match, activate, score)
    prompt_analysis.py   block 5b: prompt -> QueryPlan (graph, embeddings, LLM, hand-off checks)
    semantic.py          block 5c: embedding fallback for unknown prompt words
    llm_client.py        block 3a: Claude / Gemini / Ollama with fallbacks
    embeddings.py        Gemini embeddings and Jina reranker, disk-cached
    segmenter.py         interim block 1: documents -> segments
    remarker.py          blocks 6/7: flags passages per checklist item
  data/
    tree.yaml            the hand-written graph (review with clinicians)
    generated/           machine-generated aliases and concepts (review before relying on them)
  scripts/expand_graph.py  regenerates data/generated with Gemini (offline, once)
  eval/                  test prompts (cases.yaml), evaluation runner, HTML report builder
  tests/                 unit tests
clinical-ui/           React + TypeScript + Tailwind screen
docs/                  architecture flowchart, system diagram, evaluation report
```

## Setup (backend)

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

Copy `backend/.env.example` to `backend/.env` and add a key (`API_KEY` or `GEMINI_API_KEY` for
Gemini, `ANTHROPIC_API_KEY` for Claude). `.env` is gitignored. The patient data folder
(`data/` of the challenge repo) must never be committed.

## Everyday commands (from backend/)

```bash
.venv/Scripts/python -m pytest -q                                   # tests
.venv/Scripts/python -m app.tree explain "GP, diabetes review"      # see the checklist for a prompt
.venv/Scripts/python -m eval.run_eval --mode keywords               # evaluate the graph
.venv/Scripts/python -m eval.report --out ../docs/prompt-analysis-report.html --run "Graph=keywords"
```

## Blocks 1-4 (evidence backend) and the merge

`blocks14/` is the evidence backend of the preparation team (documents → passages → verified
facts with exact quotes → derived values → contradictions), renamed from its original
`backend` package to `prep` so it can live next to ours. Its own tests run with
`python -m unittest discover -s blocks14/tests` (two need `httpx`). The prepared patient
package in `blocks14/data/handoff/` contains challenge data and is gitignored.

`backend/app/evidence_bridge.py` loads the package (hashes checked), maps every fact to our
sentence-level segments by its quote, and hands the remarker verified facts, derived values
(weight change, BMI) and accepted contradictions. The pipeline runs without the package too.

## Security and data protection

- **Outbound gate** (`app/outbound.py`): every text for a cloud model is de-identified
  (`app/deidentify.py`: names, birth date, IDs, addresses, phone numbers, clinicians,
  facilities) and refused if an identifier would still leave. HTTPS only. Local Ollama exempt.
- **Encryption at rest** (`app/vault.py`): all caches are AES-256-GCM encrypted. Key in
  `DATA_KEY` or `backend/.cache/.data_key`. `python -m app.vault encrypt-cache` migrates old
  plain caches; `python -m app.vault new-key` prints a fresh key.
- Legal frame and residual risks: `docs/data-protection.md`.
- Every result carries `privacy` (what was replaced, what was refused) and `coverage`
  (documents and segments searched, verified facts used).

## Data

The challenge dataset is not part of this repository (`data/` is gitignored). To try the app without it, use the
invented sample patient in `sample-data/patient-9001-0001` (same folder format: `patient.json`, `documents.json`,
`documents/<id>.json`). The evaluation scripts and reports were run on the challenge data; their dataset-specific
inputs stay private.

## Running the app (backend + frontend)

```bash
cd backend && .venv/Scripts/python -m app.server --patient <dir>     # API on 127.0.0.1:8000
cd frontend && npm ci && npm run dev -- --host 127.0.0.1 --port 4289
```

`frontend/` is the React workspace UI. Vite proxies `/api` to the backend (`BACKEND_URL` overrides it).
`POST /api/assess {name, birthDate, task}` returns the segmented documents and the pipeline result;
`frontend/src/lib/backend.js` maps them to the UI and drops any citation that does not resolve.
Empty name and birth date load the server's patient. No patient data is bundled into a build.

Run the whole chain: `python -m app.pipeline "anaesthetist, pre-op check before breast surgery" --patient <dir>`.
Evaluate it: `python -m eval.run_pipeline --patient <dir> --expected <cases/expected.json> --tag v2`,
then `python -m eval.make_report4`.
