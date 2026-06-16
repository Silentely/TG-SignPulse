import logging
import os
import pathlib
from logging.handlers import RotatingFileHandler


class ExactLevelFilter(logging.Filter):
    def __init__(self, level: int):
        super().__init__()
        self.level = level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno == self.level


class MinLevelFilter(logging.Filter):
    def __init__(self, min_level: int):
        super().__init__()
        self.min_level = min_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno >= self.min_level


format_str = (
    "[%(levelname)s] [%(name)s] %(asctime)s %(filename)s %(lineno)s %(message)s"
)
formatter = logging.Formatter(format_str)


def configure_logger(
    name: str = "tg-signer",
    log_level: str = "INFO",
    log_dir: str | pathlib.Path = "logs",
    log_file: str | pathlib.Path = None,
    max_bytes: int = 1024 * 1024 * 3,
):
    level = log_level.strip().upper()
    level_no = logging.getLevelName(level)

    # 验证日志等级有效性
    if not isinstance(level_no, int):
        logging.warning(f"Invalid log_level '{log_level}', falling back to INFO")
        level_no = logging.INFO

    logger = logging.getLogger(name)
    logger.setLevel(level_no)
    logger.handlers.clear()
    logger.propagate = False

    console_handler = logging.StreamHandler()
    stream = getattr(console_handler, "stream", None)
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_dir = pathlib.Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_file or log_dir / f"{name}.log"
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_bytes,
        backupCount=10,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 修复逻辑：当前日志等级足够低时才创建分级日志文件
    # level_no <= logging.WARNING 表示当前等级能够记录 WARNING 及以上
    if level_no <= logging.WARNING:
        warn_file_handler = RotatingFileHandler(
            log_dir / "warn.log",
            maxBytes=max_bytes,
            backupCount=10,
            encoding="utf-8",
        )
        warn_file_handler.setLevel(logging.WARNING)
        warn_file_handler.addFilter(ExactLevelFilter(logging.WARNING))
        warn_file_handler.setFormatter(formatter)
        logger.addHandler(warn_file_handler)

    if level_no <= logging.ERROR:
        error_file_handler = RotatingFileHandler(
            log_dir / "error.log",
            maxBytes=max_bytes,
            backupCount=10,
            encoding="utf-8",
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.addFilter(MinLevelFilter(logging.ERROR))
        error_file_handler.setFormatter(formatter)
        logger.addHandler(error_file_handler)

    # 配置 Pyrogram 日志（如果启用）
    if os.environ.get("PYROGRAM_LOG_ON", "0") == "1":
        pyrogram_logger = logging.getLogger("pyrogram")
        pyrogram_logger.setLevel(level_no)  # 使用 level_no 而不是 level 字符串
        # 创建新的 handler 避免复用导致的重复输出
        pyrogram_handler = logging.StreamHandler()
        pyrogram_stream = getattr(pyrogram_handler, "stream", None)
        if hasattr(pyrogram_stream, "reconfigure"):
            try:
                pyrogram_stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
        pyrogram_handler.setFormatter(formatter)
        pyrogram_logger.addHandler(pyrogram_handler)

    return logger
