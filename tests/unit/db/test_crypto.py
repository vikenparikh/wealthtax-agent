from wealthtax_agent.db.crypto import decrypt, encrypt


def test_encrypt_decrypt_roundtrip():
    blob = encrypt("123-45-6789")
    assert blob is not None and isinstance(blob, bytes)
    assert decrypt(blob) == "123-45-6789"


def test_encrypt_none_returns_none():
    assert encrypt(None) is None
    assert decrypt(None) is None


def test_decrypt_with_garbage_returns_none():
    assert decrypt(b"not a valid token") is None
