"""设备指纹画像池与管理 (Task 6)。

借鉴 moeacgx/Telegram-Panel 设备画像机制及风控实践，
提供结构化的设备画像预设（Desktop, Android, iOS, macOS），
严格匹配 device_model, system_version, app_version, lang_code, system_lang_code，
杜绝特征违和拼装。
"""
from __future__ import annotations

import random
from typing import Any, Literal, Optional

DeviceFamily = Literal["desktop", "android", "macos", "ios"]

DEFAULT_DEVICE_FAMILY: DeviceFamily = "desktop"
VALID_DEVICE_FAMILIES = ("desktop", "android", "macos", "ios")
REQUIRED_DEVICE_PROFILE_KEYS = (
    "device_model",
    "system_version",
    "app_version",
    "lang_code",
    "system_lang_code",
)

DEVICE_PROFILES: dict[str, list[dict[str, str]]] = {
    "desktop": [
        {
            "device_model": "PC 64bit",
            "system_version": "Windows 10",
            "app_version": "5.4.1 x64",
            "lang_code": "en",
            "system_lang_code": "en-US",
        },
        {
            "device_model": "PC 64bit",
            "system_version": "Windows 11",
            "app_version": "5.5.0 x64",
            "lang_code": "zh-hans",
            "system_lang_code": "zh-CN",
        },
    ],
    "android": [
        {
            "device_model": "Samsung SM-S918B",
            "system_version": "SDK 34",
            "app_version": "11.1.3 (5234)",
            "lang_code": "en",
            "system_lang_code": "en",
        },
        {
            "device_model": "Xiaomi 23127PN0CC",
            "system_version": "SDK 33",
            "app_version": "11.0.0 (5120)",
            "lang_code": "zh",
            "system_lang_code": "zh-CN",
        },
    ],
    "macos": [
        {
            "device_model": "MacBook Pro",
            "system_version": "macOS 14.5",
            "app_version": "10.15.1",
            "lang_code": "en",
            "system_lang_code": "en-US",
        },
    ],
    "ios": [
        {
            "device_model": "iPhone 15 Pro",
            "system_version": "iOS 17.5.1",
            "app_version": "10.14.2",
            "lang_code": "en",
            "system_lang_code": "en-US",
        },
    ],
}

DEVICE_PRESET_POOL = DEVICE_PROFILES


def get_random_profile(family: str = DEFAULT_DEVICE_FAMILY) -> dict[str, str]:
    """从指定设备族预设中随机获取一套画像（返回独立副本）。"""
    family_normalized = (family or "").strip().lower()
    if family_normalized not in DEVICE_PROFILES:
        raise ValueError(
            f"Unknown device family: '{family}'. Expected one of {list(DEVICE_PROFILES.keys())}"
        )
    preset = random.choice(DEVICE_PROFILES[family_normalized]).copy()
    preset["device_family"] = family_normalized
    return preset


def _detect_model_family(model: str) -> Optional[str]:
    m = model.lower()
    if "iphone" in m or "ipad" in m:
        return "ios"
    if "macbook" in m or "mac" in m:
        return "macos"
    if any(k in m for k in ("samsung", "xiaomi", "sm-", "redmi", "pixel", "android")):
        return "android"
    if "pc" in m or "windows" in m or "linux" in m:
        return "desktop"
    return None


def _detect_system_family(system: str) -> Optional[str]:
    s = system.lower()
    if "ios" in s:
        return "ios"
    if "macos" in s or "os x" in s:
        return "macos"
    if "sdk" in s or "android" in s:
        return "android"
    if "windows" in s or "win" in s or "linux" in s:
        return "desktop"
    return None


def validate_device_profile(profile: dict[str, Any]) -> dict[str, str]:
    """校验设备画像完整性，杜绝跨族拼装与非法参数。"""
    if not isinstance(profile, dict):
        raise ValueError("device_profile must be a dictionary")

    for key in REQUIRED_DEVICE_PROFILE_KEYS:
        val = profile.get(key)
        if val is None or not str(val).strip():
            raise ValueError(f"Missing required device profile key: '{key}'")

    model_family = _detect_model_family(str(profile["device_model"]))
    system_family = _detect_system_family(str(profile["system_version"]))

    if model_family and system_family and model_family != system_family:
        raise ValueError(
            f"Cross-family device profile mismatch: device_model indicates '{model_family}', "
            f"but system_version indicates '{system_family}'"
        )

    explicit_family = profile.get("device_family")
    if explicit_family is not None and str(explicit_family).strip():
        fam = str(explicit_family).strip().lower()
        if fam not in VALID_DEVICE_FAMILIES:
            raise ValueError(f"Unknown device family: '{fam}'. Expected one of {VALID_DEVICE_FAMILIES}")
        if model_family and model_family != fam:
            raise ValueError(
                f"Cross-family device profile mismatch: explicit family '{fam}' conflicts with device_model '{profile['device_model']}' ({model_family})"
            )
        if system_family and system_family != fam:
            raise ValueError(
                f"Cross-family device profile mismatch: explicit family '{fam}' conflicts with system_version '{profile['system_version']}' ({system_family})"
            )

    result = {k: str(profile[k]).strip() for k in REQUIRED_DEVICE_PROFILE_KEYS}
    if explicit_family:
        result["device_family"] = str(explicit_family).strip().lower()
    elif model_family:
        result["device_family"] = model_family
    elif system_family:
        result["device_family"] = system_family
    return result
