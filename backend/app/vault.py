"""Encryption at rest for everything the app caches about a patient.

All caches (remarker index, embeddings, summaries, prompt-analysis answers) go through
`write_bytes` / `read_bytes`, so a copied .cache folder is useless without the key.

Cipher: AES-256-GCM (authenticated; a modified file is detected, not silently read).
It runs on the CPU's AES instructions: megabytes per millisecond, so it costs nothing
noticeable next to a network call.

Key: DATA_KEY in the environment or backend/.env (32 bytes, base64 or hex). Without it a
random key is created once in backend/.cache/.data_key (owner-only permissions where the
OS supports them). Losing the key only loses caches; they are rebuilt from the documents.

File layout: b"CSDV1" + 12-byte nonce + ciphertext (GCM tag included). Files that do not
start with the magic bytes are read as plain legacy files and encrypted on the next save.

ENCRYPT_AT_REST=0 writes plain files (local debugging only).
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import os
import secrets
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"CSDV1"
NONCE_LEN = 12
KEY_LEN = 32
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
KEY_FILE = CACHE_DIR / ".data_key"


class VaultError(RuntimeError):
    """Wrong key, tampered file or unusable key material."""


_key_cache: bytes | None = None


def _parse_key(raw: str) -> bytes:
    raw = raw.strip()
    for decode in (lambda s: base64.b64decode(s, validate=True), binascii.unhexlify,
                   lambda s: base64.urlsafe_b64decode(s)):
        try:
            key = decode(raw)
        except (ValueError, binascii.Error):
            continue
        if len(key) == KEY_LEN:
            return key
    raise VaultError("DATA_KEY must be 32 bytes, base64 or hex encoded")


def data_key() -> bytes:
    """The encryption key: DATA_KEY, else the key file, created on first use."""
    global _key_cache
    if _key_cache is not None:
        return _key_cache
    raw = os.environ.get("DATA_KEY")
    if raw:
        _key_cache = _parse_key(raw)
        return _key_cache
    if KEY_FILE.exists():
        _key_cache = _parse_key(KEY_FILE.read_text(encoding="ascii"))
        return _key_cache
    key = secrets.token_bytes(KEY_LEN)
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(base64.b64encode(key).decode("ascii"), encoding="ascii")
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass  # Windows: ACLs apply instead
    _key_cache = key
    return key


def reset_key_cache() -> None:
    global _key_cache
    _key_cache = None


def enabled() -> bool:
    return os.environ.get("ENCRYPT_AT_REST", "1").strip().lower() not in ("0", "false", "no", "off")


def encrypt(data: bytes, key: bytes | None = None) -> bytes:
    nonce = secrets.token_bytes(NONCE_LEN)
    return MAGIC + nonce + AESGCM(key or data_key()).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, key: bytes | None = None) -> bytes:
    if not blob.startswith(MAGIC):
        raise VaultError("not an encrypted vault file")
    nonce = blob[len(MAGIC):len(MAGIC) + NONCE_LEN]
    try:
        return AESGCM(key or data_key()).decrypt(nonce, blob[len(MAGIC) + NONCE_LEN:], MAGIC)
    except InvalidTag as e:
        raise VaultError("cannot decrypt: wrong key or the file was modified") from e


def is_encrypted(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def read_bytes(path: Path) -> bytes:
    blob = Path(path).read_bytes()
    return decrypt(blob) if blob.startswith(MAGIC) else blob


def write_bytes(path: Path, data: bytes) -> None:
    """Atomic: the file is complete or absent, never half written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_bytes(encrypt(data) if enabled() else data)
    os.replace(tmp, path)


def read_text(path: Path, encoding: str = "utf-8") -> str:
    return read_bytes(path).decode(encoding)


def write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    write_bytes(path, text.encode(encoding))


def read_json(path: Path):
    return json.loads(read_text(path))


def write_json(path: Path, obj, **dumps_kwargs) -> None:
    dumps_kwargs.setdefault("ensure_ascii", False)
    write_text(path, json.dumps(obj, **dumps_kwargs))


def read_npz(path: Path):
    import numpy as np
    return np.load(io.BytesIO(read_bytes(path)), allow_pickle=False)


def write_npz(path: Path, **arrays) -> None:
    import numpy as np
    buf = io.BytesIO()
    np.savez(buf, **arrays)
    write_bytes(path, buf.getvalue())


def encrypt_tree(folder: Path) -> int:
    """Encrypt every plain file under a folder in place (one-off migration). Returns a count."""
    n = 0
    for p in Path(folder).rglob("*"):
        if p.is_file() and not p.name.startswith(".") and not is_encrypted(p) and not p.name.endswith(".tmp"):
            write_bytes(p, p.read_bytes())
            n += 1
    return n


if __name__ == "__main__":  # python -m app.vault encrypt-cache
    import sys
    if sys.argv[1:] == ["encrypt-cache"]:
        print(f"encrypted {encrypt_tree(CACHE_DIR)} file(s) under {CACHE_DIR}")
    elif sys.argv[1:] == ["new-key"]:
        print(base64.b64encode(secrets.token_bytes(KEY_LEN)).decode("ascii"))
    else:
        print("usage: python -m app.vault encrypt-cache | new-key")
