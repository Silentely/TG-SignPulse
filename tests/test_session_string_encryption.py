import base64
import struct
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.utils.tg_session import load_session_string_file, save_session_string_file
from tg_signer.compat import _SESSION_STRING_FORMAT
from tg_signer.security import SecretKeyError


def _make_valid_session_string() -> str:
    packed = struct.pack(
        _SESSION_STRING_FORMAT,
        2,
        12345,
        False,
        bytes(range(256)),
        987654321,
        False,
    )
    return base64.urlsafe_b64encode(packed).decode("ascii").rstrip("=")


def test_session_string_file_encryption_and_fail_closed(tmp_path: Path):
    valid_session = _make_valid_session_string()
    account = "acc_test_sec"

    # 1. Normal save encrypts
    save_session_string_file(tmp_path, account, valid_session)
    raw = (tmp_path / f"{account}.session_string").read_text(encoding="utf-8").strip()
    assert raw.startswith("fernet:")

    # 2. Read back works
    loaded = load_session_string_file(tmp_path, account)
    assert loaded == valid_session

    # 3. Fail-closed: SecretKeyError must NOT write plaintext file
    bad_acc = "acc_bad_sec"
    target_file = tmp_path / f"{bad_acc}.session_string"
    with patch("tg_signer.security.encrypt_secret", side_effect=SecretKeyError("No secret key")):
        with pytest.raises(SecretKeyError):
            save_session_string_file(tmp_path, bad_acc, valid_session)
    assert not target_file.exists(), "Target file must not be created on encryption failure!"

    # 4. Legacy plaintext auto-migrates atomically
    plain_acc = "acc_legacy"
    legacy_file = tmp_path / f"{plain_acc}.session_string"
    legacy_file.write_text(valid_session, encoding="utf-8")
    loaded_plain = load_session_string_file(tmp_path, plain_acc)
    assert loaded_plain == valid_session
    migrated_raw = legacy_file.read_text(encoding="utf-8").strip()
    assert migrated_raw.startswith("fernet:")

    # 5. Migration failure leaves original plaintext intact
    fail_acc = "acc_fail_migration"
    fail_file = tmp_path / f"{fail_acc}.session_string"
    fail_file.write_text(valid_session, encoding="utf-8")
    with patch("tg_signer.security.encrypt_secret", side_effect=SecretKeyError("key missing")):
        with pytest.raises(SecretKeyError):
            load_session_string_file(tmp_path, fail_acc)
    assert fail_file.read_text(encoding="utf-8") == valid_session

    # 6. Read failure on SecretKeyError re-raises and preserves file
    enc_acc = "acc_enc_key_error"
    save_session_string_file(tmp_path, enc_acc, valid_session)
    enc_file = tmp_path / f"{enc_acc}.session_string"
    orig_content = enc_file.read_text(encoding="utf-8")
    with patch("tg_signer.security.decrypt_secret", side_effect=SecretKeyError("key missing")):
        with pytest.raises(SecretKeyError):
            load_session_string_file(tmp_path, enc_acc)
    assert enc_file.exists(), "Encrypted file must not be deleted on SecretKeyError!"
    assert enc_file.read_text(encoding="utf-8") == orig_content

    # 7. Corrupted ciphertext returns None and does not unlink file
    corrupt_acc = "acc_corrupt_sec"
    corrupt_file = tmp_path / f"{corrupt_acc}.session_string"
    corrupt_content = "fernet:corrupted"
    corrupt_file.write_text(corrupt_content, encoding="utf-8")
    res = load_session_string_file(tmp_path, corrupt_acc)
    assert res is None
    assert corrupt_file.exists(), "Corrupted ciphertext file must not be unlinked!"
    assert corrupt_file.read_text(encoding="utf-8") == corrupt_content
