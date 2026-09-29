"""Application logging setup kept separate from dashboard route code."""

from __future__ import annotations

import logging
from pathlib import Path


LOGGER_NAME = "bosshunter.runtime"


def configure_runtime_logging(data_dir: Path | str) -> logging.Logger:
    runtime_dir = Path(data_dir) / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    target = str((runtime_dir / "web.out.log").resolve())
    if not any(getattr(handler, "baseFilename", "") == target for handler in logger.handlers):
        handler = logging.FileHandler(target, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    return logger


def runtime_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
