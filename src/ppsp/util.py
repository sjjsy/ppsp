"""Shared utilities: logging, subprocess wrapper, raw-converter detection — see design.md."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from typing import List, Optional, Union

_logger = logging.getLogger(__name__)

# Custom log level for shell command lines — between INFO (20) and WARNING (30).
CMD: int = 25
logging.addLevelName(CMD, "CMD")

# ANSI colour codes
_RESET = "\033[0m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_BOLD_RED = "\033[1;31m"

_LEVEL_COLOR = {
    logging.DEBUG: _DIM,
    logging.INFO: "",
    CMD: _CYAN,
    logging.WARNING: _YELLOW,
    logging.ERROR: _RED,
    logging.CRITICAL: _BOLD_RED,
}


class _ColoredFormatter(logging.Formatter):
    """Formatter that dims the timestamp+level prefix and colours the message per level."""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, self.datefmt)
        prefix = f"{_DIM}{ts} | {record.levelname:<8} |{_RESET} "
        color = _LEVEL_COLOR.get(record.levelno, "")
        msg = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            msg = msg + "\n" + record.exc_text
        if record.stack_info:
            msg = msg + "\n" + self.formatStack(record.stack_info)
        return f"{prefix}{color}{msg}{_RESET if color else ''}"


def setup_logging(verbose: bool = False) -> None:
    """Configure dual FileHandler + StreamHandler logging — see design.md § Logging."""
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s | %(levelname)-8s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    if root.handlers:
        root.handlers.clear()

    root.setLevel(level)

    fh = logging.FileHandler("ppsp.log", mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(fmt, datefmt))

    sh = logging.StreamHandler()
    sh.setLevel(level)
    if sys.stderr.isatty():
        sh.setFormatter(_ColoredFormatter(datefmt=datefmt))
    else:
        sh.setFormatter(logging.Formatter(fmt, datefmt))

    root.addHandler(fh)
    root.addHandler(sh)

    logging.info("=" * 80)
    logging.info("ppsp started")


def run_command(
    cmd: Union[List[str], str],
    desc: str,
    check: bool = True,
    shell: bool = False,
) -> Optional[subprocess.CompletedProcess]:
    """Run a subprocess, log elapsed time if >4 s, log stdout at DEBUG — see design.md."""
    if shell:
        display = cmd if isinstance(cmd, str) else " ".join(str(x) for x in cmd)
    else:
        display = " ".join(str(x) for x in cmd)

    logging.log(CMD, "Running: %s  # %s", display, desc)
    start = time.perf_counter()
    rv = None
    try:
        rv = subprocess.run(cmd, capture_output=True, text=True, check=check, shell=shell)
        if rv.stdout:
            logging.debug(rv.stdout.strip())
        if rv.stderr:
            logging.warning(rv.stderr.strip())
        elapsed = time.perf_counter() - start
        if elapsed > 4:
            logging.info("  %.1fs taken by %s", elapsed, desc)
    except subprocess.CalledProcessError as exc:
        logging.error("Failed: %s", exc)
        if check:
            raise
    return rv


def get_raw_converter() -> Optional[str]:
    """Return 'dcraw', 'darktable-cli', or None — see design.md § RAW conversion."""
    if shutil.which("dcraw"):
        return "dcraw"
    if shutil.which("darktable-cli"):
        return "darktable-cli"
    return None
