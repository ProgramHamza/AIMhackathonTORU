"""One attempt per call; bounded retries belong to the extraction orchestrator."""
import os
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Protocol

from pydantic import BaseModel, ValidationError


class ModelError(Exception):
    def __init__(self, code: str, retryable: bool):
        super().__init__(code)  # Never expose raw provider errors, prompts or secrets.
        self.code, self.retryable = code, retryable


class StructuredClient(Protocol):
    model: str
    def generate(self, *, system: str, payload: dict, response_type: type[BaseModel]) -> BaseModel: ...


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    failed_calls: int = 0
    elapsed_ms: int = 0
    response_models: set[str] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock, repr=False)

    def record(self, elapsed, response=None, failed=False):
        with self._lock:
            self.calls += 1
            self.failed_calls += int(failed)
            self.elapsed_ms += round(elapsed * 1000)
            if response:
                self.response_models.add(response.model)
                if response.usage:
                    self.input_tokens += response.usage.input_tokens
                    self.output_tokens += response.usage.output_tokens
                    self.reasoning_tokens += getattr(response.usage.output_tokens_details, "reasoning_tokens", 0) or 0

    def snapshot(self):
        with self._lock:
            return {key: getattr(self, key) for key in
                    ("calls", "input_tokens", "output_tokens", "reasoning_tokens", "failed_calls", "elapsed_ms")} | {"response_models": sorted(self.response_models)}


class OpenAIClient:
    def __init__(self, model: str, api_key: str | None = None, timeout: float = 60,
                 max_output_tokens: int = 12000, sdk_client=None):
        if not model.strip():
            raise ValueError("Set OPENAI_MODEL to an API model supporting structured outputs")
        if not 1 <= timeout <= 180 or not 256 <= max_output_tokens <= 32000:
            raise ValueError("Timeout must be 1–180 seconds; output limit 256–32000 tokens")
        self.model, self.max_output_tokens, self.timeout = model, max_output_tokens, timeout
        self.usage = Usage()
        if sdk_client is None:
            from openai import OpenAI
            key = api_key or os.environ.get("OPENAI_API_KEY")
            if not key:
                raise ValueError("Set OPENAI_API_KEY locally before enabling narrative extraction")
            # Fixed official endpoint; no accidental forwarding to an inherited proxy base URL.
            sdk_client = OpenAI(api_key=key, base_url="https://api.openai.com/v1", timeout=timeout, max_retries=0)
        self.sdk = sdk_client

    @classmethod
    def from_env(cls):
        return cls(model=os.environ.get("OPENAI_MODEL", ""), timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
                   max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "12000")))

    def generate(self, *, system, payload, response_type):
        import json
        from openai import APIConnectionError, APIStatusError, APITimeoutError
        started, response, failed = time.perf_counter(), None, True
        try:
            response = self.sdk.responses.parse(
                model=self.model, instructions=system,
                input=json.dumps(payload, ensure_ascii=False), text_format=response_type,
                max_output_tokens=self.max_output_tokens, store=False,
            )
            if response.status != "completed":
                raise ModelError("incomplete_response", True)
            if any(getattr(part, "type", "") == "refusal" for item in response.output
                   for part in getattr(item, "content", [])):
                raise ModelError("model_refusal", False)
            if response.output_parsed is None:
                raise ModelError("missing_structured_output", True)
            result = response_type.model_validate(response.output_parsed)
            failed = False
            return result
        except APITimeoutError:
            raise ModelError("provider_timeout", True) from None
        except APIConnectionError:
            raise ModelError("provider_connection", True) from None
        except APIStatusError as error:
            raise ModelError(f"provider_http_{error.status_code}", error.status_code in (408, 409, 429) or error.status_code >= 500) from None
        except ValidationError:
            raise ModelError("invalid_structured_output", True) from None
        finally:
            self.usage.record(time.perf_counter() - started, response, failed)

    def close(self):
        self.sdk.close()
