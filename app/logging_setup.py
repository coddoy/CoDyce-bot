"""Configure stderr + rotating file logging for Windows and Linux."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FILENAME = "bot.log"
MAX_BYTES = 5 * 1024 * 1024  # 5 MB
BACKUP_COUNT = 5
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def configure_logging(
    level: str = "INFO",
    *,
    log_dir: Path | str | None = None,
) -> Path:
    """Attach stderr and rotating file handlers to the root logger.

    Returns the directory where log files are written.
    """
    directory = Path(log_dir) if log_dir is not None else DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)

    resolved_level = getattr(logging, str(level).upper(), logging.INFO)
    formatter = logging.Formatter(LOG_FORMAT)

    root = logging.getLogger()
    root.setLevel(resolved_level)
    root.handlers.clear()

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        directory / LOG_FILENAME,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    logging.info("Logging to %s (level=%s)", directory / LOG_FILENAME, logging.getLevelName(resolved_level))
    return directory


__all__ = ["DEFAULT_LOG_DIR", "LOG_FILENAME", "configure_logging"]
