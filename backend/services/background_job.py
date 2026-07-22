"""
可恢复的长任务 Job 基类。

用于批量运维类操作（加退群、迁移、扫描等）的统一状态机：
- 状态：running / canceling / canceled / completed / failed
- JSON 落盘，服务重启后将未结束任务标为 failed
- 环形日志、进度计数、可取消

签到 run 仍使用 sign_task_run_status；本模块面向「分钟级」运维作业。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger("backend.background_job")

ACTIVE_STATUSES: Set[str] = {"running", "canceling"}
FINAL_STATUSES: Set[str] = {"completed", "canceled", "failed"}
DEFAULT_MAX_LOGS = 1000
DEFAULT_MAX_HISTORY = 50


def utc_now_iso() -> str:
    """UTC ISO8601（秒精度，Z 后缀）。"""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def public_job_view(job: Dict[str, Any]) -> Dict[str, Any]:
    """过滤内部字段（以下划线开头）后返回可对外暴露的 job 视图。"""
    return {key: value for key, value in job.items() if not str(key).startswith("_")}


class BackgroundJobStore:
    """
    基于目录的 Job 存储与生命周期管理。

    子类或调用方负责真正的业务执行；本类提供：
    create / list / get / cancel / complete / fail / append_log / persist。
    """

    def __init__(
        self,
        root: Path,
        *,
        max_logs: int = DEFAULT_MAX_LOGS,
        max_history: int = DEFAULT_MAX_HISTORY,
        restart_error: str = "服务重启，原任务已中断",
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_logs = max(1, int(max_logs))
        self.max_history = max(1, int(max_history))
        self.restart_error = restart_error
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._load_jobs()

    def _job_path(self, job_id: str) -> Path:
        return self.root / f"{job_id}.json"

    def _write_job(self, job: Dict[str, Any]) -> None:
        payload = public_job_view(job)
        path = self._job_path(str(job["job_id"]))
        temp = path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(path)

    def _load_jobs(self) -> None:
        loaded: List[Dict[str, Any]] = []
        for path in self.root.glob("*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict) or not value.get("job_id"):
                continue
            if value.get("status") in ACTIVE_STATUSES:
                value["status"] = "failed"
                value["error"] = self.restart_error
                value["finished_at"] = utc_now_iso()
                value["updated_at"] = value["finished_at"]
                logs = value.setdefault("logs", [])
                logs.append(
                    {
                        "time": value["finished_at"],
                        "level": "error",
                        "message": self.restart_error,
                        "ref": None,
                    }
                )
                if len(logs) > self.max_logs:
                    del logs[: -self.max_logs]
                try:
                    path.write_text(
                        json.dumps(value, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError:
                    logger.warning("Failed to persist interrupted job %s", path)
            loaded.append(value)
        loaded.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
        self.jobs = {str(item["job_id"]): item for item in loaded[: self.max_history]}

    def create_job(
        self,
        *,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        progress: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """创建 running 状态 job 并落盘。"""
        now = utc_now_iso()
        job_id = uuid.uuid4().hex
        job: Dict[str, Any] = {
            "job_id": job_id,
            "kind": str(kind or "generic"),
            "status": "running",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "progress": dict(progress or {"total": 0, "done": 0}),
            "summary": {},
            "results": [],
            "logs": [],
            "error": None,
            "payload": dict(payload or {}),
        }
        self.jobs[job_id] = job
        self._write_job(job)
        self._trim_history()
        return public_job_view(job)

    def _trim_history(self) -> None:
        if len(self.jobs) <= self.max_history:
            return
        ordered = sorted(
            self.jobs.values(),
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )
        keep = {str(item["job_id"]) for item in ordered[: self.max_history]}
        for job_id in list(self.jobs.keys()):
            if job_id in keep:
                continue
            self.jobs.pop(job_id, None)
            path = self._job_path(job_id)
            try:
                if path.exists():
                    path.unlink()
            except OSError:
                pass

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.jobs.get(str(job_id or ""))
        return public_job_view(job) if job else None

    def list_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit or 20), self.max_history))
        ordered = sorted(
            self.jobs.values(),
            key=lambda item: str(item.get("created_at") or ""),
            reverse=True,
        )
        return [public_job_view(item) for item in ordered[:limit]]

    def append_log(
        self,
        job_id: str,
        level: str,
        message: str,
        *,
        ref: Optional[str] = None,
        persist: bool = True,
    ) -> None:
        job = self.jobs.get(str(job_id or ""))
        if not job:
            return
        logs = job.setdefault("logs", [])
        logs.append(
            {
                "time": utc_now_iso(),
                "level": str(level or "info"),
                "message": str(message or ""),
                "ref": ref,
            }
        )
        if len(logs) > self.max_logs:
            del logs[: -self.max_logs]
        job["updated_at"] = utc_now_iso()
        if persist:
            self._write_job(job)

    def update_progress(
        self,
        job_id: str,
        *,
        done: Optional[int] = None,
        total: Optional[int] = None,
        extra: Optional[Dict[str, int]] = None,
        persist: bool = True,
    ) -> None:
        job = self.jobs.get(str(job_id or ""))
        if not job:
            return
        progress = job.setdefault("progress", {})
        if done is not None:
            progress["done"] = int(done)
        if total is not None:
            progress["total"] = int(total)
        if extra:
            for key, value in extra.items():
                progress[str(key)] = int(value)
        job["updated_at"] = utc_now_iso()
        if persist:
            self._write_job(job)

    def request_cancel(self, job_id: str) -> bool:
        """请求取消；若已终态返回 False。"""
        job = self.jobs.get(str(job_id or ""))
        if not job or job.get("status") not in ACTIVE_STATUSES:
            return False
        if job.get("status") == "canceling":
            return True
        job["status"] = "canceling"
        job["updated_at"] = utc_now_iso()
        self.append_log(job_id, "info", "收到取消请求", persist=False)
        self._write_job(job)
        return True

    def is_cancel_requested(self, job_id: str) -> bool:
        job = self.jobs.get(str(job_id or ""))
        return bool(job and job.get("status") == "canceling")

    def mark_completed(
        self,
        job_id: str,
        *,
        summary: Optional[Dict[str, Any]] = None,
        results: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        job = self.jobs.get(str(job_id or ""))
        if not job:
            return
        # 若在收尾前已请求取消，记为 canceled
        final = "canceled" if job.get("status") == "canceling" else "completed"
        job["status"] = final
        now = utc_now_iso()
        job["finished_at"] = now
        job["updated_at"] = now
        if summary is not None:
            job["summary"] = dict(summary)
        if results is not None:
            job["results"] = list(results)
        self.append_log(
            job_id,
            "info",
            "任务已取消" if final == "canceled" else "任务已完成",
            persist=False,
        )
        self._write_job(job)

    def mark_failed(self, job_id: str, error: str) -> None:
        job = self.jobs.get(str(job_id or ""))
        if not job:
            return
        now = utc_now_iso()
        job["status"] = "failed"
        job["error"] = str(error or "unknown error")
        job["finished_at"] = now
        job["updated_at"] = now
        self.append_log(job_id, "error", job["error"], persist=False)
        self._write_job(job)

    def attach_task(self, job_id: str, task: asyncio.Task) -> None:
        self._tasks[str(job_id)] = task

        def _cleanup(done: asyncio.Task) -> None:
            self._tasks.pop(str(job_id), None)
            # 未显式收尾时兜底
            job = self.jobs.get(str(job_id))
            if not job or job.get("status") not in ACTIVE_STATUSES:
                return
            if done.cancelled():
                self.mark_failed(job_id, "任务被取消")
                return
            exc = done.exception()
            if exc is not None:
                self.mark_failed(job_id, str(exc))

        task.add_done_callback(_cleanup)

    def start_background(
        self,
        job_id: str,
        coro_factory: Callable[[], Any],
        *,
        name: Optional[str] = None,
    ) -> asyncio.Task:
        """启动后台协程并挂到 job 上。"""
        task = asyncio.create_task(coro_factory(), name=name or f"bg-job-{job_id}")
        self.attach_task(job_id, task)
        return task
