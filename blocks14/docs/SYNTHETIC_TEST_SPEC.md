# Synthetic evidence evaluation specification v1

## Objective

Measure source-grounded extraction and temporal/contradiction accuracy independently of the five known answers. The official README currently specifies new situations for the same patient. Additional synthetic records are robustness tests, not a claim about a changed jury dataset.

The larger target corpus below remains a plan. An initial 12-case development seed and strict evaluation runner are now implemented (see current implementation below). They do not replace the planned held-out and longitudinal evaluations.

## Corpus layout and isolation

| Suite | Scope | Use |
|---|---|---|
| Official | Existing eight documents and five situations | Private end-to-end benchmark; never runtime answer lookup |
| Focused | 40 short independent German cases | 30 development cases; 10 held out |
| Longitudinal | Three independent synthetic patients, 8–12 documents each | Two development records; one held out |
| Scale (later) | 25/50/100 distinct-event documents | Measure ingestion and query degradation separately |

Independent corpus inputs: `tests/fixtures/independent/inputs/`. Gold labels: `tests/fixtures/independent/gold/`. A runtime reader receives only the inputs directory. Larger generated material and any IBM-derived artifacts stay under ignored `data/evaluation/`. The example in `contracts/examples/` is independently authored and contains no copied IBM narrative.

Do not commit modified IBM letters as “synthetic” fixtures. Audit provenance and generation inputs before publishing any independent corpus. Hold out complete patient records, not random paragraphs from the same patient. Keep a held-out split frozen and do not tune against repeated failures from it; promote a case to development only by explicitly replacing the held-out case and recording the change.

## Creation process

1. Author a hidden fact ledger first: patient identity, events, dates, medications, changes, negations, planned actions and intentional inconsistencies.
2. Define expected extraction claims and query needs independently of prose generation.
3. Generate German letters from the ledger with varied structure, dates and abbreviations. Keep exact source evidence and clinically interpretable wording; avoid invented treatment advice.
4. Review each resulting document against the ledger. If prose omits a fact, gold must not assume it is documented. Reject generation drift rather than silently adjusting all labels to fit.
5. Annotate evidence spans against normalized text. Review intentional contradictions and negative controls separately. Use another reviewer, ideally a clinician for ambiguous semantics; a second model is assistance, not independent ground truth.
6. Freeze source hashes, labels, split and generator/reviewer metadata. Evaluate the extractor without exposing the ledger or expected results.

## Focused cases: 40 required tests

Each case specifies expected facts, forbidden interpretations and evidence spans. Paired variants should have different wording and values, not copied identifiers.

| IDs | Count | Required behavior |
|---|---:|---|
| MED-01–06 | 6 | Four-slot schedule; half-tablet; weekly medication; PRN; discontinued drug; same drug changed at a later encounter |
| NEG-01–05 | 5 | Explicit absence; suspected condition; diagnostic question is not a diagnosis; resolved condition; family condition is not patient's |
| TIME-01–05 | 5 | Day date; month-only; relative follow-up; document date differs from event date; invalid date preserved as unresolved |
| MEAS-01–05 | 5 | Decimal comma; unit conversion; distinct BP components; incompatible units rejected; small measurement difference is not a conflict |
| ALL-01–03 | 3 | Substance plus reactions; explicit no-known-allergy statement; no allergy section does not create a negative fact |
| EVENT-01–04 | 4 | Recommended investigation; performed investigation; later follow-up completion; absent completion documentation |
| CONFLICT-01–05 | 5 | Same-event laterality conflict; same-event date conflict; BMI mismatch; unrelated events do not conflict; copied conflict counts once |
| SOURCE-01–04 | 4 | Repeated quote uses correct location; Unicode and entities; multiline table context; malformed/unsupported extraction becomes a gap |
| SCOPE-01–03 | 3 | Unexpected clinical concept preserved; incidental header excluded; irrelevant instructions embedded in a source treated as data |

Reserve one case from each of MED, NEG, TIME, MEAS, ALL, EVENT, CONFLICT and SCOPE plus two SOURCE cases for the held-out split. Record exact assigned IDs before model tuning.

## Longitudinal record design

**Patient A (development):** cardiovascular/diabetes history, three dated medication lists, measurements, a recommendation and later completion. Include one explicit laterality disagreement and a numeric inconsistency; include legitimate dose and weight changes as negative controls.

**Patient B (development):** surgical investigation with outpatient letter, imaging, pathology, discharge and follow-up. Include planned versus completed procedures, tumour attributes, one conflicting event date and one missing requested laboratory result. Do not duplicate the official patient's clinical story.

**Patient C (held out):** a different clinical trajectory and document wording; select categories covered by the schema plus one unexpected concept. Include family/social history, ambiguous time, repeated source text and genuine and apparent conflicts. Freeze gold before running the implementation.

For each record create at least four role/task requests, including an unseen combination, a historical-date question, a request for absent information and a request whose answer requires multiple documents. No expected answer may be inferred from the hidden ledger unless the supplied documents support it.

## Gold annotation format

Store a separate JSON object with `case_id`, `split`, `source_hashes`, `review_status`, `expected_facts`, `expected_derived_values`, `expected_contradictions`, `forbidden_claims`, `questions` and `expected_processing_gaps`.

An expected fact records category, concept, structured value, assertion, clinical status, date precision/basis and allowed supporting spans. Permit alternate legitimate citations explicitly. Match claims by normalized meaning/fields rather than generated IDs. Do not require one exact segmentation if several valid spans retain the necessary context.

Contradiction labels identify the claims and same-event rationale, all source spans, and whether the case is a positive or negative control. Query labels distinguish documented, conflicting, not documented and incomplete. Calculation labels include inputs, formula and tolerance.

## Metrics and release gates

| Layer | Measurement | Initial gate |
|---|---|---|
| Contract | Schema, IDs, offsets, quote equality, references | All deterministic tests pass |
| Extraction | Fact precision and recall, separately by category | Report both; investigate every unsupported displayed claim |
| Semantics | Negation, status, laterality, dates and units | All critical focused cases correct before integration freeze |
| Provenance | Correct source supports the claim, not merely exists | 100% on displayed official facts |
| Calculations | Correct inputs, conversions and result | All calculation tests pass |
| Contradictions | True positives, false positives, false negatives, deduplicated | Official net score >=5; zero false alarms on focused negative controls |
| Coverage | Missing vs failed processing vs conflicting | No processing failure labelled not documented |
| Official answers | Visible supported answers | 15/15 |
| Timing | Cold preparation; warm and uncached query; cache-hit query | Report separately; official complete response <10s |

A schema-valid output is not an extraction success. A correct value with a wrong source fails provenance. An LLM judge can assist adjudication but does not replace gold checks and human review. Report sample sizes and held-out results even when worse than development results.

Run official prompts at least five times per configuration and report median and worst observed query latency, output tokens, reasoning usage if available, model versions, retries, preparation cost and request cost. Do not call a partial or timed-out response complete to satisfy timing. Scale tests must add distinct events and distractors, not merely repeat identical letters.

## Implementation order

1. Contract tests and independent example (included now).
2. Implement normalizer and medication slice; add MED/SOURCE gold fixtures alongside them.
3. Add deterministic fields and their MEAS/ALL/TIME cases.
4. Add narrative extraction with NEG/EVENT/SCOPE cases.
5. Add calculations and CONFLICT cases.
6. Generate/review the longitudinal development records.
7. Run frozen held-out records, official end-to-end benchmark and scale tests.

The input corpus and expected labels are different artifacts. Do not make expected labels an extraction dependency or load `cases/expected.json` in runtime modules.

## Current implementation (2026-10-30)

`evaluation/build_development.py` is an independently authored fixed ledger and prose seed, not a model-driven random generator. It creates 12 `DEV-*` cases with 17 expected facts, source hashes, exact Unicode evidence spans, and forbidden interpretations under `tests/fixtures/independent/`. The seed does not read official patient letters, expected official answers, or extractor output. These are development cases, authored after the extractor existed; they are not a blind benchmark. Labels explicitly require independent review and are not clinician-certified. No held-out cases have been created or evaluated yet.

Cases cover measurements, split blood pressure, positive and negative allergies, missing allergy information, a four-slot medication schedule with a half tablet, dated encounters, negation and suspicion, recommendation versus completion, family versus patient, repeated identical quotes at distinct offsets, Unicode, and an embedded instruction that must not become a clinical fact. These cover part of the planned 40-case suite; longitudinal changes, calculations and contradictions remain untested by this seed.

Run the zero-API baseline:

```powershell
python -m evaluation.score --output data/evaluation/development-rules-baseline.json
```

Run bounded live extraction separately, passing only source inputs to the extraction pipeline:

```powershell
python -m evaluation.run_inputs --case DEV-NEG-01 --case DEV-EVENT-01 --case DEV-FAMILY-01 --case DEV-SCOPE-01 --max-calls 12 --output data/evaluation/gemini-development
python -m evaluation.score --case DEV-NEG-01 --case DEV-EVENT-01 --case DEV-FAMILY-01 --case DEV-SCOPE-01 --predictions data/evaluation/gemini-development --output data/evaluation/development-gemini-narrative.json
python -m evaluation.score --case DEV-NEG-01 --case DEV-EVENT-01 --case DEV-FAMILY-01 --case DEV-SCOPE-01 --output data/evaluation/development-rules-narrative.json
```

The live runner uses the locally configured Gemini model, shared request cache and pacing, with one case at a time and a total request ceiling. It records usage and elapsed time. It never opens gold files. The scorer receives saved predictions separately and fails if cases are missing or source hashes do not match. Do not compare the four-case model score directly with the twelve-case baseline: use the matching four-case baseline command above.

Scoring uses maximum one-to-one matching over explicitly annotated fields, optional accepted concept keys, and required source spans. Extra predictions cannot inflate recall; repeated identical text must point at the correct occurrence. Every required span must be covered by a citation. Lists match exactly; there is no LLM judge, fuzzy synonym inference, unit conversion or numerical tolerance in v1. Unannotated fields are not graded. This is stricter than semantic equivalence and narrower than full clinical correctness. Extra facts and failed matches are review items, not automatically hallucinations. Gold may need independently reviewed alternate representations before a semantic precision claim is appropriate.

Reports include matches, missed labels, unmatched prediction IDs/reasons, category counts, forbidden-claim violations, processing gaps, evidence versions and gold hashes. Empty denominators produce null rather than misleading perfect scores. A pipeline partial status is retained and never interpreted as absence of documentation. The initial rules-only baseline matched 13/17 facts and all 13 predictions matched the annotated fields/spans; the four misses are narrative claims outside the rules' scope. Scores on this small development seed do not estimate performance on unseen hackathon documents.

### First bounded live comparison

On the four-case narrative/instruction subset, rules matched 1/5 labelled claims with one prediction. Gemini preparation matched 4/5 with seven predictions: strict precision 4/7 and recall 4/5. There were zero forbidden-claim violations. This used `gemini-3.5-flash-lite`, eight network calls, 8,720 input tokens and 2,480 output tokens, with no failed calls. Wall time was 85.38 seconds including free-tier pacing; summed request time was 14.64 seconds. These are offline preparation timings, not online query latency or dollar-cost estimates.

Review found a category mismatch (recommended colonoscopy represented as procedures instead of care_plans), a valid separate not-yet-performed statement omitted from the gold ledger, and a repeated HbA1c fact from rule and model extraction. Thus 4/7 strict precision is not a claim that three predictions are clinically false. Original gold and scores remain unchanged. `data/evaluation/development-review.json` records these review items; independently review and version any future gold revision. The next implementation work is a clear category policy and conservative duplicate reconciliation, before contradiction detection.

### Reconciliation regression

The category policy and conservative presentation reconciliation are now implemented. To compare the presentation view with the unchanged saved raw predictions and gold labels:

```powershell
python -m evaluation.score --case DEV-NEG-01 --case DEV-EVENT-01 --case DEV-FAMILY-01 --case DEV-SCOPE-01 --predictions data/evaluation/gemini-development --reconcile --output data/evaluation/development-gemini-reconciled.json
```

The presentation view matches 5/5 existing labels with six predictions (strict precision 5/6, recall 5/5). One HbA1c duplicate is grouped; the recommended procedure receives the care_plans presentation category. The additional negated not-yet-performed procedure remains an unmatched prediction pending independent gold review. No labels were changed to obtain this result, and there were no new API calls. This is a development regression after tuning on observed failures, not held-out improvement or clinical accuracy validation. New prompt v5 behavior has not been live-tested by this cached-output comparison.

### Bounded contradiction development suite

`evaluation/build_contradiction_development.py` defines a separate frozen seed of 12 source-level cases under `tests/fixtures/contradictions/inputs/` and separate gold labels under `gold/`. The labels specify accepted findings, review candidates, source hashes and required supporting quotes. They are AI-authored development labels, not independently reviewed clinical truth. They cover large BMI discrepancies, correct/rounded BMI, distinct historical dates, separated source blocks, copied text, multiple ambiguous weights, unit conversion, conflicting encounter dates, planned-versus-completed admission, separate documents and an invalid date.

```powershell
python -m evaluation.score_contradictions --output data/evaluation/contradiction-development.json
```

The runner prepares only input documents with deterministic rules, then evaluates detector findings against separately loaded gold. It checks kind, status and citation support, and reports missing/unexpected findings and accepted false alarms. Candidate matches are separate from accepted contradictions. All 12 current development cases pass, including zero accepted false alarms on the negative controls. This does not evaluate general narrative extraction, cross-document event linking or held-out contradiction recall.

Additional detector tests exercise explicit same-event date conflicts, side ambiguity, bilateral findings, differing dates/sites/statuses/subjects, source-unit support, preservation of citations, copied-claim deduplication, tamper/stale rejection and versioned handoff. The patient review lives in ignored `data/evaluation/contradiction-review.json`; the two rule-accepted BMI inconsistencies and two review candidates are not a claimed official net score of five. The suite is deliberately conservative while broader semantic adjudication remains unimplemented.
