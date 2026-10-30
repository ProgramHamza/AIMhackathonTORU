"""Block 3a: provider-agnostic LLM client.

Every block that calls a model goes through `complete_json`, so the provider is config.

Configuration (environment variables, or backend/.env; see .env.example):
  ANTHROPIC_API_KEY   enables Claude (cloud)
  GEMINI_API_KEY      enables Google Gemini (cloud); a plain API_KEY entry also works
  LLM_PROVIDER        auto (default) | anthropic | gemini | ollama
                      auto = each cloud provider that has a key (Claude, then Gemini),
                             then local Ollama as the last fallback.
  LLM_MODEL           overrides the Claude model (default claude-haiku-5-5, a small fast model)
  GEMINI_MODEL        overrides the Gemini model (default gemini-3.5-flash)
  OLLAMA_MODEL        local model (default mistral:latest)
  OLLAMA_NUM_CTX      local context window in tokens (default 2048, fits ~4.3 GB RAM)
  OLLAMA_HOST         default http://127.0.0.1:11434
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .outbound import assert_https, is_local, outbound_text

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
DEFAULT_OLLAMA_MODEL = "mistral:latest"
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
# Tried in order when the first model is overloaded, unavailable or not enabled for the key.
GEMINI_BACKUP_MODELS = ["gemini-flash-lite-latest", "gemini-flash-latest", "gemini-3.8-flash"]
GEMINI_ATTEMPT_TIMEOUT = 20.0


def load_env_file(path: Path = ENV_FILE) -> None:
    """Read KEY=VALUE lines from backend/.env. Real environment variables win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def gemini_keys() -> list[str]:
    """All Gemini keys, in order: GEMINI_API_KEY or API_KEY, then GEMINI_API_KEY_2, _3, ...
    Free-tier limits are per key, so requests rotate to the next key on a rate limit."""
    names = (["GEMINI_API_KEY", "API_KEY"] + [f"GEMINI_API_KEY_{i}" for i in range(2, 10)]
             + [f"GEMINI_API_KEY{i}" for i in range(2, 10)])
    # any other Gemini/Google key name in .env counts too (GOOGLE_API_KEY, GEMINI_KEY_B, API_KEY_3, ...)
    extra = sorted(n for n in os.environ if _GEMINI_KEY_NAME.match(n) and n not in names)
    keys = []
    for n in names + extra:
        v = (os.environ.get(n) or "").strip()
        if v and v not in keys:
            keys.append(v)
    return keys


_GEMINI_KEY_NAME = re.compile(r"^(GEMINI|GOOGLE)[A-Z0-9_]*KEY[A-Z0-9_]*$|^API_KEY[_0-9]*$")
_KEY_PROBLEM_HINTS = ("API_KEY_INVALID", "API key not valid", "billing", "FAILED_PRECONDITION",
                      "PERMISSION_DENIED", "RESOURCE_EXHAUSTED", "quota")


def is_key_problem(code: int, detail: str) -> bool:
    """True when another API key may succeed: quota or rate limit, billing required,
    key invalid or not allowed to use this model."""
    if code in (401, 403, 429):
        return True
    return code == 400 and any(h.lower() in detail.lower() for h in _KEY_PROBLEM_HINTS)


def gemini_key() -> str | None:
    """The first Gemini key (GEMINI_API_KEY, or a plain API_KEY entry in .env)."""
    keys = gemini_keys()
    return keys[0] if keys else None


def render_user(user, context_tokens: int) -> str:
    """`user` may be a string or a callable that builds the message for a context size."""
    return user(context_tokens) if callable(user) else user


class LLMError(RuntimeError):
    """The model call failed or returned something unusable."""


@dataclass
class LLMResult:
    data: dict
    ms: float
    model: str


class LLMClient(Protocol):
    provider: str
    model: str
    context_tokens: int

    def complete_json(self, system: str, user, schema: dict, timeout: float) -> LLMResult: ...


class AnthropicClient:
    provider = "anthropic"
    context_tokens = 1_000_000

    def __init__(self, model: str | None = None, effort: str = "low") -> None:
        import anthropic  # optional dependency

        self._anthropic = anthropic
        self.client = anthropic.Anthropic()
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self.effort = effort

    def complete_json(self, system: str, user, schema: dict, timeout: float) -> LLMResult:
        t = time.perf_counter()
        try:
            response = self.client.with_options(timeout=timeout, max_retries=1).messages.create(
                model=self.model,
                max_tokens=4096,
                system=outbound_text(system, "anthropic"),
                messages=[{"role": "user", "content": outbound_text(render_user(user, self.context_tokens), "anthropic")}],
                output_config={"effort": self.effort,
                               "format": {"type": "json_schema", "schema": schema}},
            )
        except self._anthropic.APIError as e:
            raise LLMError(f"anthropic: {type(e).__name__}: {e}") from e
        if response.stop_reason == "refusal":
            raise LLMError("anthropic: request refused")
        if response.stop_reason == "max_tokens":
            raise LLMError("anthropic: output truncated")
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"anthropic: invalid JSON: {e}") from e
        return LLMResult(data, (time.perf_counter() - t) * 1000, self.model)


class OllamaClient:
    provider = "ollama"

    def __init__(self, model: str | None = None, host: str | None = None,
                 num_ctx: int | None = None, num_predict: int = 700) -> None:
        self.model = model or os.environ.get("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
        self.host = (host or os.environ.get("OLLAMA_HOST") or "http://127.0.0.1:11434").rstrip("/")
        self.context_tokens = num_ctx or int(os.environ.get("OLLAMA_NUM_CTX", "2048"))
        self.num_predict = num_predict

    def complete_json(self, system: str, user, schema: dict, timeout: float) -> LLMResult:
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system if is_local(self.host) else outbound_text(system, "ollama")},
                         {"role": "user", "content": render_user(user, self.context_tokens) if is_local(self.host)
                          else outbound_text(render_user(user, self.context_tokens), "ollama")}],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0, "num_ctx": self.context_tokens,
                        "num_predict": self.num_predict},
        }).encode("utf-8")
        t = time.perf_counter()
        deadline = t + timeout
        errors = []
        for _ in range(2):  # one retry: local servers fail transiently (model loading, memory)
            remaining = deadline - time.perf_counter()
            if remaining <= 1:
                break
            req = urllib.request.Request(f"{self.host}/api/chat", data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=remaining) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                errors.append(f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:200]}")
                continue
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                errors.append(f"{type(e).__name__}: {e}")
                continue
            data = _parse_json_object((payload.get("message") or {}).get("content", ""))
            if data is not None:
                return LLMResult(data, (time.perf_counter() - t) * 1000, self.model)
            errors.append(f"unusable JSON (done_reason={payload.get('done_reason')})")
        raise LLMError("ollama: " + " | ".join(errors or ["timeout"]))


def _parse_json_object(text: str) -> dict | None:
    """Parse the first JSON object in text; tolerate code fences and trailing text."""
    start = text.find("{")
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


class GeminiClient:
    """Google Gemini over REST (no SDK dependency). The key goes in a header, never the URL."""

    provider = "gemini"
    context_tokens = 1_000_000
    URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    RETRY_STATUS = {429, 500, 502, 503, 504}

    def __init__(self, model: str | None = None, api_key: str | None = None,
                 attempt_timeout: float = GEMINI_ATTEMPT_TIMEOUT) -> None:
        self.attempt_timeout = attempt_timeout
        first = model or os.environ.get("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        self.models = [first] + [m for m in GEMINI_BACKUP_MODELS if m != first]
        self.model = first
        self.api_keys = [api_key] if api_key else gemini_keys()
        if not self.api_keys:
            raise LLMError("gemini: GEMINI_API_KEY (or API_KEY) is not set")
        self._key_i = 0
        self._variant = 0  # index into _configs that the API accepted last time

    @property
    def api_key(self) -> str:
        return self.api_keys[self._key_i]

    def complete_json(self, system: str, user, schema: dict, timeout: float) -> LLMResult:
        """Overloaded or rate-limited models are retried once, then the next model is tried."""
        deadline = time.perf_counter() + timeout
        errors = []
        for model in self.models:
            for attempt in range(1 + len(self.api_keys)):
                remaining = deadline - time.perf_counter()
                if remaining <= 1:
                    raise LLMError("gemini: " + " | ".join(errors or ["timeout"]))
                try:
                    result = self._call(model, system, user, schema,
                                        min(remaining, self.attempt_timeout))
                    self.models.remove(model)  # remember the model that works
                    self.models.insert(0, model)
                    self.model = model
                    return result
                except _Retryable as e:
                    errors.append(f"{model}: {e}")
                    if not e.same_model:
                        break
                    if attempt == 0:
                        time.sleep(min(1.0, max(0.0, deadline - time.perf_counter() - 1)))
        raise LLMError("gemini: " + " | ".join(errors))

    @staticmethod
    def _configs(schema: dict) -> list[dict]:
        """Request variants, newest API features first; older endpoints reject some fields."""
        return [
            {"responseMimeType": "application/json", "responseJsonSchema": schema,
             "temperature": 0, "thinkingConfig": {"thinkingLevel": "low"}},
            {"responseMimeType": "application/json", "responseJsonSchema": schema, "temperature": 0},
            {"responseMimeType": "application/json", "responseSchema": _openapi_schema(schema),
             "temperature": 0},
        ]

    def _call(self, model: str, system: str, user, schema: dict, timeout: float) -> LLMResult:
        assert_https(self.URL)
        text = outbound_text(render_user(user, self.context_tokens), "gemini")
        system = outbound_text(system, "gemini")
        configs = self._configs(schema)
        t = time.perf_counter()
        last = None
        for v in range(self._variant, len(configs)):
            body = json.dumps({
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": text}]}],
                "generationConfig": configs[v],
            }).encode("utf-8")
            req = urllib.request.Request(self.URL.format(model=model), data=body, headers={
                "Content-Type": "application/json", "x-goog-api-key": self.api_key})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                self._variant = v
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                last = f"HTTP {e.code}: {detail[:160]}"
                if is_key_problem(e.code, detail) and len(self.api_keys) > 1:
                    # quota, billing or permission problem of this key: the next key, same model
                    self._key_i = (self._key_i + 1) % len(self.api_keys)
                    raise _Retryable(last) from e
                if e.code in self.RETRY_STATUS:
                    raise _Retryable(last) from e
                if e.code in (403, 404):  # model not enabled for this key or retired
                    raise _Retryable(last, same_model=False) from e
                if e.code != 400:  # only a bad request means "try a simpler variant"
                    raise LLMError(f"gemini: {last}") from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise _Retryable(f"{type(e).__name__}: {e}") from e
        else:
            raise LLMError(f"gemini: {last}")
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            out = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            data = json.loads(out)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            reason = (payload.get("candidates") or [{}])[0].get("finishReason", "unknown")
            raise LLMError(f"gemini: unusable response (finishReason={reason}): {e}") from e
        return LLMResult(data, (time.perf_counter() - t) * 1000, model)


class _Retryable(LLMError):
    """Overload, rate limit or network error: worth retrying or trying another model."""

    def __init__(self, message: str, same_model: bool = True) -> None:
        super().__init__(message)
        self.same_model = same_model


def _openapi_schema(schema):
    """Gemini's older responseSchema is an OpenAPI subset without additionalProperties."""
    if isinstance(schema, dict):
        return {k: _openapi_schema(v) for k, v in schema.items() if k != "additionalProperties"}
    if isinstance(schema, list):
        return [_openapi_schema(v) for v in schema]
    return schema


class FallbackClient:
    """Try clients in order; the first one that succeeds answers."""

    provider = "fallback"

    def __init__(self, *clients: LLMClient) -> None:
        self.clients = clients
        self.model = " -> ".join(c.model for c in clients)
        self.context_tokens = max(c.context_tokens for c in clients)

    def complete_json(self, system: str, user, schema: dict, timeout: float) -> LLMResult:
        errors = []
        for c in self.clients:
            try:
                return c.complete_json(system, user, schema, timeout)
            except LLMError as e:
                errors.append(str(e))
        raise LLMError(" | ".join(errors))


def make_client(provider: str | None = None, model: str | None = None) -> LLMClient:
    """auto: every cloud provider that has a key (Claude, then Gemini), then local Ollama."""
    load_env_file()
    provider = provider or os.environ.get("LLM_PROVIDER", "auto")
    if provider == "ollama":
        return OllamaClient(model)
    if provider == "anthropic":
        return AnthropicClient(model or os.environ.get("LLM_MODEL") or None)
    if provider == "gemini":
        return GeminiClient(model)
    if provider == "auto":
        chain: list[LLMClient] = []
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                chain.append(AnthropicClient(os.environ.get("LLM_MODEL") or None))
            except ImportError:
                pass  # anthropic package missing
        if gemini_key():
            chain.append(GeminiClient())
        chain.append(OllamaClient())
        return chain[0] if len(chain) == 1 else FallbackClient(*chain)
    raise ValueError(f"unknown LLM provider {provider!r}")
