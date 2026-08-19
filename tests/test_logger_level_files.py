"""
分级日志文件过滤语义测试

覆盖 tg_signer/logger.py 的 configure_logger：
- warn.log 应收 WARNING 及以上（含 ERROR/CRITICAL，完整问题视图）
- error.log 应收 ERROR 及以上
- 两文件均不混入 INFO/DEBUG
"""

import logging
import tempfile
from pathlib import Path

from tg_signer.logger import MinLevelFilter, configure_logger


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


class TestLevelFileFiltering:
    def test_warn_log_contains_warning_and_above(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            logger = configure_logger(name="t1", log_level="INFO", log_dir=log_dir)
            logger.info("info-line")
            logger.warning("warn-line")
            logger.error("error-line")
            logger.critical("critical-line")
            # 手动 flush 让 RotatingFileHandler 落盘
            for h in logger.handlers:
                h.flush()

            warn_lines = _read_lines(log_dir / "warn.log")
            assert any("warn-line" in line for line in warn_lines)
            assert any("error-line" in line for line in warn_lines)
            assert any("critical-line" in line for line in warn_lines)
            # 分级文件不含 INFO 噪音
            assert not any("info-line" in line for line in warn_lines)

            error_lines = _read_lines(log_dir / "error.log")
            assert any("error-line" in line for line in error_lines)
            assert any("critical-line" in line for line in error_lines)
            # error.log 不收 WARNING 与 INFO
            assert not any("warn-line" in line for line in error_lines)
            assert not any("info-line" in line for line in error_lines)

    def test_error_level_skips_warn_file(self):
        """ERROR 级配置下收不到 WARNING 记录，不创建 warn.log；error.log 正常创建。"""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            configure_logger(name="t2", log_level="ERROR", log_dir=log_dir)
            assert not (log_dir / "warn.log").exists()
            assert (log_dir / "error.log").exists()

    def test_info_level_creates_grade_files(self):
        """INFO 级配置下 WARNING/ERROR 均能被记录，分级文件都会创建。"""
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp)
            configure_logger(name="t3", log_level="INFO", log_dir=log_dir)
            assert (log_dir / "warn.log").exists()
            assert (log_dir / "error.log").exists()


class TestMinLevelFilter:
    def test_filters_below_min_level(self):
        f = MinLevelFilter(logging.WARNING)
        assert f.filter(_record(logging.INFO)) is False
        assert f.filter(_record(logging.WARNING)) is True
        assert f.filter(_record(logging.ERROR)) is True


def _record(level: int) -> logging.LogRecord:
    return logging.LogRecord(
        name="t", level=level, pathname=__file__, lineno=1,
        msg="x", args=(), exc_info=None,
    )
