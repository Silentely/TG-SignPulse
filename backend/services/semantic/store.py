import time
import uuid
from pathlib import Path
from typing import Any, Callable

from tg_signer.atomic_io import path_write_lock, read_json_safe, write_json_atomic


def _scope_matches(target_scope: Any, query_scope: str) -> bool:
    if not query_scope:
        return True
    if not isinstance(target_scope, str):
        return False
    clean_query = query_scope.rstrip(":")
    if not clean_query:
        return True
    if target_scope == clean_query:
        return True
    return target_scope.startswith(f"{clean_query}:")


class SemanticStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.store_dir = self.root / "semantic"
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self.records_path = self.store_dir / "records.json"
        self.max_observations = 5000
        self.max_suggestions = 1000
        self.max_baselines = 1000
        self.max_monitor_keys = 10000

    def _mutate(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        with path_write_lock(self.records_path):
            raw = read_json_safe(
                self.records_path,
                default={
                    "observations": [],
                    "labels": {},
                    "suggestions": [],
                    "baselines": {},
                    "monitor_keys": {},
                },
            )
            # 平滑兼容旧版本/新版本缺失字段
            if not isinstance(raw, dict):
                raw = {}
            payload = {
                "observations": raw.get("observations", []) or [],
                "labels": raw.get("labels", {}) or {},
                "suggestions": raw.get("suggestions", []) or [],
                "baselines": raw.get("baselines", {}) or {},
                "monitor_keys": raw.get("monitor_keys", {}) or {},
            }
            result = mutator(payload)
            write_json_atomic(self.records_path, payload)
            return result

    def append(self, observation: dict[str, Any]) -> str:
        req_key = observation.get("request_key")
        scope = observation.get("scope", "")

        def _do_append(data: dict[str, Any]) -> str:
            obs_list = data["observations"]
            # 幂等去重：检查是否存在相同 scope 和 request_key
            if req_key:
                for item in obs_list:
                    if (
                        item.get("scope") == scope
                        and item.get("request_key") == req_key
                    ):
                        return item["id"]

            obs_id = str(uuid.uuid4())
            record = dict(observation)
            record["id"] = obs_id
            if "observed_at" not in record:
                record["observed_at"] = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                )
            obs_list.append(record)

            # 容量修剪（保留最新 N 条）
            if len(obs_list) > self.max_observations:
                data["observations"] = obs_list[-self.max_observations :]
            return obs_id

        return self._mutate(_do_append)

    def list_observations(
        self,
        *,
        scope: str = "",
        kind: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        def _do_list(data: dict[str, Any]) -> dict[str, Any]:
            obs_list = data.get("observations", [])
            labels = data.get("labels", {})

            matched = []
            for item in reversed(obs_list):
                if scope and not _scope_matches(item.get("scope", ""), scope):
                    continue
                if kind and item.get("kind") != kind:
                    continue
                row = dict(item)
                if item["id"] in labels:
                    row["human_label"] = labels[item["id"]]
                matched.append(row)

            total = len(matched)
            paginated = matched[offset : offset + limit]
            return {"total": total, "items": paginated}

        return self._mutate(_do_list)

    def label(self, observation_id: str, *, scope: str, label: str) -> dict[str, Any]:
        def _do_label(data: dict[str, Any]) -> dict[str, Any]:
            # 核对 observation 是否存在且匹配 scope
            obs_list = data.get("observations", [])
            target_obs = None
            for item in obs_list:
                if item["id"] == observation_id:
                    if scope and not _scope_matches(item.get("scope", ""), scope):
                        raise ValueError("SCOPE_MISMATCH")
                    target_obs = item
                    break
            if target_obs is None:
                raise FileNotFoundError("OBSERVATION_NOT_FOUND")

            from backend.services.semantic.review import validate_label

            kind = target_obs.get("kind", "")
            if not validate_label(kind, label):
                raise ValueError(
                    f"INVALID_LABEL: '{label}' is not valid for kind '{kind}'"
                )

            data["labels"][observation_id] = label

            # 建立或更新人工基线
            try:
                from backend.services.semantic.drift import build_baseline

                target_obs = next(it for it in obs_list if it["id"] == observation_id)
                baseline = build_baseline(observation=target_obs, label=label)
                if baseline:
                    baselines = data.get("baselines", {})
                    b_key = f"{baseline['scope']}:{baseline['config_revision']}"
                    if len(baselines) >= self.max_baselines and b_key not in baselines:
                        oldest_k = next(iter(baselines.keys()))
                        baselines.pop(oldest_k, None)
                    baselines[b_key] = baseline
                    data["baselines"] = baselines
            except Exception:
                pass

            return {"id": observation_id, "label": label}

        return self._mutate(_do_label)

    def claim_monitor_key(
        self, key: str, *, kind: str, now: float | None = None
    ) -> bool:
        if now is None:
            now = time.time()

        def _do_claim(data: dict[str, Any]) -> bool:
            m_keys = data["monitor_keys"]
            # 剔除超过 24h 的过期键
            expired_keys = [
                k for k, v in m_keys.items() if now - v.get("ts", 0) > 86400
            ]
            for k in expired_keys:
                m_keys.pop(k, None)

            if len(m_keys) >= self.max_monitor_keys and key not in m_keys:
                return False

            if key in m_keys:
                return False

            m_keys[key] = {"kind": kind, "ts": now, "status": "claimed"}
            return True

        return self._mutate(_do_claim)

    def mark_delivery(self, key: str, *, status: str) -> None:
        def _do_mark(data: dict[str, Any]) -> None:
            if key in data["monitor_keys"]:
                data["monitor_keys"][key]["status"] = status

        self._mutate(_do_mark)

    def get_capacity_stats(self) -> dict[str, Any]:
        def _get_stats(data: dict[str, Any]) -> dict[str, Any]:
            count = len(data.get("monitor_keys", {}))
            return {
                "monitor_keys_count": count,
                "monitor_keys_capacity": self.max_monitor_keys,
                "is_full": count >= self.max_monitor_keys,
            }

        return self._mutate(_get_stats)

    def save_baseline(self, baseline: dict[str, Any]) -> None:
        def _do_save(data: dict[str, Any]) -> None:
            baselines = data.get("baselines", {})
            scope = baseline.get("scope", "")
            rev = baseline.get("config_revision", "")
            key = f"{scope}:{rev}"

            if len(baselines) >= self.max_baselines and key not in baselines:
                oldest_k = next(iter(baselines.keys()))
                baselines.pop(oldest_k, None)

            baselines[key] = baseline
            data["baselines"] = baselines

        self._mutate(_do_save)

    def get_baseline(
        self, *, scope: str, config_revision: str
    ) -> dict[str, Any] | None:
        def _do_get(data: dict[str, Any]) -> dict[str, Any] | None:
            baselines = data.get("baselines", {})
            key = f"{scope}:{config_revision}"
            if key in baselines:
                return dict(baselines[key])
            for b in baselines.values():
                if (
                    b.get("scope") == scope
                    and b.get("config_revision") == config_revision
                ):
                    return dict(b)
            return None

        return self._mutate(_do_get)

    def save_suggestion(self, suggestion: dict[str, Any]) -> str:
        def _do_save(data: dict[str, Any]) -> str:
            s_list = data.get("suggestions", [])
            s_id = suggestion.get("id") or str(uuid.uuid4())
            record = dict(suggestion)
            record["id"] = s_id
            record.setdefault("status", "pending")
            record.setdefault("created_at", time.time())

            if len(s_list) >= self.max_suggestions:
                s_list.pop(0)
            s_list.append(record)
            data["suggestions"] = s_list
            return s_id

        return self._mutate(_do_save)

    def get_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        def _do_get(data: dict[str, Any]) -> dict[str, Any] | None:
            s_list = data.get("suggestions", [])
            for s in s_list:
                if s.get("id") == suggestion_id:
                    return dict(s)
            return None

        return self._mutate(_do_get)

    def list_suggestions(
        self, *, scope: str = "", status: str = ""
    ) -> list[dict[str, Any]]:
        def _do_list(data: dict[str, Any]) -> list[dict[str, Any]]:
            s_list = data.get("suggestions", [])
            matched = []
            for s in reversed(s_list):
                if scope and not _scope_matches(s.get("scope", ""), scope):
                    continue
                if status and s.get("status") != status:
                    continue
                matched.append(dict(s))
            return matched

        return self._mutate(_do_list)

    def dismiss(self, suggestion_id: str, *, scope: str = "") -> dict[str, Any]:
        def _do_dismiss(data: dict[str, Any]) -> dict[str, Any]:
            s_list = data.get("suggestions", [])
            target = None
            for s in s_list:
                if s.get("id") == suggestion_id:
                    if scope and not _scope_matches(s.get("scope", ""), scope):
                        raise ValueError("SCOPE_MISMATCH")
                    target = s
                    break
            if target is None:
                raise FileNotFoundError("SUGGESTION_NOT_FOUND")

            target["status"] = "dismissed"
            return dict(target)

        return self._mutate(_do_dismiss)

    def mark_suggestion_applied(
        self,
        suggestion_id: str,
        *,
        applied_by: str = "user",
        now: float | None = None,
    ) -> dict[str, Any]:
        if now is None:
            now = time.time()

        def _do_apply(data: dict[str, Any]) -> dict[str, Any]:
            s_list = data.get("suggestions", [])
            target = None
            for s in s_list:
                if s.get("id") == suggestion_id:
                    target = s
                    break
            if target is None:
                raise FileNotFoundError("SUGGESTION_NOT_FOUND")

            target["status"] = "applied"
            target["applied_at"] = now
            target["applied_by"] = applied_by
            return dict(target)

        return self._mutate(_do_apply)
