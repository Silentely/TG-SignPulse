import io
import tarfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.core.auth import create_access_token
from backend.core.config import get_settings
from backend.services.backup_archive import (
    create_backup_tarball,
    extract_backup_archive,
    prune_backups,
)
from backend.services.backup_crypto import (
    FORMAT_VERSION,
    HEADER_LENGTH,
    MAGIC,
    MAX_ITERATIONS,
    MIN_ITERATIONS,
    MODE_APP_SECRET,
    MODE_USER_PASSWORD,
    BackupDecryptionError,
    decrypt_backup,
    encrypt_backup,
)


def _auth_headers() -> dict:
    token = create_access_token(
        {"sub": "admin"},
        expires_delta=timedelta(hours=1),
    )
    return {"Authorization": f"Bearer {token}"}


def test_spbak_encryption_and_decryption_with_default_secret_key(isolated_env):
    raw_data = b"demo tar gz archive payload"

    # 不传 password，默认使用 settings.secret_key (由 isolated_env 设定)
    encrypted = encrypt_backup(raw_data, password=None)
    assert len(encrypted) >= HEADER_LENGTH + 16  # 41 字节头 + 16 字节 Tag
    assert encrypted[:5] == MAGIC
    assert encrypted[5] == FORMAT_VERSION
    assert encrypted[8] == MODE_APP_SECRET

    # 使用系统 secret_key 成功解密
    decrypted = decrypt_backup(encrypted, password=None)
    assert decrypted == raw_data


def test_spbak_encryption_and_decryption_with_password():
    raw_data = b"demo tar gz archive payload"
    password = "MySecurePassword123!"

    encrypted = encrypt_backup(raw_data, password=password)
    assert encrypted[:5] == MAGIC
    assert encrypted[5] == FORMAT_VERSION
    assert encrypted[8] == MODE_USER_PASSWORD

    decrypted = decrypt_backup(encrypted, password=password)
    assert decrypted == raw_data


def test_spbak_tampered_header_fails_aead_verification():
    raw_data = b"demo tar gz archive payload"
    password = "MySecurePassword123!"

    encrypted = bytearray(encrypt_backup(raw_data, password=password))
    # 篡改头部中的 Mode 字节 (偏移 8)
    encrypted[8] ^= 0x01

    with pytest.raises(BackupDecryptionError):
        decrypt_backup(bytes(encrypted), password=password)


def test_spbak_tampered_ciphertext_fails_aead_verification():
    raw_data = b"demo tar gz archive payload"
    password = "MySecurePassword123!"

    encrypted = bytearray(encrypt_backup(raw_data, password=password))
    # 篡改密文部分
    encrypted[-1] ^= 0xFF

    with pytest.raises(BackupDecryptionError):
        decrypt_backup(bytes(encrypted), password=password)


def test_spbak_wrong_password_fails():
    raw_data = b"demo tar gz archive payload"
    encrypted = encrypt_backup(raw_data, password="CorrectPassword123!")

    with pytest.raises(BackupDecryptionError, match="备份解密认证失败"):
        decrypt_backup(encrypted, password="WrongPassword999!")


def test_spbak_password_required_when_encrypted_with_password():
    raw_data = b"demo tar gz archive payload"
    encrypted = encrypt_backup(raw_data, password="CorrectPassword123!")

    with pytest.raises(BackupDecryptionError, match="该归档由用户密码加密，请输入密码"):
        decrypt_backup(encrypted, password=None)


def test_spbak_header_too_short():
    with pytest.raises(BackupDecryptionError, match="备份文件长度过短"):
        decrypt_backup(b"short")


def test_spbak_invalid_magic():
    raw_data = b"demo payload"
    encrypted = bytearray(encrypt_backup(raw_data, password="pass"))
    encrypted[:5] = b"WRONG"

    with pytest.raises(BackupDecryptionError, match="无效的魔数标识"):
        decrypt_backup(bytes(encrypted), password="pass")


def test_spbak_unsupported_version():
    raw_data = b"demo payload"
    encrypted = bytearray(encrypt_backup(raw_data, password="pass"))
    encrypted[5] = 0x02  # Version 2

    with pytest.raises(BackupDecryptionError, match="不支持的归档格式版本"):
        decrypt_backup(bytes(encrypted), password="pass")


def test_spbak_iterations_validation():
    raw_data = b"demo payload"

    # Encrypt: iterations too low
    with pytest.raises(ValueError, match="iterations 必须在"):
        encrypt_backup(raw_data, password="pass", iterations=MIN_ITERATIONS - 1)

    # Encrypt: iterations too high
    with pytest.raises(ValueError, match="iterations 必须在"):
        encrypt_backup(raw_data, password="pass", iterations=MAX_ITERATIONS + 1)

    # Valid custom iterations
    enc = encrypt_backup(raw_data, password="pass", iterations=300_000)
    assert decrypt_backup(enc, password="pass") == raw_data


def test_spbak_missing_secret_key_fails():
    with patch("backend.services.backup_crypto.get_settings") as mock_settings:
        mock_settings.return_value.secret_key = ""
        with pytest.raises(ValueError, match="未配置 secret_key"):
            encrypt_backup(b"data", password=None)

    enc = encrypt_backup(b"data", password="temp-password")
    with patch("backend.services.backup_crypto.get_settings") as mock_settings:
        mock_settings.return_value.secret_key = ""
        enc_app = bytearray(enc)
        enc_app[8] = MODE_APP_SECRET
        with pytest.raises(BackupDecryptionError, match="系统缺少 secret_key"):
            decrypt_backup(bytes(enc_app), password=None)


def test_backup_archive_create_and_extract_spbak(isolated_env, tmp_path: Path):
    data_dir = tmp_path / "test_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "db.sqlite").write_text("sqlite database content")
    (data_dir / "sessions").mkdir(parents=True, exist_ok=True)
    (data_dir / "sessions" / "test.session").write_text("session credentials")

    dest_spbak = tmp_path / "backup.spbak"
    res = create_backup_tarball(data_dir, dest_spbak, paths=["db.sqlite", "sessions"])
    assert res == dest_spbak
    assert dest_spbak.exists()

    content = dest_spbak.read_bytes()
    assert content[:5] == MAGIC
    assert content[8] == MODE_APP_SECRET

    restore_dir = tmp_path / "restore"
    count = extract_backup_archive(dest_spbak, restore_dir)
    assert count >= 2
    assert (restore_dir / "db.sqlite").read_text() == "sqlite database content"
    assert (
        restore_dir / "sessions" / "test.session"
    ).read_text() == "session credentials"


def test_backup_archive_create_and_extract_with_password(tmp_path: Path):
    data_dir = tmp_path / "test_data_pw"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "db.sqlite").write_text("user encrypted database")

    dest_spbak = tmp_path / "backup.spbak"
    create_backup_tarball(
        data_dir,
        dest_spbak,
        paths=["db.sqlite"],
        password="CustomUserPassword123!",
    )

    restore_dir = tmp_path / "restore"
    with pytest.raises(BackupDecryptionError):
        extract_backup_archive(
            dest_spbak,
            restore_dir,
            password="WrongPassword!",
        )

    count = extract_backup_archive(
        dest_spbak,
        restore_dir,
        password="CustomUserPassword123!",
    )
    assert count == 1
    assert (restore_dir / "db.sqlite").read_text() == "user encrypted database"


def test_extract_backup_archive_tar_bomb_protection(tmp_path: Path):
    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode="w:gz") as tar:
        payload = b"A" * 1024  # 1KB
        ti = tarfile.TarInfo("bomb.txt")
        ti.size = len(payload)
        tar.addfile(ti, io.BytesIO(payload))

    raw_tar = tar_buf.getvalue()
    spbak_path = tmp_path / "bomb.tar.gz"
    spbak_path.write_bytes(raw_tar)

    restore_dir = tmp_path / "restore"
    with pytest.raises(ValueError, match="疑似解压炸弹"):
        extract_backup_archive(spbak_path, restore_dir, max_extract_bytes=500)


def test_prune_backups_with_spbak(tmp_path: Path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for i in range(3):
        (backup_dir / f"auto-2026010{i}-120000.tar.gz").write_text("test")
    for i in range(3, 6):
        (backup_dir / f"auto-2026010{i}-120000.spbak").write_text("test")

    removed = prune_backups(backup_dir, keep=2)
    assert removed == 4
    remaining = [
        f.name
        for f in backup_dir.glob("auto-*.*")
        if f.name.endswith((".tar.gz", ".spbak"))
    ]
    assert len(remaining) == 2


def test_ops_export_and_import_api_roundtrip(client, tmp_path, isolated_env):
    settings = get_settings()
    data_dir = Path(settings.resolve_base_dir())
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "db.sqlite").write_text("api integration test content")

    headers = _auth_headers()

    # 1. 默认 export: 导出 .spbak 格式
    resp = client.post("/api/ops/backup/export", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/octet-stream"
    cd = resp.headers.get("content-disposition", "")
    assert ".spbak" in cd
    spbak_bytes = resp.content
    assert spbak_bytes[:5] == MAGIC

    # 2. 清理原文件后，通过 /api/ops/backup/import 导入还原
    (data_dir / "db.sqlite").unlink()
    assert not (data_dir / "db.sqlite").exists()

    import_resp = client.post(
        "/api/ops/backup/import",
        headers=headers,
        files={"file": ("backup.spbak", spbak_bytes, "application/octet-stream")},
    )
    assert import_resp.status_code == 200
    body = import_resp.json()
    assert body["success"] is True
    assert (data_dir / "db.sqlite").exists()
    assert (data_dir / "db.sqlite").read_text() == "api integration test content"
