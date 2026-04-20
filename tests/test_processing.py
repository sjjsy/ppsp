"""Unit tests for processing.py — companion deduplication and chain-spec dispatch."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ppsp.models import ChainSpec, Photo
from ppsp.processing import _deduplicate_companions, _run_chain_specs

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


# ---------------------------------------------------------------------------
# _run_chain_specs
# ---------------------------------------------------------------------------


def _make_mid_photo() -> Photo:
    return Photo(
        path=Path("mid.arw"),
        filename="mid.arw",
        source_file="mid.arw",
        timestamp=_BASE_TS,
        model="",
        lens="",
        exposure_comp=0.0,
        focal_length=0.0,
        fnumber=0.0,
        white_balance="",
        ext=".arw",
    )


class TestRunChainSpecs:
    """Test _run_chain_specs with mocked tool calls."""

    def _make_spec(self, enfuse_id: str, tmo_id: str | None, grading_id: str) -> ChainSpec:
        return ChainSpec(z_tier="", enfuse_id=enfuse_id, tmo_id=tmo_id, grading_id=grading_id)

    def _call(self, tmp_path, specs, **kwargs):
        """Helper: call _run_chain_specs with output_dir = tmp_path/z25."""
        output_dir = tmp_path / "z25"
        output_dir.mkdir()
        generated: list = []
        _run_chain_specs(
            aligned=[tmp_path / "aligned_0.tif", tmp_path / "aligned_1.tif"],
            output_dir=output_dir,
            stack_name="20260416-cam-0001-stack",
            z_tier="z25",
            chain_specs=specs,
            quality=80,
            mid_photo=_make_mid_photo(),
            redo=False,
            generated=generated,
            **kwargs,
        )
        return generated

    @patch("ppsp.processing.apply_grading", return_value=True)
    @patch("ppsp.processing.run_tmo", return_value=True)
    @patch("ppsp.processing.run_enfuse", return_value=True)
    @patch("ppsp.processing._copy_exif")
    def test_three_chain_specs_produce_three_outputs(
        self, mock_exif, mock_enfuse, mock_tmo, mock_grading, tmp_path
    ):
        specs = [
            self._make_spec("sel4", "fatt", "dvi1"),
            self._make_spec("sel4", "fatt", "neut"),
            self._make_spec("sel4", "ma06", "dvi1"),
        ]
        generated = self._call(tmp_path, specs)
        assert len(generated) == 3
        assert any("sel4-fatt-dvi1" in g for g in generated)
        assert any("sel4-fatt-neut" in g for g in generated)
        assert any("sel4-ma06-dvi1" in g for g in generated)

    @patch("ppsp.processing.apply_grading", return_value=True)
    @patch("ppsp.processing.run_tmo", return_value=True)
    @patch("ppsp.processing.run_enfuse", return_value=True)
    @patch("ppsp.processing._copy_exif")
    def test_shared_enfuse_step_called_once_per_unique_id(
        self, mock_exif, mock_enfuse, mock_tmo, mock_grading, tmp_path
    ):
        """Two specs sharing the same enfuse_id target the same temp TIFF path."""
        specs = [
            self._make_spec("sel4", "fatt", "dvi1"),
            self._make_spec("sel4", "fatt", "neut"),
        ]
        self._call(tmp_path, specs)
        enfuse_calls = mock_enfuse.call_args_list
        assert len(enfuse_calls) == 2
        tif_paths = [c.args[1] for c in enfuse_calls]
        assert tif_paths[0] == tif_paths[1], "Both specs must reuse the same enfuse temp TIFF"

    @patch("ppsp.processing.apply_grading", return_value=True)
    @patch("ppsp.processing.run_enfuse", return_value=True)
    @patch("ppsp.processing._copy_exif")
    def test_no_tmo_spec_does_not_call_run_tmo(
        self, mock_exif, mock_enfuse, mock_grading, tmp_path
    ):
        specs = [self._make_spec("natu", None, "neut")]
        with patch("ppsp.processing.run_tmo") as mock_tmo:
            generated = self._call(tmp_path, specs)
            mock_tmo.assert_not_called()
        assert len(generated) == 1
        assert "natu-neut" in generated[0]

    @patch("ppsp.processing.apply_grading", return_value=True)
    @patch("ppsp.processing.run_tmo", return_value=True)
    @patch("ppsp.processing.run_enfuse", return_value=False)  # enfuse fails
    @patch("ppsp.processing._copy_exif")
    def test_enfuse_failure_skips_spec(
        self, mock_exif, mock_enfuse, mock_tmo, mock_grading, tmp_path
    ):
        specs = [self._make_spec("sel4", "fatt", "dvi1")]
        generated = self._call(tmp_path, specs)
        assert generated == []
        mock_tmo.assert_not_called()
        mock_grading.assert_not_called()
