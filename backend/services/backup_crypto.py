from __future__ import annotations

import os
import struct
from typing import Optional

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from backend.core.config import get_settings

MAGIC = b"SPBAK"
FORMAT_VERSION = 0x01
KDF_PBKDF2_SHA256 = 0x01
CIPHER_AES_256_GCM = 0x01
MODE_APP_SECRET = 0x01
MODE_USER_PASSWORD = 0x02

HEADER_LENGTH = 41
DEFAULT_ITERATIONS = 600_000
MIN_ITERATIONS = 200_000
MAX_ITERATIONS = 2_000_000
MAX_EXTRACT_BYTES = 500 * 1024 * 1024  # 500MB 解压炸弹上限
MAX_ENCRYPT_INPUT_BYTES = 100 * 1024 * 1024  # AES-GCM 单包加密内存上限


class BackupDecryptionError(Exception):
    """备份解密或完整性校验失败"""


def _derive_key(secret: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=iterations,
    )
    return kdf.derive(secret.encode("utf-8"))


def encrypt_backup(
    data: bytes,
    password: Optional[str] = None,
    iterations: int = DEFAULT_ITERATIONS,
) -> bytes:
    if len(data) > MAX_ENCRYPT_INPUT_BYTES:
        raise ValueError(
            f"待加密数据超过单包内存安全上限 ({MAX_ENCRYPT_INPUT_BYTES} 字节)"
        )
    if not (MIN_ITERATIONS <= iterations <= MAX_ITERATIONS):
        raise ValueError(
            f"iterations 必须在 {MIN_ITERATIONS} 到 {MAX_ITERATIONS} 之间，当前为 {iterations}"
        )

    settings = get_settings()
    if password:
        mode = MODE_USER_PASSWORD
        secret = password
    else:
        mode = MODE_APP_SECRET
        secret = settings.secret_key
        if not secret:
            raise ValueError("未配置 secret_key，无法执行默认加密备份")

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(secret, salt, iterations)

    canonical_header = (
        MAGIC
        + bytes([FORMAT_VERSION, KDF_PBKDF2_SHA256, CIPHER_AES_256_GCM, mode])
        + struct.pack(">I", iterations)
        + salt
        + nonce
    )
    if len(canonical_header) != HEADER_LENGTH:
        # 头部长度是格式契约，用显式校验而非 assert（-O 下 assert 会被剥离）
        raise ValueError(f"头部长度必须为 41 字节，当前为 {len(canonical_header)}")

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, canonical_header)
    return canonical_header + ciphertext


def decrypt_backup(spbak_bytes: bytes, password: Optional[str] = None) -> bytes:
    if len(spbak_bytes) < HEADER_LENGTH + 16:
        raise BackupDecryptionError("备份文件长度过短，非合规 .spbak 格式")

    header = spbak_bytes[:HEADER_LENGTH]
    ciphertext = spbak_bytes[HEADER_LENGTH:]

    magic = header[:5]
    if magic != MAGIC:
        raise BackupDecryptionError("无效的魔数标识")

    version = header[5]
    if version != FORMAT_VERSION:
        raise BackupDecryptionError(f"不支持的归档格式版本: {version}")

    if header[6] != KDF_PBKDF2_SHA256:
        raise BackupDecryptionError("不支持的 KDF 算法")
    if header[7] != CIPHER_AES_256_GCM:
        raise BackupDecryptionError("不支持的加密算法")

    mode = header[8]
    iterations = struct.unpack(">I", header[9:13])[0]
    if not (MIN_ITERATIONS <= iterations <= MAX_ITERATIONS):
        raise BackupDecryptionError("Iterations 超出安全范围")

    salt = header[13:29]
    nonce = header[29:41]

    settings = get_settings()
    if mode == MODE_USER_PASSWORD:
        if not password:
            raise BackupDecryptionError("该归档由用户密码加密，请输入密码")
        secret = password
    elif mode == MODE_APP_SECRET:
        secret = settings.secret_key
        if not secret:
            raise BackupDecryptionError("系统缺少 secret_key")
    else:
        raise BackupDecryptionError(f"未知的加密模式: {mode}")

    key = _derive_key(secret, salt, iterations)
    aesgcm = AESGCM(key)

    try:
        decrypted = aesgcm.decrypt(nonce, ciphertext, header)
    except Exception as e:
        raise BackupDecryptionError("备份解密认证失败，密码错误或归档已被篡改") from e

    return decrypted
