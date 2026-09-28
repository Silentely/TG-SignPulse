"""通配（account_names 含 "*"）签到任务的删除语义测试。

核心回归：删除铺开到某账号的通配副本后，不得被 _expand_wildcard_tasks
重新铺开而「复活」；filter_related_task_infos 也不得只返回一份副本，
否则其余同名副本会在下次通配扩展时重新出现。
"""
from __future__ import annotations

from typing import Any, List, Optional, Sequence

import pytest

from backend.services.sign_task_group import filter_related_task_infos


def _norm(names: Optional[Sequence[Any]] = None, primary: Optional[str] = None) -> List[str]:
    out: List[str] = []
    for n in list(names or []):
        s = str(n or "").strip()
        if s and s not in out:
            out.append(s)
    if primary and primary not in out:
        out.append(primary)
    return out


class TestFilterRelatedSingleAccountWildcard:
    def test_single_account_copies_are_all_related(self):
        """无 group_id 的同名多副本必须整体返回，而非只返回 current 一份。"""
        tasks = [
            {"name": "wt", "account_name": "a", "account_names": ["*"]},
            {"name": "wt", "account_name": "b", "account_names": ["*"]},
        ]
        related = filter_related_task_infos(
            tasks, "wt", "a", normalize_account_names=_norm
        )
        assert {t["account_name"] for t in related} == {"a", "b"}

    def test_other_task_names_are_excluded(self):
        tasks = [
            {"name": "wt", "account_name": "a", "account_names": ["*"]},
            {"name": "wt", "account_name": "b", "account_names": ["*"]},
            {"name": "other", "account_name": "a", "account_names": ["a"]},
        ]
        related = filter_related_task_infos(
            tasks, "wt", "a", normalize_account_names=_norm
        )
        assert {t["account_name"] for t in related} == {"a", "b"}

    def test_group_id_still_scopes_to_group(self):
        """有 group_id 时仍按组收窄，不被新的同名兜底逻辑扩大。"""
        tasks = [
            {"name": "t", "account_name": "a", "account_names": ["a"], "task_group_id": "g1"},
            {"name": "t", "account_name": "b", "account_names": ["b"], "task_group_id": "g2"},
        ]
        related = filter_related_task_infos(
            tasks, "t", "a", normalize_account_names=_norm
        )
        assert [t["account_name"] for t in related] == ["a"]

    def test_multi_account_set_still_scopes_to_account_set(self):
        tasks = [
            {"name": "t", "account_name": "a", "account_names": ["a", "b"]},
            {"name": "t", "account_name": "c", "account_names": ["c"]},
        ]
        related = filter_related_task_infos(
            tasks, "t", "a", normalize_account_names=_norm
        )
        assert [t["account_name"] for t in related] == ["a"]

    def test_independent_single_account_tasks_are_not_merged(self):
        """不同账号各自创建的同名单账号任务相互独立，只应作用于当前副本。

        回归：兜底分支曾把所有同名副本当成同一任务集，删除账号 a 的任务会
        连带删掉账号 b 独立创建的同名任务。
        """
        tasks = [
            {"name": "daily", "account_name": "a", "account_names": ["a"]},
            {"name": "daily", "account_name": "b", "account_names": ["b"]},
        ]
        related = filter_related_task_infos(
            tasks, "daily", "a", normalize_account_names=_norm
        )
        assert [t["account_name"] for t in related] == ["a"]

    def test_sibling_wildcard_marker_still_groups(self):
        """当前副本已丢失 "*"、兄弟副本仍带通配标记时必须整体收拢。

        否则残留的 "*" 会在下一次扩展时把已删副本重新铺开，删除被撤销。
        """
        tasks = [
            {"name": "wild", "account_name": "a", "account_names": ["a"]},
            {"name": "wild", "account_name": "b", "account_names": ["*"]},
        ]
        related = filter_related_task_infos(
            tasks, "wild", "a", normalize_account_names=_norm
        )
        assert {t["account_name"] for t in related} == {"a", "b"}


class TestWildcardDeleteNotResurrected:
    """端到端：单账号期创建 → 加账号 → expand → delete → expand，目录不得复活。"""

    @pytest.fixture
    def service(self, tmp_path, monkeypatch):
        monkeypatch.setenv("APP_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setenv("SIGN_TASK_FORCE_IN_MEMORY", "1")
        from backend.core import config as config_module
        from backend.services import sign_tasks as sign_tasks_module
        from backend.services.sign_tasks import get_sign_task_service

        config_module.get_settings.cache_clear()
        # 服务是进程内单例：必须先清掉，否则会复用其他用例绑定过的 data_dir
        monkeypatch.setattr(sign_tasks_module, "_sign_task_service", None)
        svc = get_sign_task_service()
        svc.invalidate_tasks_cache()
        return svc

    @staticmethod
    def _accounts(monkeypatch, names):
        import backend.services.sign_tasks as st_module

        monkeypatch.setattr(st_module, "list_account_names", lambda: list(names))

    @staticmethod
    def _dirs(svc):
        out = {}
        if not svc.signs_dir.exists():
            return out
        for account_dir in svc.signs_dir.iterdir():
            if not account_dir.is_dir():
                continue
            for task_dir in account_dir.iterdir():
                if (task_dir / "config.json").exists():
                    out[(account_dir.name, task_dir.name)] = task_dir
        return out

    def test_delete_is_not_undone_by_reexpand(self, service, monkeypatch):
        svc = service
        # 1) 只有 acc1 时创建通配任务
        self._accounts(monkeypatch, ["acc1"])
        svc.create_task(
            task_name="wild",
            sign_at="08:00",
            chats=[],
            account_name="acc1",
            account_names=["*"],
        )
        assert set(self._dirs(svc)) == {("acc1", "wild")}

        # 2) 新增 acc2 → 通配扩展铺开
        self._accounts(monkeypatch, ["acc1", "acc2"])
        svc._expand_wildcard_tasks()
        assert set(self._dirs(svc)) == {("acc1", "wild"), ("acc2", "wild")}

        # 3) 从任一账号删除通配任务：全部同名副本作为一个任务集整体删除，
        #    否则残留副本里的 "*" 会把删除撤销
        assert svc.delete_task("wild", "acc2") is True
        assert set(self._dirs(svc)) == set()

        # 4) 再次扩展：没有任何副本残留，不得复活
        svc._expand_wildcard_tasks()
        svc.invalidate_tasks_cache()
        assert set(self._dirs(svc)) == set()

    def test_recreate_after_delete_restores_expansion(self, service, monkeypatch):
        """删除后显式重建，删除记录被清除，通配扩展恢复铺开。"""
        svc = service
        self._accounts(monkeypatch, ["acc1", "acc2"])
        svc.create_task(
            task_name="wild", sign_at="08:00", chats=[], account_name="acc1", account_names=["*"]
        )
        svc._expand_wildcard_tasks()
        assert set(self._dirs(svc)) == {("acc1", "wild"), ("acc2", "wild")}

        assert svc.delete_task("wild", "acc2") is True
        assert set(self._dirs(svc)) == set()

        # 重建后删除记录被清除，acc1/acc2 重新参与扩展
        svc.create_task(
            task_name="wild", sign_at="08:00", chats=[], account_name="acc1", account_names=["*"]
        )
        svc._expand_wildcard_tasks()
        assert set(self._dirs(svc)) == {("acc1", "wild"), ("acc2", "wild")}

    def test_delete_single_account_task_keeps_other_account_copy(self, service, monkeypatch):
        """端到端：删除某账号的单账号任务，不得连带删除其他账号的同名任务。

        回归：filter_related_task_infos 曾把所有同名副本整体收拢，导致
        delete_task(name, acc1) 把 acc2 独立创建的同名任务一并删除。
        """
        svc = service
        self._accounts(monkeypatch, ["acc1", "acc2"])
        svc.create_task(
            task_name="daily", sign_at="08:00", chats=[], account_name="acc1", account_names=["acc1"]
        )
        svc.create_task(
            task_name="daily", sign_at="08:00", chats=[], account_name="acc2", account_names=["acc2"]
        )
        assert set(self._dirs(svc)) == {("acc1", "daily"), ("acc2", "daily")}

        assert svc.delete_task("daily", "acc1") is True
        assert set(self._dirs(svc)) == {("acc2", "daily")}
