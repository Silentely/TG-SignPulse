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


class JevConfigStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.config_path = self.root / ".jev_config.json"

    def load(self) -> JevServiceConfig:
        with path_write_lock(self.config_path):
            if not self.config_path.exists():
                return JevServiceConfig()
            data = read_json_safe(self.config_path, default={})
            if not isinstance(data, dict):
                return JevServiceConfig()

            # 解密 api_key
            raw_key = data.get("api_key", "")
            plain_key = ""
            if raw_key:
                try:
                    plain_key = decrypt_secret(raw_key)
                except Exception:
                    plain_key = ""

            config_dict = dict(data)
            config_dict["api_key"] = plain_key
            try:
                return JevServiceConfig(**config_dict)
            except Exception:
                return JevServiceConfig()

    def save_patch(self, patch: dict[str, Any]) -> JevServiceConfig:
        with path_write_lock(self.config_path):
            current = self.load()
            current_dict = current.dict()

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
