"""The outbound gate: every cloud client scrubs, refuses leaks and insists on HTTPS."""
import io
import json
import urllib.error

import numpy as np
import pytest

import app.embeddings as emb
import app.llm_client as llm
from app import outbound
from app.deidentify import Deidentifier

PATIENT = {"id": "9999-0042", "name": "Erika Beispiel", "dateOfBirth": "1961-07-23"}
SECRET = "Erika Beispiel, geb. 23.07.1961, NN_9999-0042, Aspirin 100mg 1 0 0 0"


@pytest.fixture(autouse=True)
def configured():
    outbound.configure(Deidentifier.for_patient(PATIENT, []))
    outbound.reset_stats()
    yield
    outbound.configure(None)


class Capture:
    """Fake urlopen: records the request body and answers with a valid payload."""

    def __init__(self, payload):
        self.payload, self.bodies, self.urls = payload, [], []

    def __call__(self, req, timeout=None):
        self.urls.append(req.full_url)
        self.bodies.append(req.data.decode("utf-8"))
        return io.BytesIO(json.dumps(self.payload).encode())


def assert_clean(body: str):
    for s in ("Erika", "Beispiel", "23.07.1961", "NN_9999", "9999-0042"):
        assert s not in body, s
    assert "Aspirin 100mg" in body  # clinical content still travels


def test_gemini_generation_is_scrubbed(monkeypatch):
    cap = Capture({"candidates": [{"content": {"parts": [{"text": "{\"ok\": \"yes\"}"}]}}]})
    monkeypatch.setattr(llm.urllib.request, "urlopen", cap)
    c = llm.GeminiClient("m", api_key="k")
    c.models = ["m"]
    c.complete_json("System mentions Erika Beispiel", SECRET, {"type": "object"}, 10)
    assert_clean(cap.bodies[0])
    assert outbound.stats()["replaced"]["NAME"] >= 1 and outbound.stats()["refused"] == 0


def test_gemini_embeddings_are_scrubbed_and_cached_scrubbed(monkeypatch, tmp_path):
    cap = Capture({"embeddings": [{"values": [1.0, 0.0]}]})
    monkeypatch.setattr(emb.urllib.request, "urlopen", cap)
    e = emb.GeminiEmbedder(api_key="k", dim=2)
    e.cache.data, e.cache.path = {}, tmp_path / "c.json"
    e.embed([SECRET], "RETRIEVAL_DOCUMENT")
    assert_clean(cap.bodies[0])
    assert all("Erika" not in k for k in e.cache.data)


def test_jina_reranker_is_scrubbed(monkeypatch):
    cap = Capture({"results": [{"index": 0, "relevance_score": 0.5}]})
    monkeypatch.setattr(emb.urllib.request, "urlopen", cap)
    r = emb.JinaReranker(api_key="k")
    r.cache.data = {}
    r.scores("allergies of Erika Beispiel", [SECRET])
    assert_clean(cap.bodies[0])


def test_anthropic_is_scrubbed(monkeypatch):
    pytest.importorskip("anthropic")
    sent = {}

    class FakeMessages:
        def create(self, **kw):
            sent.update(kw)
            raise llm.LLMError("stop here")

    class FakeClient:
        def with_options(self, **kw):
            return self

        messages = FakeMessages()

    c = llm.AnthropicClient.__new__(llm.AnthropicClient)
    c._anthropic, c.client, c.model, c.effort = llm.AnthropicClient.__mro__[0].__dict__ and __import__("anthropic"), FakeClient(), "m", "low"
    with pytest.raises(Exception):
        c.complete_json("sys Erika", SECRET, {"type": "object"}, 10)
    assert_clean(json.dumps(sent, default=str))


def test_gate_refuses_when_scrub_cannot_remove_an_identifier():
    class Broken(Deidentifier):
        def scrub(self, text):  # simulates a pattern the scrubber misses
            from app.deidentify import ScrubResult
            return ScrubResult(text)

    outbound.configure(Broken(names=["Erika Beispiel"]))
    with pytest.raises(outbound.PHILeakError):
        outbound.outbound_text("Erika Beispiel takes aspirin", "test")
    assert outbound.stats()["refused"] == 1


def test_refused_call_sends_nothing(monkeypatch):
    class Broken(Deidentifier):
        def scrub(self, text):
            from app.deidentify import ScrubResult
            return ScrubResult(text)

    outbound.configure(Broken(names=["Erika Beispiel"]))
    cap = Capture({})
    monkeypatch.setattr(llm.urllib.request, "urlopen", cap)
    c = llm.GeminiClient("m", api_key="k")
    c.models = ["m"]
    with pytest.raises(outbound.PHILeakError):
        c.complete_json("sys", "Erika Beispiel", {"type": "object"}, 10)
    assert cap.bodies == []


def test_https_required_except_localhost():
    outbound.assert_https("https://generativelanguage.googleapis.com/x")
    outbound.assert_https("http://127.0.0.1:11434/api/chat")
    outbound.assert_https("http://localhost:11434/api/chat")
    with pytest.raises(outbound.PHILeakError):
        outbound.assert_https("http://example.com/api")


def test_local_ollama_is_not_scrubbed(monkeypatch):
    cap = Capture({"message": {"content": "{\"ok\": 1}"}})
    monkeypatch.setattr(llm.urllib.request, "urlopen", cap)
    c = llm.OllamaClient("m", host="http://127.0.0.1:11434")
    c.complete_json("sys", SECRET, {"type": "object"}, 10)
    assert "Erika Beispiel" in cap.bodies[0]  # stays on the device, so the model may see it


def test_remote_ollama_is_scrubbed(monkeypatch):
    cap = Capture({"message": {"content": "{\"ok\": 1}"}})
    monkeypatch.setattr(llm.urllib.request, "urlopen", cap)
    c = llm.OllamaClient("m", host="https://ollama.example.org")
    c.complete_json("sys", SECRET, {"type": "object"}, 10)
    assert_clean(cap.bodies[0])
