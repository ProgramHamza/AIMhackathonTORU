import json
import tempfile
import unittest
from pathlib import Path

import httpx

from prep.extraction.narrative_models import ExtractionResponse
from prep.llm.client import ModelError
from prep.llm.gemini import GeminiClient, gemini_schema


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 100.0
        self.waits = []
        self.requests = []

    def sleep(self, delay):
        self.waits.append(delay)
        self.now += delay

    def client(self, handler=None, **kwargs):
        def transport(request):
            self.requests.append(json.loads(request.content))
            if handler:
                return handler(request)
            return httpx.Response(200, json={"modelVersion": "test-snapshot", "candidates": [{
                "finishReason": "STOP", "content": {"parts": [{"text": json.dumps({
                    "candidates": [], "reviewed_passage_ids": [], "unresolved": []})}]}}],
                "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})
        c = GeminiClient(api_key="test-key", cache_dir=Path(self.temp.name), clock=lambda: self.now,
                         sleep=self.sleep, http_client=httpx.Client(transport=httpx.MockTransport(transport)), **kwargs)
        self.addCleanup(c.close)
        return c

    def generate(self, c, payload=None, system="extract"):
        return c.generate(system=system, payload=payload or {"document": "one"}, response_type=ExtractionResponse)

    def test_cache_reused_across_clients_and_source_changes_invalidate(self):
        c = self.client()
        self.generate(c)
        second = self.client()
        self.generate(second)
        self.assertEqual(second.usage.calls, 0)
        self.assertEqual(second.cache_hits, 1)
        self.generate(second, {"document": "changed"})
        self.generate(second, system="changed prompt")
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(second.usage.input_tokens, 20)

    def test_model_and_output_config_invalidate_cache(self):
        self.generate(self.client())
        self.generate(self.client(model="different-model"))
        self.generate(self.client(max_output_tokens=1000))
        self.assertEqual(len(self.requests), 3)

    def test_request_pacing_and_local_budget(self):
        c = self.client(max_calls=2)
        self.generate(c)
        self.generate(c, {"document": "two"})
        self.assertEqual(self.waits, [12])
        with self.assertRaisesRegex(ModelError, "local_request_budget"):
            self.generate(c, {"document": "three"})
        self.generate(c)  # Cache remains available after budget exhaustion.
        self.assertEqual(len(self.requests), 2)

    def test_rate_limit_backoff_and_circuit_breaker(self):
        c = self.client(lambda r: httpx.Response(429, headers={"retry-after": "25"}, json={"error": {}}))
        for retryable in (True, False):
            with self.assertRaises(ModelError) as caught:
                self.generate(c)
            self.assertEqual(caught.exception.retryable, retryable)
        with self.assertRaisesRegex(ModelError, "quota_paused"):
            self.generate(c)
        self.assertEqual(self.waits, [25])
        self.assertEqual(len(self.requests), 2)

    def test_auth_failure_stops_run_and_never_caches(self):
        c = self.client(lambda r: httpx.Response(403, json={"error": {"message": "secret details"}}))
        with self.assertRaisesRegex(ModelError, "gemini_http_403"):
            self.generate(c)
        with self.assertRaisesRegex(ModelError, "quota_paused"):
            self.generate(c)
        self.assertFalse(list(Path(self.temp.name).glob("*.json")))

    def test_truncated_output_is_rejected_not_cached(self):
        c = self.client(lambda r: httpx.Response(200, json={"candidates": [{"finishReason": "MAX_TOKENS"}]}))
        with self.assertRaisesRegex(ModelError, "truncated"):
            self.generate(c)
        self.assertFalse(list(Path(self.temp.name).glob("*.json")))

    def test_corrupt_cache_is_refetched(self):
        c = self.client()
        self.generate(c)
        next(Path(self.temp.name).glob("*.json")).write_text("invalid", encoding="utf-8")
        self.generate(c)
        self.assertEqual(c.usage.calls, 2)
        self.assertEqual(self.requests[0]["generationConfig"]["responseMimeType"], "application/json")

    def test_schema_inlines_references_and_preserves_literal_tags(self):
        schema = gemini_schema(ExtractionResponse)
        serialized = json.dumps(schema)
        self.assertNotIn('"$ref"', serialized)
        self.assertNotIn('"const"', serialized)
        values = schema["properties"]["candidates"]["items"]["properties"]["value"]["anyOf"]
        self.assertEqual(values[0]["properties"]["kind"]["enum"], ["medication"])

    def test_invalid_model_output_rejected_with_safe_feedback(self):
        c = self.client(lambda r: httpx.Response(200, json={"candidates": [{"finishReason": "STOP",
            "content": {"parts": [{"text": '{"candidates": "private content"}'}]}}]}))
        with self.assertRaises(ModelError) as error:
            self.generate(c)
        self.assertIn("invalid_structured_output", error.exception.code)
        self.assertNotIn("private content", error.exception.code)
        self.assertFalse(list(Path(self.temp.name).glob("*.json")))


if __name__ == "__main__":
    unittest.main()
