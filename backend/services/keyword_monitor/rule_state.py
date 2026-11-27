"""关键词规则/触发器的持久状态存储。

以 ``rule_id + trigger_id`` 为键保存运行状态：
- ``last_trigger_at``：上次触发时间
- ``consecutive_failures``：连续失败次数
- ``silence_until``：静默截止时间
- ``catch_up_pending``：重启后是否已放行一次补触发

状态写入复用项目已有的原子写与文件锁工具；文件损坏时安全降级为空状态，
只记日志，不抛出异常。
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from backend.utils.atomic_io import path_write_lock, write_json_atomic
from backend.utils.time import utc_now_iso_z_seconds

logger = logging.getLogger("backend.keyword_monitor.rule_state")

RULE_STATE_FILENAME = "rule_state.json"


def make_rule_state_key(rule_id: str, trigger_id: str) -> str:
    return f"{str(rule_id).strip()}::{str(trigger_id).strip()}"


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _to_iso(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _as_non_negative_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RulePolicy:
    """规则状态策略（来自规则 action 配置）。"""

    cooldown_seconds: int = 0
    failure_threshold: int = 0
    silence_seconds: int = 0
    catch_up_on_start: bool = False

    @classmethod
    def from_action(cls, action: Mapping[str, Any]) -> "RulePolicy":
        action = action or {}
        cooldown_seconds = _as_non_negative_int(action.get("state_cooldown_seconds"), 0)
        if not cooldown_seconds:
            cooldown_seconds = (
                _as_non_negative_int(action.get("state_cooldown_minutes"), 0) * 60
            )
        silence_seconds = _as_non_negative_int(action.get("state_silence_seconds"), 0)
        if not silence_seconds:
            silence_seconds = (
                _as_non_negative_int(action.get("state_silence_minutes"), 0) * 60
            )
        return cls(
            cooldown_seconds=cooldown_seconds,
            failure_threshold=_as_non_negative_int(
                action.get("state_failure_threshold"), 0
            ),
            silence_seconds=silence_seconds,
            catch_up_on_start=_as_bool(action.get("state_catch_up_on_start"), False),
        )


def evaluate_trigger(
    state: Mapping[str, Any],
    policy: RulePolicy,
    *,
    now: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """判断当前是否允许触发，返回 (allowed, reason)。

    静默优先于冷却；冷却未过一律拒绝，重启补触发也不会绕过冷却。
    """
    current = _now(now)
    silence_until = _parse_iso((state or {}).get("silence_until"))
    if silence_until is not None and silence_until > current:
        return False, "silenced"

    if policy.cooldown_seconds > 0:
        last_trigger = _parse_iso((state or {}).get("last_trigger_at"))
        if last_trigger is not None and current - last_trigger < timedelta(
            seconds=policy.cooldown_seconds
        ):
            return False, "cooldown"

    if (state or {}).get("catch_up_pending"):
        return True, "catch_up"
    return True, "ok"


class RuleStateStore:
    """按规则/触发器键持久化的状态存储（JSON + 原子写 + 文件锁）。"""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._lock = threading.Lock()

    def load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("规则状态文件损坏,已降级为空状态: %s", exc)
            return {}
        if not isinstance(raw, dict):
            logger.warning("规则状态文件结构异常,已降级为空状态")
            return {}
        return {
            str(key): dict(value)
            for key, value in raw.items()
            if isinstance(value, dict)
        }

    def get(self, rule_id: str, trigger_id: str) -> Dict[str, Any]:
        return dict(self.load().get(make_rule_state_key(rule_id, trigger_id)) or {})

    def _update(
        self,
        rule_id: str,
        trigger_id: str,
        mutate,
    ) -> Dict[str, Any]:
        key = make_rule_state_key(rule_id, trigger_id)
        with self._lock:
            payload = self.load()
            state = dict(payload.get(key) or {})
            updated = mutate(state)
            updated["updated_at"] = utc_now_iso_z_seconds()
            payload[key] = updated
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with path_write_lock(self.path):
                write_json_atomic(self.path, payload)
        return updated

    def record_trigger(
        self,
        rule_id: str,
        trigger_id: str,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        timestamp = _to_iso(_now(now))

        def mutate(state: Dict[str, Any]) -> Dict[str, Any]:
            state["last_trigger_at"] = timestamp
            state["catch_up_pending"] = False
            return state

        return self._update(rule_id, trigger_id, mutate)

    def record_success(self, rule_id: str, trigger_id: str) -> Dict[str, Any]:
        def mutate(state: Dict[str, Any]) -> Dict[str, Any]:
            state["consecutive_failures"] = 0
            state["last_success_at"] = utc_now_iso_z_seconds()
            return state

        return self._update(rule_id, trigger_id, mutate)

    def record_failure(
        self,
        rule_id: str,
        trigger_id: str,
        policy: RulePolicy,
        *,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        current = _now(now)

        def mutate(state: Dict[str, Any]) -> Dict[str, Any]:
            failures = _as_non_negative_int(state.get("consecutive_failures"), 0) + 1
            state["consecutive_failures"] = failures
            state["last_failure_at"] = _to_iso(current)
            if policy.failure_threshold > 0 and failures >= policy.failure_threshold:
                state["consecutive_failures"] = 0
                if policy.silence_seconds > 0:
                    state["silence_until"] = _to_iso(
                        current + timedelta(seconds=policy.silence_seconds)
                    )
            return state

        return self._update(rule_id, trigger_id, mutate)

    def plan_startup_catch_up(
        self,
        entries: Iterable[Tuple[str, str, RulePolicy]],
        *,
        now: Optional[datetime] = None,
    ) -> List[Dict[str, str]]:
        """重启后为满足条件的规则放行一次补触发。

        条件：规则开启 catch_up_on_start、不在静默期、冷却已过。
        返回被放行的规则键列表（用于日志）。
        """
        current = _now(now)
        planned: List[Dict[str, str]] = []
        for rule_id, trigger_id, policy in entries:
            if not policy.catch_up_on_start:
                continue
            state = self.get(rule_id, trigger_id)
            allowed, reason = evaluate_trigger(state, policy, now=current)
            if not allowed or reason != "ok":
                continue

            def mutate(state: Dict[str, Any]) -> Dict[str, Any]:
                state["catch_up_pending"] = True
                return state

            self._update(rule_id, trigger_id, mutate)
            planned.append({"rule_id": str(rule_id), "trigger_id": str(trigger_id)})
        return planned
