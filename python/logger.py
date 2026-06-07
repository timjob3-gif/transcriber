"""Логгер транскрибатора. Пишет в %APPDATA%/Transcriber/transcriber.log"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup() -> logging.Logger:
    log = logging.getLogger("transcriber")
    if log.handlers:
        return log
    log.setLevel(logging.DEBUG)

    log_dir = Path(os.environ.get("APPDATA", Path.home())) / "Transcriber"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "transcriber.log"

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s  %(message)s",
        datefmt="%H:%M:%S",
    )

    fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    log.addHandler(fh)

    return log


log = setup()
