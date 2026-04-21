"""Shared utilities: logging, subprocess wrapper, raw-converter detection — see DESIGN.md."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from typing import List, Optional, Union

_logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure dual FileHandler + StreamHandler logging — see DESIGN.md § Logging."""
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
    """Run a subprocess, log elapsed time if >4 s, log stdout at DEBUG — see DESIGN.md."""
    if shell:
        display = cmd if isinstance(cmd, str) else " ".join(str(x) for x in cmd)
    else:
        display = " ".join(str(x) for x in cmd)

    logging.info("Running: %s  # %s", display, desc)
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
            logging.info("  %.1fs taken by the command (%s)  # %s", elapsed, display.split(' ')[0], desc)
    except subprocess.CalledProcessError as exc:
        logging.error("Failed: %s", exc)
        if check:
            raise
    return rv


def get_raw_converter() -> Optional[str]:
    """Return 'dcraw', 'darktable-cli', or None — see DESIGN.md § RAW conversion."""
    if shutil.which("dcraw"):
        return "dcraw"
    if shutil.which("darktable-cli"):
        return "darktable-cli"
    return None
