"""Embedding and reranking clients (cloud, REST, no SDK), with a disk cache.

Every text is sent at most once per model: results are cached in .cache/ by a hash of
(model, task, text), so rebuilding the index or repeating a query costs no API calls.

  GEMINI_API_KEY (or API_KEY)  Gemini embeddings, batched up to 100 texts per request
  JINA_API_KEY                 Jina multilingual reranker (used offline only)
  EMBED_MODEL                  default gemini-embedding-2
  RERANK_MODEL                 default jina-reranker-v2-base-multilingual
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

from . import vault
from .llm_client import gemini_key, gemini_keys, is_key_problem, load_env_file
from .outbound import assert_https, outbound_text, outbound_texts

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
EMBED_DIM = 768
EMBED_BATCH = 90          # the free tier counts each text as one request, ~100 per minute
QUOTA_WAIT_S = 62
RETRY_STATUS = {429, 500, 502, 503, 504}


class EmbeddingError(RuntimeError):
    pass


def _key(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()


class _JsonCache:
    def __init__(self, name: str) -> None:
        self.path = CACHE_DIR / name
        self.data: dict = {}
        self.dirty = False
        if self.path.exists():
            try:
                self.data = json.loads(vault.read_text(self.path))
            except (json.JSONDecodeError, vault.VaultError):
                self.data = {}

    def save(self) -> None:
        if self.dirty:
            vault.write_text(self.path, json.dumps(self.data, separators=(",", ":")))
            self.dirty = False


class QuotaError(EmbeddingError):
    """This key cannot serve the request now: quota used up, billing needed or key refused.
    per_minute: a short wait may help; otherwise only another key will."""

    def __init__(self, message: str, per_minute: bool = False) -> None:
        super().__init__(message)
        self.per_minute = per_minute


def _post(url: str, body: dict, headers: dict, timeout: float, attempts: int = 3) -> dict:
    assert_https(url)
    data = json.dumps(body).encode("utf-8")
    last = ""
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")
            last = f"HTTP {e.code}: {detail[:160]}"
            if is_key_problem(e.code, detail):
                # per-minute or daily quota, billing required, invalid key: try the next key
                raise QuotaError(last, per_minute="PerMinute" in detail) from e
            if e.code not in RETRY_STATUS:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"{type(e).__name__}: {e}"
        if attempt + 1 < attempts:
            time.sleep(1.5 * (attempt + 1))
    raise EmbeddingError(last)


class GeminiEmbedder:
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"

    def __init__(self, model: str | None = None, api_key: str | None = None, dim: int = EMBED_DIM) -> None:
        load_env_file()
        self.model = model or os.environ.get("EMBED_MODEL") or "gemini-embedding-2"
        # all keys (API_KEY / GEMINI_API_KEY, GEMINI_API_KEY_2, ...): the free-tier quota is per key
        self.api_keys = [api_key] if api_key else gemini_keys()
        self.api_key = self.api_keys[0] if self.api_keys else None  # without a key only cached texts work
        self._key_i = 0
        self.dim = dim
        self.calls = 0
        self.cache = _JsonCache(f"embeddings-{self.model}-{dim}.json")

    def embed(self, texts: list[str], task: str, timeout: float = 30.0,
              wait_on_quota: bool = False) -> np.ndarray:
        """task: RETRIEVAL_DOCUMENT or RETRIEVAL_QUERY. Returns L2-normalised rows.

        wait_on_quota: offline builds wait for the next minute when the free-tier
        per-minute quota is used up; online queries fail fast instead."""
        texts = outbound_texts(texts, "embed")
        keys = [_key(self.model, task, t) for t in texts]
        todo = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in self.cache.data]
        if todo and not self.api_key:
            raise EmbeddingError(f"GEMINI_API_KEY (or API_KEY) is not set and {len(todo)} texts are not cached")
        for i in range(0, len(todo), EMBED_BATCH):
            chunk = todo[i:i + EMBED_BATCH]
            body = {"requests": [{"model": f"models/{self.model}", "content": {"parts": [{"text": t}]},
                                  "taskType": task, "outputDimensionality": self.dim} for _, t in chunk]}
            tries = 0
            any_per_minute = False
            while True:
                try:
                    out = _post(self.URL.format(model=self.model), body,
                                {"x-goog-api-key": self.api_keys[self._key_i]}, timeout)
                    break
                except QuotaError as e:
                    tries += 1
                    any_per_minute = any_per_minute or e.per_minute
                    self._key_i = (self._key_i + 1) % len(self.api_keys)  # every key gets a turn
                    if tries % len(self.api_keys):
                        continue
                    # all keys failed in this round: wait for the next minute only if waiting can help
                    if not (wait_on_quota and any_per_minute) or tries >= 6 * len(self.api_keys):
                        self.cache.save()
                        raise
                    any_per_minute = False
                    time.sleep(QUOTA_WAIT_S)
            self.calls += 1
            for (k, _), e in zip(chunk, out["embeddings"]):
                self.cache.data[k] = [round(x, 6) for x in e["values"]]
            self.cache.dirty = True
            self.cache.save()  # resumable: a later failure keeps what was fetched
        m = np.array([self.cache.data[k] for k in keys], dtype=np.float32).reshape(len(keys), -1)
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(norms == 0, 1, norms)


class JinaEmbedder:
    """Jina multilingual embeddings (the text-matching task suits short phrases)."""

    URL = "https://api.jina.ai/v1/embeddings"
    BATCH = 256

    def __init__(self, model: str | None = None, api_key: str | None = None, dim: int = 1024) -> None:
        load_env_file()
        self.model = model or os.environ.get("JINA_EMBED_MODEL") or "jina-embeddings-v3"
        self.api_key = api_key or os.environ.get("JINA_API_KEY")
        if not self.api_key:
            raise EmbeddingError("JINA_API_KEY is not set")
        self.dim = dim
        self.calls = 0
        self.cache = _JsonCache(f"embeddings-{self.model}-{dim}.json")

    def embed(self, texts: list[str], task: str = "text-matching", timeout: float = 30.0,
              wait_on_quota: bool = False) -> np.ndarray:
        jina_task = ("text-matching" if task in ("SEMANTIC_SIMILARITY", "text-matching") else
                     "retrieval.query" if task == "RETRIEVAL_QUERY" else "retrieval.passage")
        texts = outbound_texts(texts, "embed")
        keys = [_key(self.model, jina_task, t) for t in texts]
        todo = [(k, t) for k, t in dict(zip(keys, texts)).items() if k not in self.cache.data]
        for i in range(0, len(todo), self.BATCH):
            chunk = todo[i:i + self.BATCH]
            body = {"model": self.model, "task": jina_task, "dimensions": self.dim,
                    "input": [t for _, t in chunk]}
            out = _post(self.URL, body, {"Authorization": f"Bearer {self.api_key}",
                                         "Accept": "application/json"}, timeout)
            self.calls += 1
            for row in out["data"]:
                self.cache.data[chunk[row["index"]][0]] = [round(x, 6) for x in row["embedding"]]
            self.cache.dirty = True
            self.cache.save()
        m = np.array([self.cache.data[k] for k in keys], dtype=np.float32).reshape(len(keys), -1)
        norms = np.linalg.norm(m, axis=1, keepdims=True)
        return m / np.where(norms == 0, 1, norms)


def make_embedder(provider: str | None = None):
    """The configured embedder for short phrases: EMBED_PROVIDER=jina|gemini."""
    load_env_file()
    provider = provider or os.environ.get("EMBED_PROVIDER", "jina")
    return JinaEmbedder() if provider == "jina" else GeminiEmbedder()


class JinaReranker:
    URL = "https://api.jina.ai/v1/rerank"

    def __init__(self, model: str | None = None, api_key: str | None = None) -> None:
        load_env_file()
        self.model = model or os.environ.get("RERANK_MODEL") or "jina-reranker-v2-base-multilingual"
        self.api_key = api_key or os.environ.get("JINA_API_KEY")
        if not self.api_key:
            raise EmbeddingError("JINA_API_KEY is not set")
        self.calls = 0
        self.cache = _JsonCache(f"rerank-{self.model}.json")

    def scores(self, query: str, documents: list[str], timeout: float = 30.0) -> list[float]:
        query = outbound_text(query, "rerank")
        documents = outbound_texts(documents, "rerank")
        keys = [_key(self.model, query, d) for d in documents]
        missing = [i for i, k in enumerate(keys) if k not in self.cache.data]
        if missing:
            body = {"model": self.model, "query": query, "documents": [documents[i] for i in missing],
                    "return_documents": False}
            out = _post(self.URL, body, {"Authorization": f"Bearer {self.api_key}",
                                         "Accept": "application/json"}, timeout)
            self.calls += 1
            for r in out["results"]:
                self.cache.data[keys[missing[r["index"]]]] = round(float(r["relevance_score"]), 6)
            self.cache.dirty = True
            self.cache.save()
        return [self.cache.data[k] for k in keys]
