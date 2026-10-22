import os
import urllib.parse
from pathlib import Path
from typing import Any

from backend.services.semantic import JevServiceConfig
from tg_signer.atomic_io import path_write_lock, read_json_safe, write_json_atomic
from tg_signer.security import (
    decrypt_secret,
    encrypt_secret,
    is_masked_secret,
    mask_secret,
)
from tg_signer.semantic.security import validate_ssrf_and_host


class JevConfigStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.config_path = self.root / ".jev_config.json"

    def load(self) -> JevServiceConfig:
        with path_write_lock(self.config_path):
            if not self.config_path.exists():
                data: dict[str, Any] = {}
            else:
                data = read_json_safe(self.config_path, default={})
                if not isinstance(data, dict):
                    data = {}

            # 解密 api_key
            raw_key = data.get("api_key", "")
            plain_key = ""
            if raw_key:
                try:
                    plain_key = decrypt_secret(raw_key)
                except Exception:
                    plain_key = ""

            config_dict = dict(data)
            # 环境变量兜底（优先级：显式配置 > env > 默认）
            if plain_key:
                config_dict["api_key"] = plain_key
            else:
                env_key = os.getenv("JEV_API_KEY", "").strip()
                if env_key:
                    config_dict["api_key"] = env_key

            saved_base = config_dict.get("base_url")
            if not saved_base or str(saved_base).rstrip("/") == "https://api.typesafe.ai/v1":
                env_base = os.getenv("JEV_BASE_URL", "").strip()
                if env_base:
                    config_dict["base_url"] = env_base

            saved_model = config_dict.get("model")
            if not saved_model or saved_model == "jev-1.13.0":
                env_model = os.getenv("JEV_MODEL", "").strip()
                if env_model:
                    config_dict["model"] = env_model

            try:
                return JevServiceConfig(**config_dict)
            except Exception:
                return JevServiceConfig()

    def save_patch(self, patch: dict[str, Any]) -> JevServiceConfig:
        with path_write_lock(self.config_path):
            current = self.load()
            current_dict = current.dict()

            # 1. 目标 URL SSRF 校验
            new_base_url = patch.get("base_url")
            if new_base_url:
                is_valid, ssrf_err = validate_ssrf_and_host(new_base_url)
                if not is_valid:
                    raise ValueError(ssrf_err)

            # 2. 凭据外送面保护：更换 base_url 时，不得把已存密钥送往任意非同源主机
            if new_base_url:
                old_host = (urllib.parse.urlparse(current.base_url).hostname or "").lower()
                new_host = (urllib.parse.urlparse(new_base_url).hostname or "").lower()
                if old_host and new_host and old_host != new_host:
                    patch_key = patch.get("api_key")
                    # 若未提供新密钥，清空已存密钥，防止旧凭据外送
                    if not patch_key or is_masked_secret(patch_key) or patch_key.endswith("****"):
                        current_dict["api_key"] = ""

            clear_key = patch.get("clear_api_key", False)
            new_key = patch.get("api_key")

            for k, v in patch.items():
                if k in ("clear_api_key", "api_key", "generation"):
                    continue
                if hasattr(current, k):
                    current_dict[k] = v

            if clear_key:
                current_dict["api_key"] = ""
            elif new_key is not None and new_key != "":
                # 检查是否传入了掩码，避免将掩码覆盖保存
                if not is_masked_secret(new_key) and not new_key.endswith("****"):
                    current_dict["api_key"] = new_key

            current_dict["generation"] = current.generation + 1

            validated = JevServiceConfig(**current_dict)
            to_save = validated.dict()

            # 加密保存
            if to_save.get("api_key"):
                to_save["api_key"] = encrypt_secret(to_save["api_key"])
            else:
                to_save["api_key"] = ""

            write_json_atomic(self.config_path, to_save)
            return validated

    def get_sanitized_config(self) -> dict[str, Any]:
        cfg = self.load()
        d = cfg.dict()
        plain_key = d.pop("api_key", "")
        d["has_api_key"] = bool(plain_key)
        d["api_key_masked"] = mask_secret(plain_key) if plain_key else ""
        return d
