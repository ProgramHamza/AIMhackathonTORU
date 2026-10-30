"""Encryption at rest: round trips, tamper detection, wrong key, legacy files."""
import numpy as np
import pytest

from app import vault


@pytest.fixture(autouse=True)
def fresh_key(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "KEY_FILE", tmp_path / ".data_key")
    monkeypatch.delenv("DATA_KEY", raising=False)
    monkeypatch.delenv("ENCRYPT_AT_REST", raising=False)
    vault.reset_key_cache()
    yield
    vault.reset_key_cache()


def test_key_is_created_once_and_reused(tmp_path):
    k1 = vault.data_key()
    vault.reset_key_cache()
    assert vault.data_key() == k1 and len(k1) == 32
    assert (tmp_path / ".data_key").exists()


def test_env_key_wins(monkeypatch):
    monkeypatch.setenv("DATA_KEY", "00" * 32)
    vault.reset_key_cache()
    assert vault.data_key() == bytes(32)


def test_bad_env_key_rejected(monkeypatch):
    monkeypatch.setenv("DATA_KEY", "too-short")
    vault.reset_key_cache()
    with pytest.raises(vault.VaultError):
        vault.data_key()


def test_round_trip_and_file_is_unreadable_without_key(tmp_path):
    p = tmp_path / "c.json"
    vault.write_json(p, {"patient": "secret text ü"})
    raw = p.read_bytes()
    assert raw.startswith(vault.MAGIC) and b"secret" not in raw
    assert vault.read_json(p) == {"patient": "secret text ü"}
    assert vault.is_encrypted(p)


def test_tamper_is_detected(tmp_path):
    p = tmp_path / "c.bin"
    vault.write_bytes(p, b"abc" * 100)
    raw = bytearray(p.read_bytes())
    raw[-1] ^= 0x01
    p.write_bytes(bytes(raw))
    with pytest.raises(vault.VaultError):
        vault.read_bytes(p)


def test_wrong_key_fails(tmp_path, monkeypatch):
    p = tmp_path / "c.bin"
    vault.write_bytes(p, b"hello")
    monkeypatch.setenv("DATA_KEY", "11" * 32)
    vault.reset_key_cache()
    with pytest.raises(vault.VaultError):
        vault.read_bytes(p)


def test_legacy_plain_file_is_read_and_encrypted_on_save(tmp_path):
    p = tmp_path / "old.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    assert vault.read_json(p) == {"a": 1}
    vault.write_json(p, vault.read_json(p))
    assert vault.is_encrypted(p)


def test_npz_round_trip(tmp_path):
    p = tmp_path / "a.npz"
    vault.write_npz(p, x=np.arange(6, dtype=np.float32).reshape(2, 3))
    assert p.read_bytes().startswith(vault.MAGIC)
    assert vault.read_npz(p)["x"].tolist() == [[0, 1, 2], [3, 4, 5]]


def test_disabled_writes_plain(tmp_path, monkeypatch):
    monkeypatch.setenv("ENCRYPT_AT_REST", "0")
    p = tmp_path / "p.txt"
    vault.write_text(p, "plain")
    assert p.read_text(encoding="utf-8") == "plain" and vault.read_text(p) == "plain"


def test_write_is_atomic(tmp_path):
    p = tmp_path / "x.bin"
    vault.write_bytes(p, b"1")
    vault.write_bytes(p, b"2")
    assert vault.read_bytes(p) == b"2" and not list(tmp_path.glob("*.tmp"))


def test_encryption_is_fast(tmp_path):
    import time
    data = b"x" * (8 * 1024 * 1024)
    t = time.perf_counter()
    blob = vault.encrypt(data)
    vault.decrypt(blob)
    assert time.perf_counter() - t < 1.0  # 8 MB both ways; AES-NI does this in milliseconds
