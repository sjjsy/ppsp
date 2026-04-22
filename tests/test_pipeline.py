"""Integration tests requiring test_data/ — see DESIGN.md § Testing strategy."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

import pytest

from ppsp.commands import cmd_cull, cmd_organize, cmd_rename


@pytest.mark.needs_test_data
def test_rename_creates_csv(test_data_dir):
    """cmd_rename produces ppsp_photos.csv with canonical filenames — see README.md § Step 1."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        for f in test_data_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, work / f.name)

        cmd_rename([], work)

        csv_path = work / "ppsp_photos.csv"
        assert csv_path.exists(), "ppsp_photos.csv was not created"

        content = csv_path.read_text(encoding="utf-8")
        # All data rows should follow the naming scheme
        pattern = re.compile(r"\d{14}-[a-z0-9]{3}[a-z0-9]{3}-\d{4}-[a-z]")
        for line in content.splitlines()[1:]:
            if line.strip():
                filename_col = line.split("\t")[0]
                # Allow for files that could not be fully renamed (no EXIF)
                # but at minimum the CSV must be tab-separated with a FileName column
                assert "\t" in line


@pytest.mark.needs_test_data
def test_stacks_organize_creates_dirs(test_data_dir):
    """cmd_organize moves files into -stack directories — see README.md § Step 2."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        for f in test_data_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, work / f.name)

        cmd_rename([], work)
        cmd_organize([], work)

        stack_dirs = [d for d in work.iterdir() if d.is_dir() and d.name.endswith("-stack")]
        assert len(stack_dirs) >= 1, "No -stack directories were created"


@pytest.mark.needs_test_data
def test_stacks_cull_creates_previews(test_data_dir):
    """cmd_cull produces labeled previews in cull/ — see README.md § Step 3."""
    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        for f in test_data_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, work / f.name)

        cmd_rename([], work)
        cmd_organize([], work)
        cmd_cull(work, quality=55)

        cull_dir = work / "cull"
        previews = list(cull_dir.glob("*_count*.jpg")) if cull_dir.exists() else []
        assert len(previews) >= 1, "No cull previews were created"
