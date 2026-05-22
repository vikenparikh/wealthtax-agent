from wealthtax_agent.db.crypto import decrypt, encrypt

# Use synthetic data that does NOT look like a real SSN/SIN.
# Real SSNs follow NNN-NN-NNNN format; we use a clearly-synthetic value.
_SYNTHETIC_PII = "SYNTH-TAX-ID-0000"


def test_encrypt_decrypt_roundtrip():
    blob = encrypt(_SYNTHETIC_PII)
    assert blob is not None and isinstance(blob, bytes)
    assert decrypt(blob) == _SYNTHETIC_PII


def test_encrypt_none_returns_none():
    assert encrypt(None) is None
    assert decrypt(None) is None


def test_decrypt_with_garbage_returns_none():
    assert decrypt(b"not a valid token") is None
