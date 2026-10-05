from unittest.mock import MagicMock, patch

from backend.services.sign_task_history_ops import SignTaskHistoryMixin


def test_empty_indexed_result_does_not_trigger_disk_fallback():
    mixin = SignTaskHistoryMixin()
    mixin.run_history_dir = MagicMock()
    mixin.list_tasks = MagicMock(return_value=[{"name": "task1", "account_name": "acc1"}])
    mixin._repair_mojibake = lambda s: s

    with patch("backend.services.sign_task_history_ops.ensure_history_index"), \
         patch("backend.services.sign_task_history_ops.list_recent_from_index", return_value=[]), \
         patch.object(mixin, "_load_history_entries", return_value=[]) as mock_fallback_scan:

        results = mixin.get_recent_history_logs(limit=20)
        assert results == []
        # 核心断言：patch 真实的 mixin._load_history_entries，断言绝不应该被回退调用！
        assert not mock_fallback_scan.called, "空结果引发了全盘扫描！"


def test_empty_indexed_result_filtered_does_not_trigger_disk_fallback():
    mixin = SignTaskHistoryMixin()
    mixin.run_history_dir = MagicMock()
    mixin.list_tasks = MagicMock(return_value=[{"name": "task1", "account_name": "acc1"}])
    mixin._repair_mojibake = lambda s: s

    with patch("backend.services.sign_task_history_ops.ensure_history_index"), \
         patch("backend.services.sign_task_history_ops.list_recent_from_index", return_value=[]), \
         patch.object(mixin, "_load_history_entries", return_value=[]) as mock_fallback_scan:

        results = mixin.get_filtered_history_logs(account_name="acc1", limit=20)
        assert results == []
        # 核心断言：筛选查询返回空列表时，不应回退到全盘扫描
        assert not mock_fallback_scan.called, "筛选空结果引发了全盘扫描！"


def test_index_error_triggers_disk_fallback():
    mixin = SignTaskHistoryMixin()
    mixin.run_history_dir = MagicMock()
    mixin.list_tasks = MagicMock(return_value=[{"name": "task1", "account_name": "acc1"}])
    mixin._repair_mojibake = lambda s: s

    with patch("backend.services.sign_task_history_ops.ensure_history_index"), \
         patch("backend.services.sign_task_history_ops.list_recent_from_index", side_effect=RuntimeError("index corrupted")), \
         patch.object(mixin, "_load_history_entries", return_value=[]) as mock_fallback_scan:

        results = mixin.get_recent_history_logs(limit=20)
        assert results == []
        assert mock_fallback_scan.called, "索引异常时必须回退到全盘扫描"


def test_index_error_filtered_triggers_disk_fallback():
    mixin = SignTaskHistoryMixin()
    mixin.run_history_dir = MagicMock()
    mixin.list_tasks = MagicMock(return_value=[{"name": "task1", "account_name": "acc1"}])
    mixin._repair_mojibake = lambda s: s

    with patch("backend.services.sign_task_history_ops.ensure_history_index"), \
         patch("backend.services.sign_task_history_ops.list_recent_from_index", side_effect=RuntimeError("index corrupted")), \
         patch.object(mixin, "_load_history_entries", return_value=[]) as mock_fallback_scan:

        results = mixin.get_filtered_history_logs(account_name="acc1", limit=20)
        assert results == []
        assert mock_fallback_scan.called, "筛选索引异常时必须回退到全盘扫描"
