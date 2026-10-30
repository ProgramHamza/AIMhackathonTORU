"""Quota-conscious Gemini REST adapter; no implicit provider/model fallback."""
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

import httpx
from pydantic import ValidationError

from prep.llm.client import ModelError, Usage


def gemini_schema(model):
    """Inline our acyclic definitions and express literal tags as enums."""
    schema = model.model_json_schema()
    definitions = schema.get("$defs", {})
    def convert(node):
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return convert(definitions[node["$ref"].split("/")[-1]])
        result = {k: convert(v) for k, v in node.items() if k not in ("$defs", "title", "default", "const")}
        if "const" in node:
            result["enum"] = [node["const"]]
        return result
    return convert(schema)


class GeminiClient:
    def __init__(self, api_key=None, model="gemini-3.5-flash-lite", *, cache_dir=Path("data/prepared/llm-cache"),
                 interval=12, max_calls=32, max_output_tokens=12000, timeout=60,
                 http_client=None, clock=time.monotonic, sleep=time.sleep):
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ValueError("Set GEMINI_API_KEY locally before enabling narrative extraction")
        if not re.fullmatch(r"[a-zA-Z0-9._-]+", model):
            raise ValueError("Invalid Gemini model ID")
        if interval < 0 or max_calls < 1 or not 256 <= max_output_tokens <= 32000 or not 1 <= timeout <= 180:
            raise ValueError("Invalid Gemini request limits")
        self.model, self.max_output_tokens = model, max_output_tokens
        self.interval, self.max_calls = interval, max_calls
        self.cache_dir = Path(cache_dir)
        self.usage = Usage()
        self.cache_hits = 0
        self.last_validation_errors = []
        self._clock, self._sleep = clock, sleep
        self._lock, self._next_request = Lock(), 0
        self._rate_errors, self._blocked = 0, False
        self._key = key
        self.http = http_client or httpx.Client(timeout=timeout)

    @classmethod
    def from_env(cls):
        return cls(model=os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
                   interval=float(os.environ.get("LLM_MIN_INTERVAL_SECONDS", "12")),
                   max_calls=int(os.environ.get("LLM_MAX_CALLS", "32")),
                   max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "12000")),
                   timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
                   cache_dir=Path(os.environ.get("LLM_CACHE_DIR", "data/prepared/llm-cache")))

    def generate(self, *, system, payload, response_type):
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": json.dumps(payload, ensure_ascii=False)}]}],
                "generationConfig": {"responseMimeType": "application/json",
                    "responseJsonSchema": gemini_schema(response_type),
                    "maxOutputTokens": self.max_output_tokens}}
        identity = json.dumps({"adapter": "gemini-rest-v2", "model": self.model, "body": body}, sort_keys=True)
        path = self.cache_dir / (hashlib.sha256(identity.encode()).hexdigest() + ".json")
        # Serialize calls within this process, including retries and cache writes.
        with self._lock:
            try:
                result = response_type.model_validate_json(path.read_text(encoding="utf-8"))
                self.cache_hits += 1
                return result
            except (OSError, ValueError):
                pass
            if self._blocked:
                raise ModelError("gemini_quota_paused", False)
            if self.usage.calls >= self.max_calls:
                raise ModelError("local_request_budget_exhausted", False)
            delay = max(0, self._next_request - self._clock())
            if delay:
                self._sleep(delay)
            start, usage_response, failed = self._clock(), None, True
            self._next_request = start + self.interval
            try:
                response = self.http.post("https://generativelanguage.googleapis.com/v1beta/models/" + self.model + ":generateContent",
                    headers={"x-goog-api-key": self._key}, json=body)
                if response.status_code == 429:
                    self._rate_errors += 1
                    try:
                        retry = float(response.headers.get("retry-after", "60"))
                        for detail in response.json().get("error", {}).get("details", []):
                            if "retryDelay" in detail:
                                retry = max(retry, float(detail["retryDelay"].rstrip("s")))
                    except (ValueError, TypeError):
                        retry = 60
                    # Do not burn the rest of the run's quota on repeated failures.
                    self._blocked = self._rate_errors >= 2 or retry > 120
                    self._next_request = self._clock() + min(max(retry, self.interval), 120)
                    raise ModelError("gemini_rate_limit", not self._blocked)
                if response.status_code >= 400:
                    if response.status_code in (400, 401, 403, 404):
                        self._blocked = True
                    raise ModelError(f"gemini_http_{response.status_code}", response.status_code >= 500)
                data = response.json()
                usage = data.get("usageMetadata", {})
                usage_response = SimpleNamespace(model=data.get("modelVersion", self.model), usage=SimpleNamespace(
                    input_tokens=usage.get("promptTokenCount", 0),
                    output_tokens=usage.get("candidatesTokenCount", 0) + usage.get("thoughtsTokenCount", 0),
                    output_tokens_details=SimpleNamespace(reasoning_tokens=usage.get("thoughtsTokenCount", 0))))
                candidates = data.get("candidates", [])
                if candidates and candidates[0].get("finishReason") == "MAX_TOKENS":
                    raise ModelError("gemini_output_truncated", False)
                if not candidates or candidates[0].get("finishReason") != "STOP":
                    raise ModelError("gemini_incomplete_or_blocked_output", False)
                content = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []) if not p.get("thought"))
                result = response_type.model_validate_json(content)
                failed = False
                # Cache only schema-valid successes. Source/semantic checks still run on cache hits.
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                temp_path = None
                try:
                    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.cache_dir, delete=False) as handle:
                        temp_path = Path(handle.name)
                        handle.write(result.model_dump_json(warnings=False))
                    os.replace(temp_path, path)
                finally:
                    if temp_path and temp_path.exists():
                        temp_path.unlink()
                return result
            except httpx.TimeoutException:
                raise ModelError("provider_timeout", True) from None
            except httpx.RequestError:
                raise ModelError("provider_connection", True) from None
            except ValidationError as error:
                self.last_validation_errors = [{"location": list(e["loc"]), "type": e["type"]} for e in error.errors()]
                locations = sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()})[:4]
                raise ModelError("invalid_structured_output: " + ", ".join(locations), True) from None
            except ValueError:
                raise ModelError("invalid_structured_output", True) from None
            finally:
                self.usage.record(self._clock() - start, usage_response, failed)

    def close(self):
        self.http.close()
