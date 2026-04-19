"""Unit tests for processing.py companion deduplication — see DESIGN.md § Testing strategy."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from ppsp.models import Photo
from ppsp.processing import _deduplicate_companions

_BASE_TS = datetime(2026, 4, 16, 10, 0, 0)


def make_photo(stem: str, ext: str, offset_sec: float = 0.0, path: Path | None = None) -> Photo:
    filename = f"{stem}{ext}"
    return Photo(
        path=path or Path(filename),
        filename=filename,
        source_file=filename,
        timestamp=_BASE_TS + timedelta(seconds=offset_sec),
        model="ILCE-7RM4",
        lens="SEL1635GM",
        exposure_comp=0.0,
        focal_length=35.0,
        fnumber=8.0,
        white_balance="Daylight",
        ext=ext,
    )


class TestDeduplicateCompanions:
    def test_raw_jpg_pair_keeps_raw(self):
        arw = make_photo("20260416-cam-0001-a", ".arw")
        jpg = make_photo("20260416-cam-0001-a", ".jpg")
        result = _deduplicate_companions([arw, jpg])
        assert len(result) == 1
        assert result[0].ext == ".arw"

    def test_no_companions_unchanged(self):
        photos = [
            make_photo("20260416-cam-0001-a", ".arw", offset_sec=0),
            make_photo("20260416-cam-0002-a", ".arw", offset_sec=2),
            make_photo("20260416-cam-0003-a", ".arw", offset_sec=4),
        ]
        result = _deduplicate_companions(photos)
        assert len(result) == 3

    def test_multiple_pairs_each_deduplicated(self):
        photos = [
            make_photo("stem-0001", ".arw", offset_sec=0),
            make_photo("stem-0001", ".jpg", offset_sec=0),
            make_photo("stem-0002", ".arw", offset_sec=2),
            make_photo("stem-0002", ".jpg", offset_sec=2),
            make_photo("stem-0003", ".arw", offset_sec=4),
            make_photo("stem-0003", ".jpg", offset_sec=4),
        ]
        result = _deduplicate_companions(photos)
        assert len(result) == 3
        assert all(p.ext == ".arw" for p in result)

    def test_result_sorted_by_timestamp(self):
        photos = [
            make_photo("stem-0003", ".arw", offset_sec=4),
            make_photo("stem-0001", ".arw", offset_sec=0),
            make_photo("stem-0002", ".arw", offset_sec=2),
        ]
        result = _deduplicate_companions(photos)
        timestamps = [p.timestamp for p in result]
        assert timestamps == sorted(timestamps)

    def test_real_test_data_companions(self, test_data_dir):
        """With actual test_data/ ARW+JPG pairs, dedup keeps only ARW files."""
        photos = []
        for f in sorted(test_data_dir.iterdir()):
            if f.suffix.lower() in (".arw", ".jpg"):
                photos.append(make_photo(f.stem, f.suffix.lower(), path=f))

        result = _deduplicate_companions(photos)

        stems_in = {Path(p.filename).stem for p in photos}
        stems_out = {Path(p.filename).stem for p in result}
        assert stems_in == stems_out, "All stems should be represented after dedup"
        assert len(result) == len(stems_in), "Exactly one file per stem"
        assert all(p.ext == ".arw" for p in result), "ARW preferred over JPG companions"

    def test_jpg_only_group_survives(self):
        """When there is no raw companion, the lone JPEG is kept."""
        jpg = make_photo("stem-only-jpg", ".jpg")
        result = _deduplicate_companions([jpg])
        assert len(result) == 1
        assert result[0].ext == ".jpg"
