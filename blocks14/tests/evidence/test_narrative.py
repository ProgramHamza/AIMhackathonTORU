import json
import tempfile
import unittest
from pathlib import Path

from prep.ingestion.documents import load_document, segment_document
from prep.extraction.narrative import extract_passages, resolve_quote, candidate_fact
from prep.extraction.narrative_models import ExtractionResponse, Quote
from prep.llm.client import ModelError, OpenAIClient
from prep.preparation import prepare_patient


class FakeClient:
    model = "test-model"

    def __init__(self, verdict="supported", bad_quote=False, error=None, coverage=True):
        self.calls = 0
        self.verdict, self.bad_quote, self.error, self.coverage = verdict, bad_quote, error, coverage

    def generate(self, *, system, payload, response_type):
        self.calls += 1
        if self.error:
            raise self.error
        if response_type is ExtractionResponse:
            p = payload["passages"][0]
            return response_type.model_validate({"candidates": [{
                "category": "symptoms", "concept": "dyspnea", "label": "Dyspnoe",
                "value": {"kind": "assertion", "text": "Keine Dyspnoe"},
                "assertion": "negated", "clinical_status": "unknown", "subject": "patient",
                "clinical_time": {"precision": "unknown", "basis": "unknown"},
                "evidence": [{"passage_id": p["id"], "quote": "invented" if self.bad_quote else p["text"], "occurrence": 0}]
            }], "reviewed_passage_ids": [p["id"] for p in payload["passages"]] if self.coverage else [], "unresolved": []})
        return response_type.model_validate({"decisions": [{"candidate_id": c["candidate_id"],
            "verdict": self.verdict, "reason": "fixture"} for c in payload["candidates"]]})


class NarrativeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "source.json"
        self.path.write_text(json.dumps({"metadata": {"id": "independent", "date": "2024-07-09"},
                                         "text": "Keine Dyspnoe. Keine Dyspnoe."}), encoding="utf-8")
        self.doc = load_document(self.path)
        self.passages = segment_document(self.doc)

    def test_supported_fact_preserves_negation_and_evidence(self):
        client = FakeClient()
        result = extract_passages(self.doc, self.passages, client)
        self.assertEqual(client.calls, 2)
        self.assertEqual(len(result.facts), 1)
        f = result.facts[0]
        self.assertEqual(f.assertion, "negated")
        self.assertEqual(f.validation.semantic_check, "model_checked")
        self.assertEqual(f.validation.field_check, "not_checked")
        r = f.evidence[0]
        self.assertEqual(self.doc.normalized_text[r.start:r.end], r.quote)

    def test_invented_quote_is_retried_then_excluded(self):
        client = FakeClient(bad_quote=True)
        result = extract_passages(self.doc, self.passages, client)
        self.assertEqual(client.calls, 2)
        self.assertFalse(result.facts)
        self.assertTrue(result.processing_gaps)

    def test_unsupported_and_unclear_are_excluded(self):
        for verdict in ("unsupported", "unclear"):
            result = extract_passages(self.doc, self.passages, FakeClient(verdict=verdict))
            self.assertFalse(result.facts)
            self.assertTrue(result.processing_gaps)

    def test_timeout_retries_are_bounded(self):
        client = FakeClient(error=ModelError("provider_timeout", True))
        result = extract_passages(self.doc, self.passages, client)
        self.assertEqual(client.calls, 2)
        self.assertTrue(result.processing_gaps[0].retryable)

    def test_refusal_does_not_retry(self):
        client = FakeClient(error=ModelError("model_refusal", False))
        result = extract_passages(self.doc, self.passages, client)
        self.assertEqual(client.calls, 1)
        self.assertFalse(result.facts)

    def test_finding_cannot_be_marked_completed(self):
        c = FakeClient().generate(system="test", payload={"passages": [{"id": p.id, "text": p.text} for p in self.passages]}, response_type=ExtractionResponse).candidates[0]
        c.clinical_status = "completed"
        with self.assertRaisesRegex(ValueError, "completed_requires_event"):
            candidate_fact(c, {p.id: p for p in self.passages}, self.doc, "test-model")

    def test_incomplete_coverage_is_reported(self):
        result = extract_passages(self.doc, self.passages, FakeClient(coverage=False))
        self.assertTrue(any("coverage" in g.reason for g in result.processing_gaps))

    def test_repeated_quote_resolves_requested_occurrence(self):
        p = self.passages[0]
        ref = resolve_quote(Quote(passage_id=p.id, quote="Keine", occurrence=1), {p.id: p}, self.doc)
        self.assertEqual(ref.start, self.doc.normalized_text.rfind("Keine"))
        with self.assertRaises(ValueError):
            resolve_quote(Quote(passage_id="unknown", quote="Keine", occurrence=0), {p.id: p}, self.doc)

    def test_preparation_integrates_and_validates_bundle(self):
        bundle = prepare_patient(self.path.parent, "synthetic", "independent_synthetic", client=FakeClient())
        self.assertEqual(len(bundle.facts), 1)
        self.assertEqual(bundle.manifest.model_versions, ["test-model"])
        self.assertEqual(bundle.manifest.status, "partial")

    def test_invalid_review_coverage_fails_closed(self):
        class Incomplete(FakeClient):
            def generate(self, **kwargs):
                if kwargs["response_type"] is not ExtractionResponse:
                    self.calls += 1
                    return kwargs["response_type"](decisions=[])
                return super().generate(**kwargs)
        client = Incomplete()
        result = extract_passages(self.doc, self.passages, client)
        self.assertEqual(client.calls, 3)
        self.assertFalse(result.facts)

    def test_openai_sdk_request_and_schema_using_mock_transport(self):
        import httpx
        from openai import OpenAI
        requests = []
        def handler(request):
            body = json.loads(request.content)
            requests.append(body)
            return httpx.Response(200, json={"id": "resp_test", "object": "response", "created_at": 1,
                "model": "test-model", "status": "completed", "error": None, "incomplete_details": None,
                "instructions": None, "metadata": {}, "parallel_tool_calls": False, "tools": [],
                "tool_choice": "auto", "temperature": 1, "top_p": 1,
                "output": [{"type": "message", "id": "msg_test", "role": "assistant", "status": "completed",
                            "content": [{"type": "output_text", "annotations": [], "text": json.dumps({
                                "candidates": [], "reviewed_passage_ids": [], "unresolved": []})}]}],
                "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}})
        sdk = OpenAI(api_key="test-not-a-real-key", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        self.addCleanup(sdk.close)
        client = OpenAIClient("test-model", sdk_client=sdk)
        client.generate(system="test", payload={"text": "source"}, response_type=ExtractionResponse)
        self.assertFalse(requests[0]["store"])
        schema = requests[0]["text"]["format"]
        self.assertTrue(schema["strict"])
        self.assertNotIn('"oneOf"', json.dumps(schema))
        self.assertEqual(client.usage.snapshot()["input_tokens"], 10)


if __name__ == "__main__":
    unittest.main()
