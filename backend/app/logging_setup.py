from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path


def configure_logging(data_dir: Path, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger("iris")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    if logger.handlers:
        return logger

    log_dir = Path(data_dir) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        log_dir / "iris.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger
