# Changelog

All notable changes to ppsp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

---

## [0.1.0] — 2026-04-26

First PyPI-ready release. The pipeline is complete end-to-end and has been
used in production on Sony a7R IV material.

### Added
- `--discover` / `-D`: variant discovery at reduced resolution with per-stack
  annotated collages; `--interactive` / `-I` runs a per-stack review loop with
  session tracking, convergence detection, and auto-apply.
- `--generate` / `-g`: full-resolution export of selected variants using a CSV,
  `variants/` folder, or an explicit chain list.
- `--gui`: early-stage tkinter GUI (`ppsp-gui` entry point) — Discover, Review,
  and Export tabs backed by the same `cmd_*` functions as the CLI.
- Variant chain format: `z_tier-enfuse[-tmo]-grading[-ct]`
  (e.g. `z25-sel4-m08n-dvi1-ctw5`).
- Resolution tiers: `z2` (micro), `z6` (quarter), `z25` (half), `z100` (full).
- Enfuse variants: `natu`, `sel3`, `sel4`, `sel6`, `focu`.
- TMO variants: 20 presets across Mantiuk, Drago, Reinhard02, Fattal, and
  Kim operators, with `*d` (operator default) and tuned variants per operator.
- Grading presets: `neut`, `dvi1`, `dvi2`, `brt1`, `brt2`.
- CT (color temperature) presets: `ctw4`–`ctw9`, `ctc4`–`ctc9`; orthogonal
  to grading, applied in a single ImageMagick `convert` call.
- Preset levels: `some`, `many`, `lots`, `tmod`, `all`.
- `--rename` / `-r`: EXIF-driven filename normalization + `ppsp_photos.csv`.
- `--organize` / `-o`: time-gap-based stack grouping into `*-stack/` folders.
- `--cull` / `-c`: labeled contact-sheet previews in `cull/`.
- `--prune` / `-P`: removes stack folders with no surviving cull preview.
- `--arws-enhance` / `-e`: batch ARW → enhanced JPG conversion.
- `--cleanup` / `-C`: removes z-tier discovery folders and `variants/`.
- Session tracking (`ppsp_session.json`): win counts, discard flag, convergence
  streak, active-chain narrowing.
- RAW conversion: `dcraw` preferred for Sony ARW; `darktable-cli` fallback.
- EXIF preservation: tags copied from middle stack frame to all processed outputs.
- `out-BBBB/` full-res export; `out-{PX}/` resized copy when `--resolution` set.
- `ppsp-gui` console script entry point.
- Optional `Pillow>=9.0` dependency for native JPEG thumbnails in the GUI.

### Changed
- `warm` and `dv1w` grading presets retired; color temperature is now a
  separate chain element (`ct*`), not embedded in grading.

---

## [0.0.1] — 2026-04-19

Initial working implementation (not published to PyPI).

### Added
- Core pipeline: rename → organize → cull → discover → generate.
- `dcraw` → `align_image_stack` → `enfuse` → `luminance-hdr-cli` → ImageMagick
  grading chain.
- First enfuse and TMO variant tables.
- `ppsp_photos.csv` output from rename step.
- `guide.md`: deep-dive reference for the underlying tools and preset rationale.

---

[Unreleased]: https://github.com/synsigma/ppsp/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/synsigma/ppsp/releases/tag/v0.1.0
[0.0.1]: https://github.com/synsigma/ppsp/releases/tag/v0.0.1
