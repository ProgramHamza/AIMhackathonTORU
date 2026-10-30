"""The one gate every byte must pass before it leaves the device for a cloud model.

Rules enforced here, not in each caller:
  1. The text is de-identified (deidentify.Deidentifier.scrub).
  2. If any direct identifier is still present, the call is refused (PHILeakError) and
     nothing is sent. Better no answer than a leak.
  3. Only HTTPS endpoints are allowed.
Local models (Ollama on this machine) are exempt from 1-2 because nothing leaves the device.

Usage: call `configure(Deidentifier.for_patient(...))` once at startup. Each provider
client calls `outbound_text(text, "gemini")` on everything it is about to send.
`stats()` reports what was replaced, for the README and the demo.
"""
from __future__ import annotations

import threading
from collections import Counter
from urllib.parse import urlparse

from .deidentify import DEFAULT, Deidentifier

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


class PHILeakError(RuntimeError):
    """Refused to send: the text still contains a direct patient identifier."""


class _State:
    deid: Deidentifier = DEFAULT
    enabled: bool = True
    counts: Counter = Counter()
    refused: int = 0
    calls: Counter = Counter()
    chars: int = 0
    lock = threading.Lock()


_state = _State()


def configure(deid: Deidentifier | None = None, enabled: bool = True) -> None:
    with _state.lock:
        _state.deid = deid or DEFAULT
        _state.enabled = enabled


def is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in LOCAL_HOSTS


def assert_https(url: str) -> None:
    if not is_local(url) and urlparse(url).scheme != "https":
        raise PHILeakError(f"refusing non-HTTPS endpoint: {url}")


def outbound_text(text: str, context: str = "cloud") -> str:
    """De-identify `text`; raise PHILeakError if an identifier would still leave."""
    if not _state.enabled or not text:
        return text
    result = _state.deid.scrub(text)
    hits = _state.deid.leaks(result.text)
    with _state.lock:
        _state.calls[context] += 1
        _state.chars += len(result.text)
        _state.counts.update(result.replaced)
        if hits:
            _state.refused += 1
    if hits:
        raise PHILeakError(f"{context}: refusing to send text that still contains identifiers: "
                           + ", ".join(sorted(set(hits))[:3]))
    return result.text


def outbound_texts(texts: list[str], context: str = "cloud") -> list[str]:
    return [outbound_text(t, context) for t in texts]


def stats() -> dict:
    with _state.lock:
        return {"replaced": dict(_state.counts), "calls": dict(_state.calls), "chars_sent": _state.chars,
                "refused": _state.refused, "enabled": _state.enabled}


def reset_stats() -> None:
    with _state.lock:
        _state.counts = Counter()
        _state.calls = Counter()
        _state.refused = 0
        _state.chars = 0
