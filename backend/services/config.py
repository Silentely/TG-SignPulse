"""
配置管理服务
提供任务配置的导入导出功能
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.core.config import get_settings
from backend.utils.names import validate_storage_name
from backend.utils.storage import (
    clear_data_dir_override,
    is_writable_dir,
    load_data_dir_override,
    save_data_dir_override,
)


class ConfigService:
    """配置管理服务类"""

    _file_lock = threading.RLock()

    def _read_json_file(self, path: Path, default: Any = None) -> Any:
        """带进程内锁读取 JSON，避免同进程并发读写交错。"""
        if not path.exists():
            return default
        try:
            with self._file_lock:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default

    def _write_json_file(self, path: Path, data: Any) -> bool:
        """原子写入 JSON，避免异常中断时留下半截配置文件。"""
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        with self._file_lock:
            try:
                fd, temp_name = tempfile.mkstemp(
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    dir=str(path.parent),
                )
                temp_path = Path(temp_name)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(temp_path, path)
                return True
            except Exception:
                if temp_path is not None:
                    with contextlib.suppress(OSError):
                        temp_path.unlink()
                logging.getLogger("backend.config").exception(
                    "Failed to write JSON file: %s", path
                )
                return False

    def __init__(self):
        # 路径一律经 _ensure_paths / 属性解析，避免单例绑定过期 workdir
        self._workdir: Optional[Path] = None
        self._signs_dir: Optional[Path] = None
        self._monitors_dir: Optional[Path] = None
        self._ensure_paths()

    def _ensure_paths(self) -> None:
        """按当前环境同步 workdir（测试会切换 APP_DATA_DIR；get_settings 有缓存）。"""
        # 若 env 中的 APP_DATA_DIR 与缓存不一致则清缓存（仅测试热切换场景）
        env_data = (os.environ.get("APP_DATA_DIR") or "").strip()
        cached = get_settings()
        if env_data and str(cached.data_dir) != env_data:
            get_settings.cache_clear()
        workdir = get_settings().resolve_workdir()
        if self._workdir != workdir:
            self._workdir = workdir
            self._signs_dir = workdir / "signs"
            self._monitors_dir = workdir / "monitors"
            self._signs_dir.mkdir(parents=True, exist_ok=True)
            self._monitors_dir.mkdir(parents=True, exist_ok=True)

    @property
    def workdir(self) -> Path:
        self._ensure_paths()
        assert self._workdir is not None
        return self._workdir

    @property
    def signs_dir(self) -> Path:
        self._ensure_paths()
        assert self._signs_dir is not None
        return self._signs_dir

    @property
    def monitors_dir(self) -> Path:
        self._ensure_paths()
        assert self._monitors_dir is not None
        return self._monitors_dir

    def list_sign_tasks(self) -> List[str]:
        """获取所有签到任务名称列表"""
        tasks = []

        if self.signs_dir.exists():
            # 扫描顶层目录 (兼容旧版)
            for path in self.signs_dir.iterdir():
                if path.is_dir():
                    # Check if it's a task directory (has config.json)
                    if (path / "config.json").exists():
                        tasks.append(path.name)
                    else:
                        # Check if it's an account directory containing tasks
                        for task_dir in path.iterdir():
                            if task_dir.is_dir() and (task_dir / "config.json").exists():
                                tasks.append(task_dir.name)

        return sorted(set(tasks))  # 去重并排序

    def list_monitor_tasks(self) -> List[str]:
        """获取所有监控任务名称列表"""
        tasks = []

        if self.monitors_dir.exists():
            for task_dir in self.monitors_dir.iterdir():
                if task_dir.is_dir():
                    config_file = task_dir / "config.json"
                    if config_file.exists():
                        tasks.append(task_dir.name)

        return sorted(tasks)

    def _find_sign_task_dirs(self, task_name: str) -> List[Path]:
        matches = []
        if not self.signs_dir.exists():
            return matches

        # 1. 旧版结构: signs/task
        direct_dir = self.signs_dir / task_name
        if (direct_dir / "config.json").exists():
            matches.append(direct_dir)

        # 2. 新版结构: signs/account/task
        for acc_dir in self.signs_dir.iterdir():
            if acc_dir.is_dir():
                nested_task_dir = acc_dir / task_name
                if (nested_task_dir / "config.json").exists():
                    matches.append(nested_task_dir)

        return matches

    def get_sign_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[Dict]:
        """
        获取签到任务配置

        Args:
            task_name: 任务名称
            account_name: 账号名称（可选）

        Returns:
            配置字典，如果不存在则返回 None
        """
        task_name = validate_storage_name(task_name, field_name="task_name")
        if account_name:
            account_name = validate_storage_name(account_name, field_name="account_name")
            task_dir = self.signs_dir / account_name / task_name
            config_file = task_dir / "config.json"
            if not config_file.exists():
                return None
        else:
            matches = self._find_sign_task_dirs(task_name)
            if not matches:
                return None
            if len(matches) > 1:
                raise ValueError(f"任务 {task_name} 存在于多个账号中，请指定 account_name")
            task_dir = matches[0]
            config_file = task_dir / "config.json"

        return self._read_json_file(config_file)

    def save_sign_config(self, task_name: str, config: Dict) -> bool:
        """
        保存签到任务配置

        Args:
            task_name: 任务名称
            config: 配置字典

        Returns:
            是否成功保存
        """
        task_name = validate_storage_name(task_name, field_name="task_name")
        account_name = config.get("account_name", "")

        if account_name:
            account_name = validate_storage_name(account_name, field_name="account_name")
            # 使用新版结构: signs/account/task
            task_dir = self.signs_dir / account_name / task_name
        else:
            # 兼容旧版或无账号: signs/task
            task_dir = self.signs_dir / task_name

        task_dir.mkdir(parents=True, exist_ok=True)
        config_file = task_dir / "config.json"

        return self._write_json_file(config_file, config)

    def delete_sign_config(
        self, task_name: str, account_name: Optional[str] = None
    ) -> bool:
        """
        删除签到任务配置

        Args:
            task_name: 任务名称
            account_name: 账号名称（可选）

        Returns:
            是否成功删除
        """
        task_name = validate_storage_name(task_name, field_name="task_name")
        if account_name:
            account_name = validate_storage_name(account_name, field_name="account_name")
            task_dir = self.signs_dir / account_name / task_name
            if not task_dir.exists():
                return False
        else:
            matches = self._find_sign_task_dirs(task_name)
            if not matches:
                return False
            if len(matches) > 1:
                raise ValueError(f"任务 {task_name} 存在于多个账号中，请指定 account_name")
            task_dir = matches[0]

        try:
            # 删除配置文件
            config_file = task_dir / "config.json"
            if config_file.exists():
                config_file.unlink()

            # 删除签到记录文件
            record_file = task_dir / "sign_record.json"
            if record_file.exists():
                record_file.unlink()

            # 删除目录
            # 注意：如果是嵌套结构，这里只删除了任务目录，没有删除可能变空的账号目录
            # 这通常是可以接受的，或者我们可以检查父目录是否为空并删除
            import shutil
            shutil.rmtree(task_dir)

            return True
        except OSError:
            return False

    def export_sign_task(
        self, task_name: str, account_name: Optional[str] = None
    ) -> Optional[str]:
        """
        导出签到任务配置为 JSON 字符串

        Args:
            task_name: 任务名称
            account_name: 账号名称（可选）

        Returns:
            JSON 字符串，如果任务不存在则返回 None
        """
        config = self.get_sign_config(task_name, account_name=account_name)

        if config is None:
            return None

        config = dict(config)
        config.pop("last_run", None)
        # Keep exported payload account-agnostic for cross-account imports.
        config.pop("account_name", None)

        # 添加元数据
        export_data = {
            "task_name": task_name,
            "task_type": "sign",
            "config": config,
        }

        return json.dumps(export_data, ensure_ascii=False, indent=2)

    def import_sign_task(
        self,
        json_str: str,
        task_name: Optional[str] = None,
        account_name: Optional[str] = None,
    ) -> bool:
        """
        导入签到任务配置

        Args:
            json_str: JSON 字符串
            task_name: 新任务名称（可选，如果不提供则使用原名称）
            account_name: 新账号名称（可选，如果不提供则使用原名称）

        Returns:
            是否成功导入
        """
        try:
            data = json.loads(json_str)

            # 验证数据格式
            if "config" not in data:
                return False

            # 确定任务名称
            final_task_name = validate_storage_name(
                task_name or data.get("task_name", "imported_task"),
                field_name="task_name",
            )

            config = data["config"]
            if account_name:
                account_name = validate_storage_name(
                    account_name, field_name="account_name"
                )
                config["account_name"] = account_name

            # 保存配置
            return self.save_sign_config(final_task_name, config)

        except (json.JSONDecodeError, KeyError):
            return False

    # 导出脱敏占位；导入时若见到则跳过密钥写入，避免覆盖真实密钥
    AI_KEY_MASK = "***MASKED***"
    SECRET_MASKS = frozenset({AI_KEY_MASK, "***", "MASKED", "REDACTED", "***MASKED***"})

    def export_all_configs(self) -> str:
        """
        导出业务配置（任务 / 监控 / 设置）。

        不含 sessions、数据库、执行历史。
        AI api_key / WebDAV 密码 / Bot Token 默认脱敏。
        """
        all_configs: Dict[str, Any] = {
            "_meta": {
                "format": "tg-signpulse-config-export",
                "version": 1,
                "includes": ["signs", "monitors", "settings"],
                "excludes": [
                    "sessions",
                    "db.sqlite",
                    "history",
                    "account_login_state",
                ],
                "notes": [
                    "配置迁移用：可导入；不含 Telegram 登录会话。",
                    "AI api_key / WebDAV 密码 / Bot Token 已脱敏；导入时不会用占位符覆盖现有密钥。",
                    "整机恢复请用面板「完整数据备份」tar.gz + 手动解压覆盖 data/。",
                ],
            },
            "signs": {},
            "monitors": {},
            "settings": {},
        }

        # 导出所有签到任务
        if self.signs_dir.exists():
            # 1. 扫描顶层 (旧版)
            for path in self.signs_dir.iterdir():
                if path.is_dir() and (path / "config.json").exists():
                    config = self._read_json_file(path / "config.json")
                    if config is not None:
                        config.pop("last_run", None)
                        key = path.name
                        if key in all_configs["signs"]:
                            key = f"{key}_{config.get('account_name', 'default')}"
                        all_configs["signs"][key] = config

                # 2. 扫描账号层
                if path.is_dir():
                    for task_dir in path.iterdir():
                        if task_dir.is_dir() and (task_dir / "config.json").exists():
                            config = self._read_json_file(task_dir / "config.json")
                            if config is not None:
                                config.pop("last_run", None)
                                key = f"{task_dir.name}_{path.name}"
                                account_name = config.get("account_name")
                                if account_name:
                                    key = f"{config.get('name', task_dir.name)}@{account_name}"
                                else:
                                    key = config.get("name", task_dir.name)

                                if key in all_configs["signs"]:
                                    import uuid
                                    key = f"{key}_{str(uuid.uuid4())[:8]}"

                                all_configs["signs"][key] = config

        # 导出所有监控任务
        for task_name in self.list_monitor_tasks():
            config_file = self.monitors_dir / task_name / "config.json"
            config = self._read_json_file(config_file)
            if config is not None:
                config.pop("last_run", None)
                all_configs["monitors"][task_name] = config

        # 导出设置 — 敏感字段脱敏
        ai_config = self.get_ai_config()
        if ai_config and ai_config.get("api_key"):
            ai_config = dict(ai_config)
            ai_config["api_key"] = self.AI_KEY_MASK
            all_configs["_meta"]["ai_api_key_masked"] = True

        global_settings = dict(self.get_global_settings())
        if global_settings.get("webdav_password"):
            global_settings["webdav_password"] = self.AI_KEY_MASK
            all_configs["_meta"]["webdav_password_masked"] = True
        if global_settings.get("telegram_bot_token"):
            global_settings["telegram_bot_token"] = self.AI_KEY_MASK
            all_configs["_meta"]["telegram_bot_token_masked"] = True

        all_configs["settings"] = {
            "global": global_settings,
            "ai": ai_config,
            "telegram": self.get_telegram_config(),
        }

        return json.dumps(all_configs, ensure_ascii=False, indent=2)

    def import_all_configs(
        self, json_str: str, overwrite: bool = False
    ) -> Dict[str, Any]:
        """
        导入所有配置
        """
        result: Dict[str, Any] = {
            "signs_imported": 0,
            "signs_skipped": 0,
            "monitors_imported": 0,
            "monitors_skipped": 0,
            "settings_imported": 0,
            "settings_skipped": 0,
            "errors": [],
            "warnings": [],
        }

        try:
            data = json.loads(json_str)

            # 导入签到任务
            for key, config in data.get("signs", {}).items():
                task_name = config.get("name")
                if not task_name:
                    task_name = key.split("@")[0]

                if not overwrite:
                    account_name = config.get("account_name")
                    exists = False
                    if account_name:
                        if (self.signs_dir / account_name / task_name).exists():
                            exists = True
                    else:
                        if (self.signs_dir / task_name).exists():
                            exists = True

                    if exists:
                        result["signs_skipped"] += 1
                        continue

                if self.save_sign_config(task_name, config):
                    result["signs_imported"] += 1
                else:
                    result["errors"].append(f"Failed to import sign task: {task_name}")

            # 导入监控任务
            for task_name, config in data.get("monitors", {}).items():
                task_dir = self.monitors_dir / task_name
                config_file = task_dir / "config.json"

                if not overwrite and config_file.exists():
                    result["monitors_skipped"] += 1
                    continue

                task_dir.mkdir(parents=True, exist_ok=True)
                if self._write_json_file(config_file, config):
                    result["monitors_imported"] += 1
                else:
                    result["errors"].append(
                        f"Failed to import monitor task: {task_name}"
                    )

            # 导入设置
            settings_data = data.get("settings", {})

            if "global" in settings_data:
                try:
                    gs = dict(settings_data["global"] or {})
                    # 脱敏占位不得覆盖已有 WebDAV 密码 / Bot Token
                    for secret_key, warn in (
                        (
                            "webdav_password",
                            "webdav_password is masked in export; kept existing",
                        ),
                        (
                            "telegram_bot_token",
                            "telegram_bot_token is masked in export; kept existing",
                        ),
                    ):
                        raw = str(gs.get(secret_key) or "").strip()
                        if raw in self.SECRET_MASKS:
                            gs.pop(secret_key, None)
                            result["warnings"].append(warn)
                        elif not raw and secret_key in gs:
                            # 空串：不覆盖
                            gs.pop(secret_key, None)
                    if self.save_global_settings(gs):
                        result["settings_imported"] += 1
                    else:
                        result["errors"].append("Failed to import global settings")
                except Exception as e:
                    result["errors"].append(f"Failed to import global settings: {e}")

            # AI 配置：脱敏占位符不得覆盖现有密钥
            if "ai" in settings_data and settings_data["ai"]:
                try:
                    ai_conf = settings_data["ai"]
                    raw_key = str(ai_conf.get("api_key") or "").strip()
                    if not raw_key:
                        result["settings_skipped"] += 1
                        result["warnings"].append(
                            "AI config skipped: empty api_key"
                        )
                    elif raw_key in self.SECRET_MASKS:
                        result["settings_skipped"] += 1
                        result["warnings"].append(
                            "AI api_key is masked in export; kept existing key on server"
                        )
                        # 仍可更新 base_url / model（保留现有 key）
                        existing = self.get_ai_config() or {}
                        keep_key = str(existing.get("api_key") or "").strip()
                        if keep_key:
                            if self.save_ai_config(
                                keep_key,
                                ai_conf.get("base_url") or existing.get("base_url"),
                                ai_conf.get("model") or existing.get("model"),
                            ):
                                result["settings_imported"] += 1
                                result["warnings"].append(
                                    "AI base_url/model updated with existing api_key"
                                )
                    else:
                        if self.save_ai_config(
                            raw_key, ai_conf.get("base_url"), ai_conf.get("model")
                        ):
                            result["settings_imported"] += 1
                        else:
                            result["errors"].append("Failed to import AI config")
                except Exception as e:
                    result["errors"].append(f"Failed to import AI config: {e}")

            if "telegram" in settings_data:
                try:
                    tg_conf = settings_data["telegram"]
                    if (
                        tg_conf.get("is_custom")
                        and tg_conf.get("api_id")
                        and tg_conf.get("api_hash")
                    ):
                        if self.save_telegram_config(
                            str(tg_conf["api_id"]), tg_conf["api_hash"]
                        ):
                            result["settings_imported"] += 1
                        else:
                            result["errors"].append("Failed to import Telegram config")
                except Exception as e:
                    result["errors"].append(f"Failed to import Telegram config: {e}")

            try:
                from backend.services.sign_tasks import get_sign_task_service

                get_sign_task_service().invalidate_tasks_cache()
            except Exception as e:
                logging.getLogger("backend.config").warning(
                    "Failed to clear cache: %s", e
                )

        except (json.JSONDecodeError, KeyError) as e:
            result["errors"].append(f"Invalid JSON format: {str(e)}")

        return result

    # ============ AI 配置 ============

    def _get_ai_config_file(self) -> Path:
        """获取 AI 配置文件路径"""
        return self.workdir / ".openai_config.json"

    def get_ai_config(self) -> Optional[Dict]:
        """
        获取 AI 配置，优先解密加密的 API Key，兼容旧版明文

        Returns:
            配置字典，如果不存在则返回 None
        """
        config_file = self._get_ai_config_file()
        raw = self._read_json_file(config_file)
        if not raw:
            return None

        api_key = raw.get("api_key", "")

        return {
            "api_key": api_key,
            "base_url": raw.get("base_url"),
            "model": raw.get("model"),
        }

    def save_ai_config(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ) -> bool:
        """
        保存 AI 配置，API Key 使用 Fernet 加密存储

        Args:
            api_key: OpenAI API Key
            base_url: API Base URL（可选）
            model: 模型名称（可选）

        Returns:
            是否成功保存
        """
        existing = self.get_ai_config() or {}
        normalized_api_key = (api_key or "").strip()
        final_api_key = normalized_api_key or existing.get("api_key", "")
        if not final_api_key:
            raise ValueError("API Key 不能为空")

        config_file = self._get_ai_config_file()
        existing_raw = self._read_json_file(config_file) or {}

        # 使用 Fernet 加密，但存储为 api_key 字段以兼容 OpenAIConfigManager
        try:
            from tg_signer.security import encrypt_secret
            existing_raw["api_key"] = encrypt_secret(final_api_key)
        except Exception as exc:
            logging.getLogger("backend.config").error(
                "AI API Key 加密失败，拒绝保存明文: %s", exc
            )
            raise ValueError("API Key 加密失败，请检查 APP_SECRET_KEY 配置") from exc

        existing_raw["base_url"] = base_url if base_url else None
        existing_raw["model"] = model if model else None

        return self._write_json_file(config_file, existing_raw)

    def delete_ai_config(self) -> bool:
        """
        删除 AI 配置

        Returns:
            是否成功删除
        """
        config_file = self._get_ai_config_file()

        if not config_file.exists():
            return True

        try:
            config_file.unlink()
            return True
        except OSError:
            return False

    async def test_ai_connection(self) -> Dict:
        """
        测试 AI 连接

        Returns:
            测试结果
        """
        config = self.get_ai_config()

        if not config:
            return {"success": False, "message": "未配置 AI API Key"}

        api_key = config.get("api_key")
        base_url = config.get("base_url")
        model = config.get("model", "gpt-4o")

        if not api_key:
            return {"success": False, "message": "API Key 为空"}

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=api_key, base_url=base_url)

            # 发送一个简单的测试请求
            response = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Say 'test ok' in 2 words"}],
                max_tokens=10,
            )

            return {
                "success": True,
                "message": f"连接成功！模型响应: {response.choices[0].message.content}",
                "model_used": model,
            }

        except ImportError:
            return {
                "success": False,
                "message": "未安装 openai 库，请运行: pip install openai",
            }
        except Exception as e:
            return {"success": False, "message": f"连接失败: {str(e)}"}

    # ============ 全局设置 ============

    def _get_global_settings_file(self) -> Path:
        """获取全局设置文件路径"""
        return self.workdir / ".global_settings.json"

    def get_global_settings(self) -> Dict:
        """
        获取全局设置

        Returns:
            设置字典
        """
        config_file = self._get_global_settings_file()

        override_data_dir = load_data_dir_override()
        default_settings = {
            "sign_interval": None,  # None 表示使用随机 1-120 秒
            "log_retention_days": 7,
            "data_dir": str(override_data_dir) if override_data_dir else None,
            "global_proxy": None,
            "tg_global_concurrency": None,  # None 表示使用动态默认 min(cpu_count, 5)
            "device_keepalive_enabled": True,
            "device_keepalive_interval_days": 30,
            "telegram_bot_notify_enabled": False,
            "telegram_bot_login_notify_enabled": False,
            "telegram_bot_task_failure_enabled": True,
            "telegram_bot_task_success_enabled": False,
            "telegram_bot_quiet_hours_enabled": False,
            "telegram_bot_quiet_hours_start": "23:00",
            "telegram_bot_quiet_hours_end": "07:00",
            "telegram_bot_token": None,
            "telegram_bot_chat_id": None,
            "telegram_bot_message_thread_id": None,
            "sign_task_execution_timeout": None,
            "sign_task_account_cooldown": None,
            "sign_task_flow_retry_attempts": None,
            "sign_task_history_max_age_days": None,
            "ai_vision_timeout": None,
            "ai_vision_retry_attempts": None,
            "auto_backup_enabled": False,
            "auto_backup_interval_hours": 24,
            "auto_backup_keep": 3,
            "webdav_url": None,
            "webdav_username": None,
            "webdav_password": None,
            "webdav_remote_dir": "tg-signpulse-backups",
        }

        settings = self._read_json_file(config_file)
        if settings is None or not isinstance(settings, dict):
            settings = dict(default_settings)
        else:
            # 合并默认设置
            for key, value in default_settings.items():
                if key not in settings:
                    settings[key] = value
        # 时区：文件值优先，否则回退环境/核心配置（静默时段等依赖）
        if not settings.get("timezone"):
            try:
                settings["timezone"] = get_settings().timezone
            except Exception:
                settings.setdefault("timezone", "Asia/Hong_Kong")
        return settings

    def save_global_settings(self, settings: Dict) -> bool:
        """
        保存全局设置

        Args:
            settings: 设置字典

        Returns:
            是否成功保存
        """
        config_file = self._get_global_settings_file()
        merged = dict(self.get_global_settings())
        merged.update(settings)

        # 校验时区格式（防止导入配置等绕过路由层校验）
        tz_value = merged.get("timezone")
        if tz_value:
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo(str(tz_value))
            except Exception:
                raise ValueError(f"无效的时区: {tz_value}")

        data_dir_value = merged.get("data_dir")
        if isinstance(data_dir_value, str):
            data_dir_value = data_dir_value.strip()
        if data_dir_value:
            resolved = Path(str(data_dir_value)).expanduser()
            resolved.mkdir(parents=True, exist_ok=True)
            if not is_writable_dir(resolved):
                raise ValueError(f"数据路径不可写: {resolved}")
            save_data_dir_override(resolved)
            merged["data_dir"] = str(resolved)
        elif data_dir_value is None or data_dir_value == "":
            clear_data_dir_override()
            merged["data_dir"] = None

        if not self._write_json_file(config_file, merged):
            return False

        # Apply concurrency change at runtime
        concurrency_val = merged.get("tg_global_concurrency")
        if concurrency_val is not None:
            try:
                from backend.utils.tg_session import update_global_semaphore
                update_global_semaphore(int(concurrency_val))
            except Exception:
                pass

        # 同步高级参数到环境变量，供 tg_signer 等仍读 env 的路径使用
        env_sync = {
            "sign_task_execution_timeout": "SIGN_TASK_EXECUTION_TIMEOUT",
            "sign_task_account_cooldown": "SIGN_TASK_ACCOUNT_COOLDOWN",
            "sign_task_flow_retry_attempts": "SIGN_TASK_FLOW_RETRY_ATTEMPTS",
            "sign_task_history_max_age_days": "SIGN_TASK_HISTORY_MAX_AGE_DAYS",
            "ai_vision_timeout": "AI_VISION_TIMEOUT",
            "ai_vision_retry_attempts": "AI_VISION_RETRY_ATTEMPTS",
        }
        for gkey, ekey in env_sync.items():
            val = merged.get(gkey)
            if val is None or str(val).strip() == "":
                continue
            try:
                os.environ[ekey] = str(int(val))
            except (TypeError, ValueError):
                logging.getLogger("backend.config").debug(
                    "跳过无效 env 同步 %s=%r", ekey, val
                )

        return True

    def preview_import_all(self, json_str: str) -> Dict[str, Any]:
        """预览导入内容，不写盘。"""
        errors: List[str] = []
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            return {
                "signs_count": 0,
                "monitors_count": 0,
                "settings_keys": [],
                "conflicts": [],
                "errors": [str(e)],
            }
        if not isinstance(data, dict):
            return {
                "signs_count": 0,
                "monitors_count": 0,
                "settings_keys": [],
                "conflicts": [],
                "errors": ["配置根节点必须是对象"],
            }

        signs = data.get("signs") or {}
        monitors = data.get("monitors") or {}
        settings_data = data.get("settings") or {}
        if not isinstance(signs, dict):
            signs = {}
            errors.append("signs 字段格式无效")
        if not isinstance(monitors, dict):
            monitors = {}
            errors.append("monitors 字段格式无效")
        if not isinstance(settings_data, dict):
            settings_data = {}

        conflicts: List[str] = []
        for key, config in signs.items():
            task_name = ""
            account_name = None
            if isinstance(config, dict):
                task_name = str(config.get("name") or key.split("@")[0])
                account_name = config.get("account_name")
            else:
                task_name = str(key.split("@")[0])
            exists = False
            if account_name:
                exists = (self.signs_dir / str(account_name) / task_name).exists()
            else:
                exists = (self.signs_dir / task_name).exists() or bool(
                    self._find_sign_task_dirs(task_name)
                )
            if exists:
                conflicts.append(f"sign:{task_name}")

        for task_name in monitors:
            if (self.monitors_dir / str(task_name) / "config.json").exists():
                conflicts.append(f"monitor:{task_name}")

        settings_keys: List[str] = []
        for section in ("global", "ai", "telegram"):
            if section in settings_data and settings_data[section]:
                settings_keys.append(section)

        return {
            "signs_count": len(signs),
            "monitors_count": len(monitors),
            "settings_keys": settings_keys,
            "conflicts": conflicts,
            "errors": errors,
        }

    # ============ Telegram API 配置 ============

    # 默认的 Telegram API 凭证
    DEFAULT_TG_API_ID = "611335"
    DEFAULT_TG_API_HASH = "d524b414d21f4d37f08684c1df41ac9c"

    def _get_telegram_config_file(self) -> Path:
        """获取 Telegram API 配置文件路径"""
        return self.workdir / ".telegram_api.json"

    def get_telegram_config(self) -> Dict:
        """
        获取 Telegram API 配置

        Returns:
            配置字典，包含 api_id, api_hash, is_custom (是否为自定义配置)
        """
        config_file = self._get_telegram_config_file()

        # 默认配置
        default_config = {
            "api_id": self.DEFAULT_TG_API_ID,
            "api_hash": self.DEFAULT_TG_API_HASH,
            "is_custom": False,
        }

        config = self._read_json_file(config_file)
        if config is None:
            return default_config
        # 如果有自定义配置，标记为自定义
        if config.get("api_id") and config.get("api_hash"):
            config["is_custom"] = True
            return config
        else:
            return default_config

    def save_telegram_config(self, api_id: str, api_hash: str) -> bool:
        """
        保存 Telegram API 配置

        Args:
            api_id: Telegram API ID
            api_hash: Telegram API Hash

        Returns:
            是否成功保存
        """
        config = {
            "api_id": api_id,
            "api_hash": api_hash,
        }

        config_file = self._get_telegram_config_file()

        return self._write_json_file(config_file, config)

    def reset_telegram_config(self) -> bool:
        """
        重置 Telegram API 配置（恢复默认）

        Returns:
            是否成功重置
        """
        config_file = self._get_telegram_config_file()

        if not config_file.exists():
            return True

        try:
            config_file.unlink()
            return True
        except OSError:
            return False


# 创建全局实例
_config_service: Optional[ConfigService] = None


def get_config_service() -> ConfigService:
    global _config_service
    if _config_service is None:
        _config_service = ConfigService()
    else:
        # 环境数据目录变更时重建，避免单例绑定旧 workdir
        _config_service._ensure_paths()
    return _config_service
