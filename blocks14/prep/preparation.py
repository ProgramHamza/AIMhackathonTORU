"""Deterministic extraction of medication tables and supported labelled fields."""
import argparse
import json
import os
import tempfile
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from prep.evidence.schema import EvidenceBundle, ProcessingGap
from prep.extraction.medication import VERSION as MEDICATION_VERSION, extract_medications
from prep.extraction.structured import VERSION as STRUCTURED_VERSION, extract_structured
from prep.ingestion.documents import NORMALIZATION_VERSION, SEGMENTATION_VERSION, digest, load_document, segment_document

PIPELINE_VERSION = "narrative-slice-v4"


def prepare_patient(source_directory: Path, patient_id: str, dataset_kind="official_synthetic", *, client=None, concurrency=2):
    if not 1 <= concurrency <= 4:
        raise ValueError("Concurrency must be between 1 and 4")
    source_directory = Path(source_directory)
    paths = sorted(source_directory.glob("*.json"))
    if not paths:
        raise ValueError("Source directory contains no document JSON files")
    documents = [load_document(path) for path in paths]
    passages, facts, gaps = [], [], []
    for doc in documents:
        doc_passages = segment_document(doc)
        passages.extend(doc_passages)
        extracted, failed = extract_medications(doc, doc_passages)
        facts.extend(extracted)
        gaps.extend(failed)
        extracted, failed = extract_structured(doc, doc_passages)
        facts.extend(extracted)
        gaps.extend(failed)
        gaps.append(ProcessingGap(id="scope-" + doc.id, stage="extraction", document_ids=[doc.id],
                                  reason=("Narrative extraction enabled; reconciliation, calculations and contradictions remain unprocessed." if client else "Structured rules only: general narrative interpretation, unsupported fields, reconciliation, calculations and contradictions remain unprocessed."),
                                  retryable=False))
    config = {"pipeline": PIPELINE_VERSION, "normalization": NORMALIZATION_VERSION,
              "segmentation": SEGMENTATION_VERSION, "medication": MEDICATION_VERSION, "structured": STRUCTURED_VERSION}
    if client is not None:
        from prep.extraction.narrative import extract_passages, VERSION as NARRATIVE_VERSION
        from prep.extraction.prompts import VERSION as PROMPT_VERSION
        from prep.extraction.chunks import section_batches, VERSION as CHUNK_VERSION
        from prep.extraction.source_checks import VERSION as CHECK_VERSION
        from prep.extraction.coverage import uncovered_passages, with_headings, VERSION as COVERAGE_VERSION
        config.update(narrative=NARRATIVE_VERSION, prompt=PROMPT_VERSION, model=client.model,
                      max_output_tokens=getattr(client, "max_output_tokens", None), chunking=CHUNK_VERSION, source_checks=CHECK_VERSION, coverage=COVERAGE_VERSION)
        def process(doc):
            selected = [p for p in passages if p.document_id == doc.id]
            results = []
            for batch in section_batches(selected):
                ids = {p.id for p in batch}
                known = [f for f in facts if any(r.passage_id in ids for r in f.evidence)]
                result = extract_passages(doc, batch, client, existing_facts=known)
                # A truncated batch contributes no facts; try smaller coherent batches once.
                smaller = section_batches(batch, limit=1200)
                if not result.facts and len(smaller) > 1 and any(g.reason == 'gemini_output_truncated' for g in result.processing_gaps):
                    for sub_batch in smaller:
                        sub_ids = {p.id for p in sub_batch}
                        sub_known = [f for f in known if any(r.passage_id in sub_ids for r in f.evidence)]
                        results.append(extract_passages(doc, sub_batch, client, existing_facts=sub_known))
                else:
                    results.append(result)
            doc_ids = {p.id for p in selected}
            known = [f for f in facts if any(r.passage_id in doc_ids for r in f.evidence)] + [f for r in results for f in r.facts]
            uncovered = uncovered_passages(selected, known)
            # One bounded recovery pass; do not loop until the heuristic is satisfied.
            recovery = section_batches(with_headings(uncovered, selected), limit=1200)
            for batch in recovery[:3]:
                ids = {p.id for p in batch}
                prior = [f for f in known if any(r.passage_id in ids for r in f.evidence)]
                result = extract_passages(doc, batch, client, existing_facts=prior,
                    requested_concepts=['Recover uncited clinical claims and every explicitly dated admission/discharge. Preserve conflicting sides independently; use assertion text and laterality for sided imaging measurements. Do not let a different conclusion override the quoted finding.'])
                results.append(result)
                known.extend(result.facts)
            remaining = uncovered_passages(selected, known)
            if remaining:
                from prep.extraction.narrative import ExtractionResult
                results.append(ExtractionResult(processing_gaps=[ProcessingGap(
                    id='coverage-' + doc.id, stage='extraction', document_ids=[doc.id],
                    passage_ids=[p.id for p in remaining], reason='Potential uncaptured clinical claims remain after bounded recovery', retryable=False)]))
            return results
        # Collect before mutating facts; preserve source order regardless of completion order.
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            results = list(pool.map(process, documents))
        for document_results in results:
            for result in document_results:
                facts.extend(result.facts)
                gaps.extend(result.processing_gaps)
        facts = list({f.id: f for f in facts}.values())
        gaps = list({g.id: g for g in gaps}.values())
    config_hash = digest(json.dumps(config, sort_keys=True).encode())
    version = digest(json.dumps({"config": config_hash, "patient": patient_id,
                                "sources": [(d.id, d.source_sha256) for d in documents],
                                "facts": [f.model_dump(mode="json") for f in facts],
                                "gaps": [g.model_dump(mode="json") for g in gaps]}, sort_keys=True).encode())
    return EvidenceBundle(manifest={"bundle_id": f"{patient_id}:{version[:16]}", "patient_id": patient_id,
                                    "dataset_kind": dataset_kind, "evidence_version": version,
                                    "prepared_at": datetime.now(timezone.utc), "pipeline_version": PIPELINE_VERSION,
                                    "configuration_hash": config_hash, "status": "partial",
                                    "model_versions": [client.model] if client else []},
                          documents=documents, passages=passages, facts=facts, processing_gaps=gaps)


def write_bundle(bundle, destination: Path):
    """Atomic replacement; no partial JSON if interrupted."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(bundle.model_dump_json(indent=2) + "\n")
        os.replace(temp_path, destination)
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()


def main():
    from dotenv import load_dotenv
    # Explicit project file; existing process environment settings take precedence.
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.local", override=False)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/patient-0000-0001/documents"))
    parser.add_argument("--patient-id", default="0000-0001")
    parser.add_argument("--output", type=Path, default=Path("data/prepared/patient-0000-0001.json"))
    parser.add_argument("--dataset-kind", choices=["official_synthetic", "independent_synthetic"], default="official_synthetic")
    parser.add_argument("--with-llm", action="store_true", help="Send source documents to the configured provider")
    parser.add_argument("--provider", choices=["gemini", "openai"], default=os.environ.get("LLM_PROVIDER", "gemini"))
    parser.add_argument("--concurrency", type=int, default=int(os.environ.get("LLM_CONCURRENCY", "1")))
    args = parser.parse_args()
    started = time.perf_counter()
    client = None
    if args.with_llm:
        from prep.llm.client import OpenAIClient
        from prep.llm.gemini import GeminiClient
        try:
            client = (GeminiClient if args.provider == "gemini" else OpenAIClient).from_env()
        except ValueError as error:
            parser.error(str(error))
    try:
        bundle = prepare_patient(args.source, args.patient_id, args.dataset_kind, client=client, concurrency=args.concurrency)
    finally:
        if client:
            client.close()
    write_bundle(bundle, args.output)
    print(json.dumps({"status": bundle.manifest.status, "documents": len(bundle.documents), "passages": len(bundle.passages),
                      "facts": len(bundle.facts), "facts_by_category": dict(Counter(f.category for f in bundle.facts)), "processing_gaps": len(bundle.processing_gaps),
                      "elapsed_ms": round((time.perf_counter() - started) * 1000), "output": str(args.output),
                      "llm_calls": client.usage.calls if client else 0,
                      "cache_hits": getattr(client, "cache_hits", 0),
                      "usage": client.usage.snapshot() if client else None}, indent=2))


if __name__ == "__main__":
    main()
