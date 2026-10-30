"""Every Gemini call tries each key in .env until one works (fake HTTP, no network)."""
import io
import json
import urllib.error

import pytest

import app.embeddings as emb
import app.llm_client as llm


class FakeHTTP:
    """Answers per key: an HTTP error code, or 200 with a valid body."""

    def __init__(self, by_key: dict[str, int], body: dict):
        self.by_key, self.body, self.seen = by_key, body, []

    def __call__(self, req, timeout=None):
        key = req.headers.get("X-goog-api-key")
        self.seen.append(key)
        code = self.by_key[key]
        if code != 200:
            detail = {403: "PERMISSION_DENIED", 429: "RESOURCE_EXHAUSTED PerDay",
                      400: "API key not valid"}.get(code, "")
            raise urllib.error.HTTPError(req.full_url, code, "err", {}, io.BytesIO(detail.encode()))
        return io.BytesIO(json.dumps(self.body).encode())



@pytest.mark.parametrize("bad", [403, 429, 400])
def test_generation_tries_every_key(monkeypatch, bad):
    fake = FakeHTTP({"k1": bad, "k2": bad, "k3": 200},
                    {"candidates": [{"content": {"parts": [{"text": json.dumps({"ok": "yes"})}]}}]})
    monkeypatch.setattr(llm.urllib.request, "urlopen", fake)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    c = llm.GeminiClient("m", api_key="k1")
    c.api_keys, c.models = ["k1", "k2", "k3"], ["m"]
    res = c.complete_json("sys", "user", {"type": "object"}, timeout=30)
    assert res.data == {"ok": "yes"}
    assert fake.seen[:3] == ["k1", "k2", "k3"]
    assert c.api_key == "k3"  # the working key is used first next time


@pytest.mark.parametrize("bad", [403, 429])
def test_embeddings_try_every_key(monkeypatch, tmp_path, bad):
    fake = FakeHTTP({"k1": bad, "k2": 200}, {"embeddings": [{"values": [1.0, 0.0]}]})
    monkeypatch.setattr(emb.urllib.request, "urlopen", fake)
    monkeypatch.setattr(emb.time, "sleep", lambda s: None)
    e = emb.GeminiEmbedder(api_key="k1", dim=2)
    e.api_keys = ["k1", "k2"]
    e.cache.data, e.cache.path = {}, tmp_path / "c.json"
    out = e.embed(["hello"], "RETRIEVAL_QUERY")
    assert out.shape == (1, 2) and fake.seen == ["k1", "k2"]


def test_all_keys_refused_raises(monkeypatch, tmp_path):
    fake = FakeHTTP({"k1": 403, "k2": 403}, {})
    monkeypatch.setattr(emb.urllib.request, "urlopen", fake)
    monkeypatch.setattr(emb.time, "sleep", lambda s: None)
    e = emb.GeminiEmbedder(api_key="k1", dim=2)
    e.api_keys = ["k1", "k2"]
    e.cache.data, e.cache.path = {}, tmp_path / "c.json"
    with pytest.raises(emb.EmbeddingError):
        e.embed(["hello"], "RETRIEVAL_QUERY", wait_on_quota=True)
    assert fake.seen == ["k1", "k2"]  # no waiting: a refused key does not recover in a minute
