# Preparation: structured and narrative extraction

By default this stage uses deterministic Python only, requiring no API key. It reads source JSON documents, normalizes formatting, segments narrative paragraphs and medication rows, and extracts supported discharge medication entries and labelled clinical fields. Optional Gemini (default) and OpenAI narrative extraction are documented below. Calculations, contradiction detection and the integrated handoff are separate postprocessing steps described below.

## Current development priority

Prioritize the supplied patient's eight documents and the published scenarios, including unseen role/task requests about this same patient. This is the user's explicit project preference. Independent synthetic tests remain useful regression controls, but broad multi-patient support is secondary. Do not manufacture contradictions to meet a count. Keep runtime extraction source-driven; published expected answers and patient-specific readiness checks belong only in evaluation, never runtime answer lookup.

## Run

From the repository root:

```sh
python -m pip install -r backend/requirements.txt
python -m backend.preparation
python -m unittest discover -s tests/evidence -v
```

Default output is `data/prepared/patient-0000-0001.json` (ignored). Override with `--source`, `--patient-id`, `--output`, and `--dataset-kind independent_synthetic`. Source must be a directory of document JSON files with `text` and optional `metadata`, not the directory containing IBM extraction trees. Store supplied-data outputs only under ignored paths. Malformed document JSON fails preparation rather than silently omitting documents. Writes replace the destination atomically only after bundle validation.

## Supported structure

- BR variants and CRLF line breaks, HTML entities and common inline emphasis/span markup.
- Narrative paragraphs retained across wrapped lines; no naive splitting on decimal points or German abbreviations.
- Discharge-medication headings `Entlassungsmedikation:` and `Medikation bei Entlassung:`.
- Explicit `Applikation mo mi ab na` column order; other orders are not guessed.
- Oral or subcutaneous routes; ordinary strength units; decimal commas and fractional schedules.
- Four daily slots with optional ST/tablet/drop/dose labels; once-weekly tablet instructions are preserved as frequency text without invented daily slots.
- Every fact cites the medication row, section heading and table header. Repeated identical rows have occurrence-specific offsets.

The parser uses structure, not official patient/document identifiers or a drug-name list. Its coverage is deliberately bounded. Narrative prescriptions, unrecognized table layouts, concentrations, conditional/discontinued rows and ambiguous quantities are excluded with processing gaps when encountered inside the recognized table. Arbitrary PDF, OCR, HTML tables and multilingual document formats are not yet supported.

One ambiguous medication row in the official 2015 letter contains an extra unlabelled number. The parser deliberately leaves it unresolved; it must not assume that number's unit or meaning. This will be handled by contextual extraction/review later.

## Dates, completeness and validation

### Labelled clinical fields added in structured-slice-v2

`backend/extraction/structured.py` extracts weight, height, recorded BMI, temperature, heart rate, explicitly labelled blood pressure components, EF, HbA1c, Ki-67, complete recorded TNM/V/G tuples, receptor status/percentages/Allred scores, explicit allergy lines and selected labelled event dates. Values retain source units; calculated conversions are not yet implemented. Blood pressure components share an event ID. Receptor-negative results are affirmed test results, distinct from negated clinical conditions.

Rules are bounded by labels and units: tumour size must not become patient height. Qualified, negated, family, historical, target or planned contexts are conservatively deferred where recognized. Explicit unknown allergy entries and invalid event dates produce gaps. No allergy heading or missing lab result does not create a negative fact. Unsupported wording is not exhaustively identified; the broad scope gap remains essential.

Dates labelled `Aufnahme am`, `Entlassen am` and `Entnahmedatum:` are extracted as explicit event dates if valid and unqualified. Other dates remain in source passages. Duplicate/conflicting event claims are not reconciled yet. Fallback document dates are not promoted to precise measurement dates.

An explicit `am dd.mm.yyyy` letter-header date is preferred to metadata. If it is invalid, it stays unresolved rather than being repaired. Document metadata date is used only when no recognized letter-header date exists. Medication time is explicitly a document-date fallback, not diagnosis onset or confirmed treatment start. Entries retain `clinical_status=unknown` and discharge-list context rather than claiming present-day use.

Every output is `partial`: per-document gaps state that general narrative interpretation, unsupported fields, reconciliation, calculations and contradictions are unprocessed. There is no missing-documentation inference. Exact source verification and parsed fields are checked by rules; this does not guarantee clinical interpretation.

IDs include source content and processing versions. Unchanged inputs yield the same evidence version and fact/passage IDs (preparation timestamp changes). Rules are rebuilt cheaply; Gemini model responses are reused from a content-keyed local cache. Uncached model outputs can vary. Offsets use Unicode code points as specified in `EVIDENCE_CONTRACT.md`.

## Integration

```python
from pathlib import Path
from backend.preparation import prepare_patient

bundle = prepare_patient(Path("data/patient-0000-0001/documents"), "0000-0001")
```

Your online teammate can load the serialized bundle using `EvidenceBundle.model_validate_json`. Keep the partial state visible and do not infer absent conditions from this structured-only slice. The functions `extract_medications(document, passages)` and `extract_structured(document, passages)` are reusable on original, already-normalized passages; preserve heading context. The reusable narrative extractor accepts selected passages with their heading context; online retrieval is not implemented here.
## Gemini free-tier workflow (default provider)

The preparation CLI loads the ignored project-root `.env.local` file. Set `GEMINI_API_KEY` there or in the process environment; existing environment settings take precedence. `.env.example` lists settings and contains no secrets. Do not commit `.env.local` or share it with the frontend.

```powershell
python -m backend.preparation --with-llm --output data/prepared/patient-0000-0001-gemini.json
```

The default is the small `gemini-3.5-flash-lite` model, explicitly selected rather than a moving latest alias. Change `GEMINI_MODEL` to select another model. There is no automatic switch to a paid model or provider. This sends document text to Google's Gemini API; use the supplied synthetic data for this hackathon workflow.

Quota controls:

- One serialized request at a time, with at least 12 seconds between starts (`LLM_MIN_INTERVAL_SECONDS`). This is a conservative local setting, not a guarantee that it matches your project's requests/token quotas.
- At most 32 network calls per client/run (`LLM_MAX_CALLS`), including retries. Cache hits do not consume this budget. This is not a persistent daily quota tracker.
- A 429 response schedules a retry using the provider's retry delay or a 60-second default. Two rate-limit responses, or a delay above 120 seconds, stop further network calls for the run. Remaining work becomes explicit processing gaps; retry later. Authentication/configuration failures also stop further calls.
- Parsed response envelopes are cached atomically under ignored `data/prepared/llm-cache`. Cache keys include model, prompt, full source payload, response schema and output limit. Unchanged documents reuse results; edits invalidate the affected requests. Cache entries are patient-derived data and must stay local/ignored. Cache reuse never bypasses exact-quote or source-support validation.
- Cache locking and pacing are per process: run one preparation process per project to avoid sharing the free quota unpredictably. The cache has no expiry; after a provider updates a model under the same ID, use a new `LLM_CACHE_DIR` for a fresh evaluation.

Extraction and source-support review remain separate calls. Switching to a smaller model does not reduce the number of requests by itself; caching does. Failed, truncated or invalid response envelopes are not cached. An envelope may contain rejected candidates; these are validated independently on every use, including cache hits. Source-invalid candidates are excluded by the extraction layer, with bounded repair attempts. No facts are truncated to a top-N list to save quota.

The command reports network calls, cache hits and token usage. Budget exhaustion or processing failures leave a valid partial bundle and explicit gaps; a zero process exit code is not proof of complete extraction. Review `processing_gaps` before downstream use. Gemini uses REST JSON Schema output, followed by the same local Pydantic validation as OpenAI.

Live smoke test (2026-10-30): the supplied radiology report produced eight accepted narrative facts and one explicit invalid-candidate gap. A repeated extraction made zero network calls and returned identical facts. The trial exposed incorrect `completed` status on non-event payloads; these are now rejected in code, even if a model reviewer would accept them. This one-document smoke test verifies integration and cache reuse, not corpus-wide recall or clinical accuracy. A subsequent full run exposed candidate date failures, incorrect status interpretations and omissions; the resulting review is saved under data/prepared/full-run-review.json. The changes below address those failure classes; a scored clinical evaluation remains separate.

## Optional OpenAI narrative extraction

Install `python -m pip install -r backend/requirements.txt`. The default command remains rules-only and sends no data to a model.

Set `OPENAI_API_KEY` locally and `OPENAI_MODEL` to a model available to your account supporting Responses structured outputs. Never commit or paste keys into chat. `.env.example` documents the settings; the preparation CLI loads `.env.local` without overriding existing process variables.

Run from the repository root:

```powershell
python -m backend.preparation --with-llm --provider openai --output data/prepared/patient-0000-0001-narrative.json
```

This explicitly sends document text to the official OpenAI API. Requests use `store=False`; that flag is not a claim of zero provider retention. Default concurrency is one document, configurable via `--concurrency` or `LLM_CONCURRENCY` (1–4). Model timeout defaults to 60 seconds per request and output limit to 12,000 tokens. No model is silently selected.

For each document, the pipeline runs the existing rules, then requests narrative candidate facts with exact passage quotes. Code resolves quotes to absolute offsets and validates the evidence schema. A separate model call checks whether the cited evidence supports every field. Only supported candidates are included, labelled `model_checked`, never clinically verified. Exact quote matching alone does not establish semantic truth. Reusing the same model for review can preserve correlated mistakes; human-labelled accuracy evaluation remains necessary.

Each stage permits at most one retry for transient/schema/evidence failures. Authentication failures and refusals do not retry. Failed or ambiguous extraction becomes a processing gap while existing rule facts survive. Model-declared coverage is not proof of exhaustive extraction or absence. Documents exceeding 40,000 passage characters are flagged rather than truncated. The reusable `extract_passages` function can also accept selected passages with their heading context for a future retrieval fallback.

The command reports calls, input/output/reasoning tokens, response model IDs, failures and elapsed time. Summed request elapsed time can exceed wall time due to concurrency. A typical successful section batch needs two calls; retries may raise this to four. Long documents need multiple batches. These counts are not cost estimates. Billing for transport failures may not be observable. Bundles remain partial: semantic duplicate reconciliation, calculations and contradiction detection are not implemented here. Rule extraction gaps remain visible even when a narrative fact appears to cover them.

Bundle versions include accepted fact content and gaps as well as source/configuration hashes, so different model outputs cannot share an evidence version. Source IDs and offsets still refer to normalized source documents. No challenge answers or frontend fixtures enter model prompts.

Validation: `python -m unittest discover -s tests -v`. Narrative tests use independent source text and mock responses, including a real SDK request through a mock HTTP transport. They do not establish real-model extraction quality. A live corpus evaluation requires locally configured credentials and a model.


## Candidate isolation and section extraction (v4 pipeline)

The provider still receives the full candidate JSON schema. Local parsing isolates individual candidate failures: one invalid ClinicalTime or payload no longer rejects all facts in the response. A single targeted repair request contains rejected items, error codes and any unreviewed passages; valid candidates are retained even if repair fails. Every retained fact still requires the separate support review. Initial rejection/repair gaps remain visible as an audit trail, so a gap count alone does not distinguish repaired items from outstanding omissions.

Long documents are packed into approximately 2,400-character batches on section boundaries. A large section can span batches; its heading is repeated, with the original passage ID and offsets. Individual paragraphs are never truncated to meet that target. Batch results are merged with duplicate IDs removed. This increases request count but reduces the tendency to summarize away conflicting details. The run request budget still applies; rerunning resumes cached requests.

Code validates explicit/contextual dates against valid dates in cited spans, retaining partial precision and preventing malformed-date repairs. Supported date forms include numeric German/ISO dates and German month names; unsupported formats are deferred rather than guessed. Document-date fallbacks remain labelled as fallbacks. Negated findings cannot be marked resolved without wording indicating resolution. Findings cannot be marked completed unless represented as an event. Unsupported optional dates/statuses are conservatively changed to unknown, with an audit note; the underlying claim still needs source-support review. Numeric measurements must appear in the cited text, preventing implicit model calculations such as converting a duration into an unsourced decimal number. These checks narrow known error classes; they are not general clinical truth verification.

A batch truncated by the provider output limit is retried once as smaller section batches (about 1,200 characters), preserving source IDs and offsets. Safety refusals and other blocked responses do not trigger this subdivision. Cache hits still use zero network calls.

After section extraction, a bounded omission-recovery pass checks uncited paragraphs containing clinical cues and missing explicitly dated admissions/discharges. It retries at most three small batches per document, preserving headings and original offsets. This is a heuristic, not full recall measurement; potential omissions remaining afterward are explicit processing gaps. All recovered candidates use the same quote, metadata and model support checks.

Regression run after these fixes (2026-10-30): all eight documents yielded narrative facts, versus six before. The bundle contains 263 facts (60 rule, 203 model), compared with 118 before. All 380 quote references match source offsets; date/status/numeric guard checks pass. The two previously empty documents now contain 95 and 21 model facts. Both admission dates, the valid narrative discharge date, right axillary finding, negative family history and breast lesion dimensions are retained. This is a regression review, not a precision/recall score. Typed laterality for quantitative imaging findings and consistent concept naming remain incomplete; the right-carotid claim is currently represented through its label and source context. See ignored data/prepared/fix-review.json for evidence IDs and remaining gaps.

## Deterministic normalization index

Run after preparation, without additional API calls:

```powershell
python -m backend.evidence.normalization --input data/prepared/patient-0000-0001-gemini-fixed.json --output data/prepared/patient-0000-0001-normalization.json
```

This writes a separate index and leaves the extraction bundle and model caches unchanged. The current regression bundle has 263 indexed facts, 156 mapped concepts, 43 assigned sides, and three ambiguous side annotations. The right-carotid 60% measurement receives a contextual right-side annotation with an expanded exact quote; the left-sided conclusion remains a separate fact. Unknown concepts and uncertain sides remain unresolved. This is conservative indexing, not a precision/recall evaluation or contradiction adjudication. The online developer can join entries on `fact_id` after validating the index against its source bundle.

## Presentation reconciliation

```powershell
python -m backend.evidence.reconciliation --input data/prepared/patient-0000-0001-gemini-fixed.json --output data/prepared/patient-0000-0001-reconciliation.json
```

No API calls are needed. This creates an auditable group index for display/ranking, preserving every original fact. Identical rule/model claims from identical evidence locations can share a representative; distinct dates, sides, events, units, methods and source locations remain separate. `presentation_facts(bundle, index)` supplies category-adjusted copies for downstream use; all citations and linked IDs resolve against the original bundle. See the evidence contract for the exact conservative matching rules.

The current 263-fact bundle produces 263 groups and one presentation category change; no broader semantic deduplication is claimed. On the saved four-case development run, reconciliation removes the repeated HbA1c display item and maps the recommended procedure to care_plans. Raw bundles and gold labels are untouched. Prompt v5 specifies the category policy for future extraction; its version changes request cache keys, so a new live extraction may require fresh requests. Validation here used saved v4 outputs and made zero model calls.

## Bounded contradiction detection and handoff

```powershell
python -m backend.evidence.contradictions --input data/prepared/patient-0000-0001-gemini-fixed.json --output data/prepared/patient-0000-0001-contradictions.json --enriched-output data/prepared/patient-0000-0001-with-contradictions.json
python -m backend.evidence.normalization --input data/prepared/patient-0000-0001-with-contradictions.json --output data/prepared/patient-0000-0001-with-contradictions-normalization.json
python -m backend.evidence.reconciliation --input data/prepared/patient-0000-0001-with-contradictions.json --output data/prepared/patient-0000-0001-with-contradictions-reconciliation.json
```

This sequence uses zero model calls and never overwrites the raw extraction bundle. Run detection from that raw bundle. The report references the raw source version; enrichment produces a new version. Rebuild downstream normalization/reconciliation indexes against the enriched version, as shown, rather than mixing indexes from different versions.

The current patient output preserves 263 source facts and adds three calculated BMI values. Two source blocks meet the conservative BMI inconsistency rule: recorded 29.4 versus calculated 26.99, and recorded 29 versus calculated 22.91. The third recorded BMI is consistent within the rule's tolerances. Conflicting admission dates and a finding/summary laterality difference are retained as two review candidates, excluded from the default display helper. The malformed discharge year remains an existing data-quality/extraction gap; it is not counted as an accepted contradiction.

The accepted count is two, below the hackathon target of at least five net contradictions. Do not add candidate counts or data-quality errors to claim that target is met. Further recall work requires source-grounded event linking, broader independent labels and candidate adjudication. The original scope gaps remain as an extraction audit trail; the bounded detector does not claim to complete all reconciliation/calculation/contradiction processing.

For integration, serve the enriched bundle's accepted contradictions and source-linked derived values; keep candidate contradictions separate from the ordinary clinical display. Preserve full group lineage when ranking presentation representatives. On the current machine, a five-run in-process detector check took about 76 ms median / 110 ms worst for this bundle. This excludes file IO and the rest of the query pipeline and is not the end-to-end load-time metric.

## Current integrated handoff

The patient-focused source audit recovered four omitted claims: blood-pressure checks, GP medication adjustment, repeated eye follow-up, and explicit causal attribution of the prior presenting symptoms. `backend.refinement` selects source passages by regex, runs the existing extraction and source-support review on those passages only, and preserves every original fact and processing gap. The current refinement used two Gemini calls, taking the bundle from 263 to 267 facts. It requires a raw extraction bundle; derived outputs must be rebuilt afterward.

```powershell
python -m backend.handoff --input data/prepared/patient-0000-0001-refined.json --output data/handoff/patient-0000-0001
python -m evaluation.patient_readiness --input data/handoff/patient-0000-0001/evidence.json --output data/evaluation/patient-readiness.json
```

The ignored handoff folder is the current integration artifact. `manifest.json` lists file hashes: validate all hashes before consuming a package, particularly if a rebuild was interrupted. `evidence.json` contains 267 source facts, three calculated BMI values, the signed weight change (-12 kg), and status-labelled contradictions. `source-evidence.json` is the immutable source for `contradiction-report.json`; `normalization.json`, `reconciliation.json` and `history.json` all refer to the final enriched evidence version. No frontend or API routes are changed by this build.

`backend/evidence/history.py` supplies measurement histories, latest day-orderable measurement selections, and the latest dated discharge medication list. The supplied patient defaults to an as-of date of 15 April 2016 from the source documents, not today's date. Earlier medication schedules remain available and are not combined with the newest list. Same-date measurement ties are retained. Unknown/partial dates and unanchored historical values are not silently ranked as new measurements. Document-date ordering is labelled explicitly and never asserted as the actual measurement date. The weight change uses the cited 78 kg and 66 kg endpoints; conflicting endpoint values prevent the calculation.

The published-scenario audit currently finds evidence groups for all 15 questions: 12 are evidence-ready, while three still need query-specific review. Two involve full-record absence judgments (renal function and completion of carotid follow-up); the third involves conflicting laterality evidence. This is evidence readiness, not 15/15 correct visible answers. The query layer must still retrieve, summarize and cite these records, preserve review flags, and establish absence from full-document coverage rather than a missing extracted fact. The patient-specific audit lives only under `evaluation/`; runtime modules do not import it.

## Completed patient source review

The scenario-critical facts were inspected against all eight supplied clinical documents. The ignored `data/evaluation/patient-source-review.json` contains source hashes, citations for the 15 scenario evidence groups, 15 numeric/schedule checks, five uncertainty findings, and scoped record-coverage notes. This is assistant source review, not independent clinician certification or a review of every ancillary extracted fact. Current medication strengths/schedules, allergy reactions, EF, HbA1c, receptor values, staging, recommendations and weight values agree with the inspected source text.

One chronology improvement was applied: seven main outpatient measurement facts now cite the introduction establishing the visit on 4 April 2016. Their time basis is contextual, while the letter date remains 5 April. The bounded rule requires one valid dated outpatient introduction and main visit measurement sections; ambiguous, invalid, future or historical contexts are excluded. Original facts remain in the previous raw bundle, and the change log preserves before/after metadata.

Current rebuild sequence:

```powershell
python -m backend.evidence.encounter_context --input data/prepared/patient-0000-0001-refined.json --output data/prepared/patient-0000-0001-reviewed.json
python -m backend.handoff --input data/prepared/patient-0000-0001-reviewed.json --output data/handoff/patient-0000-0001
```

The admission header says 10 April, while the narrative says admission to the ward on 12 April. Hospital versus ward admission is a possible explanation; neither date was overwritten or given an invented common event ID. The original radiology report describes left-sided narrowing; its discharge reproduction reverses the descriptive sides while retaining a left-sided conclusion. This strongly suggests a transcription disagreement, but the underlying event identity and true side are not silently adjudicated. Both detector entries remain candidates, with exact competing source passages in the review.

Additional review notes retain specimen collection on 11 April versus biopsy described under the 12 April ultrasound section, the invalid discharge year `20156` alongside the valid narrative date, and the unlabelled `0,5` in the historical Byetta row. These are not automatically counted as confirmed contradictions. No renal-function result or subsequent completed carotid follow-up was found in the eight supplied documents; referenced laboratory annexes are not included. These are scoped review conclusions, not new patient absence facts or a blanket runtime `searchComplete` flag.
