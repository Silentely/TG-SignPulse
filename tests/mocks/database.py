"""
数据库 Mock 对象

提供内存数据库会话和模拟数据库操作的辅助工具，
用于在不依赖真实数据库文件的情况下测试后端服务层。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_memory_engine():
    """创建内存 SQLite 引擎（用于测试）"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    return engine


def create_memory_session_factory(engine=None):
    """创建内存数据库的 session 工厂"""
    if engine is None:
        engine = create_memory_engine()
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


class MockDBSession:
    """
    模拟数据库会话

    记录所有 CRUD 操作以便断言，支持配置返回值。
    """

    def __init__(self):
        self.added: List[Any] = []
        self.committed: bool = False
        self.refreshed: List[Any] = []
        self.deleted: List[Any] = []
        self.closed: bool = False
        self._query_results: Dict[type, List[Any]] = {}

    def configure_query_results(self, model_class: type, results: List[Any]):
        """配置指定模型的查询返回结果"""
        self._query_results[model_class] = results

    def add(self, instance: Any):
        """添加对象到会话"""
        self.added.append(instance)

    def commit(self):
        """提交事务"""
        self.committed = True

    def refresh(self, instance: Any):
        """刷新对象"""
        self.refreshed.append(instance)

    def delete(self, instance: Any):
        """删除对象"""
        self.deleted.append(instance)

    def close(self):
        """关闭会话"""
        self.closed = True

    def rollback(self):
        """回滚事务"""
        pass

    def query(self, model_class: type):
        """模拟查询，返回配置的结果"""
        results = self._query_results.get(model_class, [])
        mock_query = MagicMock()
        mock_query.all.return_value = results
        mock_query.first.return_value = results[0] if results else None
        mock_query.filter.return_value = mock_query
        mock_query.filter_by.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.count.return_value = len(results)
        mock_query.one.return_value = results[0] if results else None
        mock_query.one_or_none.return_value = results[0] if len(results) == 1 else None
        return mock_query

    def execute(self, statement, **kwargs):
        """模拟执行 SQL 语句"""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_result.scalar.return_value = None
        mock_result.fetchone.return_value = None
        mock_result.fetchall.return_value = []
        return mock_result

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


@contextmanager
def mock_db_dependency(db_session: Optional[MockDBSession] = None):
    """
    模拟 FastAPI 的 get_db 依赖注入

    用法:
        with mock_db_dependency() as db:
            # db 是 MockDBSession 实例
            service = SomeService(db)
            ...
    """
    if db_session is None:
        db_session = MockDBSession()

    def override_get_db():
        try:
            yield db_session
        finally:
            db_session.close()

    yield db_session


class MockDatabasePatch:
    """
    上下文管理器，用于 patch 后端数据库模块

    用法:
        with MockDatabasePatch() as db_patch:
            db_patch.session.query(Account).all.return_value = [...]
    """

    def __init__(self):
        self.session = MockDBSession()
        self._patches: List[Any] = []

    def __enter__(self) -> MockDatabasePatch:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for p in self._patches:
            p.stop()
        self._patches.clear()

    def patch_session_factory(self):
        """patch get_session_local 返回模拟会话"""
        p = patch("backend.core.database.get_session_local")
        mock_factory = p.start()
        mock_factory.return_value = lambda: self.session
        self._patches.append(p)
        return mock_factory
