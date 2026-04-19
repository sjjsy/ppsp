# DESIGN.md — ppsp Developer and Architecture Reference

This document is for developers and maintainers of `ppsp`. It covers code organization, implementation decisions, data models, and testing strategy. For user-facing documentation — including the full variant parameter tables, naming convention, stack detection algorithm, CSV format, and collage layout — see [README.md](README.md). Docstrings and inline comments in the code should reference either document by section name rather than re-explaining things inline.

## Design principles

- **Standard library first.** Use only Python stdlib. The external Linux CLI tools are expected on the user's system; `ppsp` is an advanced convenience wrapper around them.
- **One command, one function.** Each CLI flag maps 1-to-1 to a `cmd_*` function. The argparse layer in `cli.py` does nothing except parse arguments and dispatch.
- **File-argument defaulting.** Every `cmd_*` function that accepts file arguments defaults to all matching files under `--source` when no explicit arguments are given.
- **Prerequisite checking at function boundaries.** Each `cmd_*` function verifies that its required inputs are present and in the right state. It either runs the prerequisite automatically (when inputs are unambiguous) or raises a clear error. It never silently assumes global state.
- **Stateful and resumable.** Every output is checked for existence before being computed. `--redo` forces re-execution of every product the command would produce, including intermediates.
- **Classes for domain objects, pure helper functions.** Use `Photo` and `Stack` dataclasses. Keep helper functions pure (inputs → output, no side effects). Keep `cmd_*` functions as thin orchestrators.
- **Extensibility over premature abstraction.** Add a new variant by adding one entry to a dict. Add a new pipeline step by adding one `cmd_*` function and one argparse entry. Generalize only when there are at least three concrete cases.
- **Concise docstrings.** Every class and function has a one-line summary docstring. For non-obvious logic, reference the relevant section of README.md or DESIGN.md by name rather than re-explaining inline.

## Project layout

```
ppsp/
├── src/ppsp/
│   ├── __init__.py
│   ├── cli.py          # argparse setup and dispatch to cmd_* functions
│   ├── commands.py     # cmd_* functions, one per pipeline step
│   ├── models.py       # Photo and Stack dataclasses
│   ├── rename.py       # compute_refined_name and collision-suffix logic
│   ├── stacking.py     # stack detection and organization
│   ├── processing.py   # enfuse, TMO, grading, collage assembly
│   ├── export.py       # out_full / out_web copying and resizing
│   ├── variants.py     # ENFUSE_VARIANTS, TMO_VARIANTS, GRADING_PRESETS dicts
│   └── util.py         # run_command, setup_logging, get_raw_converter
├── tests/
│   ├── conftest.py           # test_data skip fixture
│   ├── test_rename.py        # compute_refined_name, collision suffix, timestamp parsing
│   ├── test_stacking.py      # stack boundary detection with synthetic Photo objects
│   ├── test_variants.py      # variant level expansion, custom --variants parsing
│   ├── test_chain.py         # filename chain compose → parse round-trips
│   └── test_pipeline.py      # integration tests (skipped without test_data/)
├── test_data/          # gitignored; local Sony ARW + JPG pairs for integration tests
├── pyproject.toml
├── README.md           # user + technical reference
└── DESIGN.md           # this file
```

## CLI-to-function mapping

| CLI flag | Short | Function | Module |
|---|---|---|---|
| `--rename [FILES...]` | `-r` | `cmd_rename(files, source, default_model, default_lens, redo)` | `commands.py` |
| `--stacks-organize [FILES...]` | `-o` | `cmd_stacks_organize(files, source, gap, redo)` | `commands.py` |
| `--stacks-cull` | `-c` | `cmd_stacks_cull(source, quality, redo)` | `commands.py` |
| `--stacks-prune` | `-p` | `cmd_stacks_prune(source)` | `commands.py` |
| `--stacks-process [STACKS...]` | `-P` | `cmd_stacks_process(stacks, source, variants, fast, quality, redo)` | `commands.py` |
| `--generate FILES/CSV/TXT` | `-g` | `cmd_generate(targets, source, quality, redo)` | `commands.py` |
| `--arws-enhance [FILES...]` | `-e` | `cmd_arws_enhance(files, source, quality, redo)` | `commands.py` |
| `--cleanup` | `-C` | `cmd_cleanup(source)` | `commands.py` |

The full workflow (no command flag) calls these in sequence, prompting between steps unless `--batch` is set.

## Data models

### `Photo`

Represents a single image file after renaming.

```python
@dataclass
class Photo:
    path: Path
    filename: str           # canonical filename post-rename
    source_file: str        # original filename pre-rename
    timestamp: datetime     # from DateTimeOriginal
    model: str
    lens: str
    exposure_comp: float    # ExposureCompensation in EV
    focal_length: float     # mm
    fnumber: float
    white_balance: str
    ext: str                # lowercase
```

### `Stack`

Represents a group of `Photo` objects belonging to the same scene capture.

```python
@dataclass
class Stack:
    name: str               # e.g. "20260416095559-m4azzz-2126-stack"
    path: Path
    photos: list[Photo]
    stack_type: StackType   # HDR or FOCUS (enum)
```

`stack_type` is set by `detect_type()`: more than one distinct rounded `ExposureCompensation` value → `HDR`, otherwise → `FOCUS`.

### `ChainSpec`

Parsed representation of a variant chain extracted from a filename.

```python
@dataclass
class ChainSpec:
    z_tier: str             # "z100", "z25", or "z13"
    enfuse_id: str          # e.g. "sel3" or "focu"
    tmo_id: Optional[str]   # e.g. "fatt"; None for focus stacks
    grading_id: str         # e.g. "dvi2"
    web: bool               # True if the "-web" suffix is present
```

`parse_chain(filename) → ChainSpec` and `compose_chain(spec) → str` must be exact inverses. The chain composition order is fixed and documented in [README.md § Naming convention](README.md#naming-convention).

## EXIF preservation

After every RAW → JPG conversion:
```bash
exiftool -TagsFromFile <source> -all:all -overwrite_original <dest>
```
For fused/processed outputs, EXIF is copied from the **middle image** of the stack. `exiftool` errors are logged as `WARNING` but do not abort the pipeline (`check=False`).

## RAW conversion

`get_raw_converter()` returns `"dcraw"` if available, `"darktable-cli"` otherwise, `None` if neither is found. `dcraw` is preferred for better Sony ARW compatibility and true unsigned 16-bit output.

`dcraw` flags used for TIFF production:
```
-T    write TIFF
-4    linear 16-bit (unsigned)
-w    camera white balance
-q 3  AHD demosaic
-h    half-size (z25 only; omitted for z100)
-M    apply manufacturer colour matrix
```

For `z13`, the TIFF produced by `dcraw -h` is further resized with `mogrify -resize 50%`. For `darktable-cli`, the TIFF is produced directly and the `z13` resize is applied the same way.

## Variant dicts

`variants.py` exposes three module-level dicts. Entries are consumed by `processing.py`; they are never duplicated elsewhere. See [README.md § Variant system](README.md#variant-system) for the full parameter tables.

```python
ENFUSE_VARIANTS: dict[str, list[str]]   # id → list of enfuse CLI flags
TMO_VARIANTS:    dict[str, list[str]]   # id → list of luminance-hdr-cli flags
GRADING_PRESETS: dict[str, list[str]]   # id → list of ImageMagick arguments
```

Variant level presets (`some`/`many`/`all`) are defined as lists of IDs in the same module and consumed by `cmd_stacks_process` to expand the `--variants` argument.

## `--generate` chain execution

For each target filename, `cmd_generate` calls `parse_chain` then executes:

1. RAW → TIFF at the z-tier — skipped if TIFF exists and not `--redo`
2. `align_image_stack` — skipped if aligned TIFFs exist and not `--redo`
3. `enfuse` — skipped if enfuse TIFF exists and not `--redo`
4. `luminance-hdr-cli` TMO — skipped if TMO output exists (focus stacks: omitted)
5. ImageMagick grading → final JPG
6. Copy to `out_full/`; produce `out_web/` copy (resize 2048px max, quality 80, `-strip`)

`--redo` propagates through all steps, not just the final output.

## Testing strategy

`tests/conftest.py` provides a `test_data` fixture that marks any test using it as `pytest.mark.skipif` when `test_data/` is absent or empty. Running `pytest` without test data should produce zero failures, only skips.

**Unit tests** (no external tools or image files required):
- `test_rename.py` — `compute_refined_name`, collision suffix, timestamp parsing edge cases
- `test_stacking.py` — stack boundary detection with synthetic `Photo` sequences covering all five signals
- `test_variants.py` — level expansion (`some`/`many`/`all`), custom list parsing, cross-product generation
- `test_chain.py` — `parse_chain`/`compose_chain` round-trips for all valid chain patterns

**Integration tests** (require `test_data/`):
- `test_pipeline.py` — copies `test_data/` to a temp directory, then runs `cmd_rename`, `cmd_stacks_organize`, and `cmd_stacks_process` in sequence; asserts outputs exist with correct naming per the convention in README.md.

## Packaging

`pyproject.toml` uses the PEP 621 `[project]` table. Entry point: `ppsp = ppsp.cli:main`. Dev extras: `pytest`, `ruff`. Minimum Python: 3.8 (Ubuntu 20.04 LTS baseline). No data files ship with the package; `test_data/` is gitignored.

## Extensibility

- **New enfuse variant:** add one entry to `ENFUSE_VARIANTS` in `variants.py`; update the `some`/`many` preset lists if appropriate; document in README.md § Enfuse variants.
- **New TMO:** add to `TMO_VARIANTS`; update preset lists; document in README.md § Tone-mapping operators.
- **New grading preset:** add to `GRADING_PRESETS`; document in README.md § Color-grading presets.
- **New pipeline step:** implement `cmd_<noun>_<verb>` in `commands.py`, add the argparse entry in `cli.py`, document in README.md § Workflow and the CLI reference table, add a row to the mapping table above.
- **New raw converter:** extend `get_raw_converter()` and add a branch in `convert_raw_to_tiff()` in `util.py`.
