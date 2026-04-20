# ppsp — Post Photoshoot Processing

A CLI tool for real-estate and architectural photographers who shoot 500+ bracketed images per session and publish 10–20 polished finals. `ppsp` automates the tedious mechanical work — renaming, organizing, stacking, fusing, grading — while keeping you in control of every creative decision.

## Motivation

A typical architectural session produces hundreds of HDR brackets and focus stacks.
The optimum tone-mapping and color-grading parameters are impossible to know upfront, so you end up generating dozens of variants per image.
`ppsp` speeds through that discovery phase at reduced resolution, presents the candidates in labeled collages, then generates only the keepers at full quality — with a single command.

Key design goals:

- **Minimize human time.** Make every choice among clearly prepared options, not from scratch.
- **Minimize processing time.** Variant discovery runs at reduced resolution (z25 or z13); full-quality output is generated only for selected results.
- **Stateful and resumable.** Every step automatically skips outputs that already exist. Pass `--redo` to force a step to regenerate even existing outputs.
- **Verbose and transparent.** Elapsed-time logging at every step so you can estimate remaining time. After the project, the logs can be archived along with the final outputs and possibly the original raw data.

Disclaimer: As of 2026-04-19, this tool has been written and used by only one Linux geek with a Sony a7R IV. Feel free to test this, critique it, and contribute to the project!

## System requirements

`ppsp` wraps standard Linux CLI tools. Install them once:

| Tool | Purpose |
|---|---|
| `exiftool` | EXIF read / write |
| `dcraw` (preferred) or `darktable-cli` | Sony ARW → TIFF conversion |
| `imagemagick` (`convert`, `mogrify`) | Image processing, collage, grading |
| `align_image_stack` (from `hugin`) | Stack alignment |
| `enfuse` (from `hugin-tools`) | Exposure / focus fusion |
| `luminance-hdr-cli` | Tone-mapping |

Ubuntu / Debian:
```bash
sudo apt install exiftool dcraw imagemagick hugin-tools luminance-hdr
```

Python ≥ 3.8.

## Installation

```bash
pip install ppsp
```

This installs the `ppsp` command globally.

## Quickstart

```bash
# Interactive full workflow
ppsp --source /path/to/shoot/

# Fully automated (no prompts)
ppsp --source /path/to/shoot/ --batch
```

## Processing flow and command reference

Running `ppsp` without a command flag walks you through all steps interactively. Every step can also be invoked individually. All file-accepting commands default to all matching files under `--source` (or the current directory) when no files are given explicitly.

| Step | Command | Short | Description |
|---|---|---|---|
| 1 | `--rename [FILES...]` | `-r` | Normalize filenames + write `ppsp_photos.csv` |
| 2 | `--stacks-organize [FILES...]` | `-o` | Group files into per-stack folders |
| 3 | `--stacks-cull` | `-c` | Generate labeled culling previews in `cull/` |
| 4 | `--stacks-prune` | `-p` | Remove stack folders with no surviving preview |
| 5 | `--stacks-process [STACKS...]` | `-P` | Variant discovery at reduced resolution + collage |
| 6 | *(manual)* | | Edit `ppsp_generate.csv` — mark variants with `x` |
| 7 | `--generate FOLDER/FILES/CSV/TXT` | `-g` | Generate variants from chain specifications |
| — | `--arws-enhance [FILES...]` | `-e` | Convert ARW files to enhanced JPGs |
| — | `--cleanup` | `-C` | Remove intermediate TIFFs from stack folders |

**Generate options** — apply to `--generate`:

| Flag | Short | Default | Description |
|---|---|---|---|
| `--half` | | off | Generate at z25 instead of z100 — reuses discovery intermediates, much faster |

**Global options** — apply to all commands:

| Flag | Short | Default | Description |
|---|---|---|---|
| `--source DIR` | `-s` | `.` | Directory containing shoot images |
| `--quality INT` | `-q` | `80` | JPEG quality for all internal conversions |
| `--batch` | `-b` | off | Skip all interactive prompts |
| `--verbose` | `-v` | off | Debug-level logging |
| `--redo` | `-R` | off | Regenerate outputs even if they already exist |

### Step 1 — Rename and catalogue (`--rename` / `-r`)

Normalize all filenames to a canonical scheme and extract full EXIF metadata into `ppsp_photos.csv` (tab-separated). These two operations always run together: the CSV records both the original filename (`SourceFile`) and the renamed result (`FileName`).

```bash
ppsp --rename                                                          # all files in current dir
ppsp -r photo1.arw photo2.jpg                                          # specific files
ppsp --rename --default-model "ILCE-7RM4" --default-lens "SEL1635GM"  # EXIF fallbacks
```

If camera model or lens ID is absent from EXIF and no default is supplied, the placeholder `zzz` is used (e.g. `-m4azzz-`).

#### Rename options

| Flag | Short | Default | Description |
|---|---|---|---|
| `--default-model MODEL` | `-m` | — | Camera model fallback when missing from EXIF |
| `--default-lens LENS` | `-l` | — | Lens ID fallback when missing from EXIF |

#### Naming scheme

All files produced by `ppsp` follow this format throughout the entire pipeline:

```
YYYYMMDDHHMMSS-CCC[LLL]-NNNN-[chain].[ext]
```

| Component | Length | Source |
|---|---|---|
| `YYYYMMDDHHMMSS` | 14 | EXIF `DateTimeOriginal`, no separators |
| `CCC` | 3 | Last 3 chars of `Model` EXIF field, lowercased; `zzz` if shorter or missing |
| `LLL` | 3 | Last 3 chars of `SerialNumber` or `LensID`, lowercased; `zzz` if shorter or missing |
| `NNNN` | 4 | Last 4 digits of the numeric run in the original filename (`DSC02126.ARW` → `2126`); `0000` if none |
| `chain` | varies | Processing chain; see below |
| `ext` | varies | Lowercase original extension |

The `chain` for original camera files is a single collision-avoidance letter (`a`, `b`, `c`, …), incremented when two files from the same camera, lens, and second would otherwise collide. For processed outputs, the chain is a `-`-separated sequence of stage identifiers in fixed order:

```
[z-tier]-[enfuse-id]-[tmo-id]-[grading-id][-web]
```

`tmo-id` is omitted for focus stacks and pure enfuse outputs. `-web` is appended only on web-export copies.

| Filename | Meaning |
|---|---|
| `20260416095559-m4azzz-2126-a.arw` | Original ARW |
| `20260416095559-m4azzz-2126-a.jpg` | Camera JPG companion |
| `20260416095559-m4azzz-2126-z25-sel3-fatt-dvi2.jpg` | Discovery variant at z25 |
| `20260416095559-m4azzz-2126-z100-sel3-fatt-dvi2.jpg` | Full-quality generation |
| `20260416095559-m4azzz-2126-z100-sel3-fatt-dvi2-web.jpg` | Web export |
| `20260416095559-m4azzz-2126-z25-focu-neut.jpg` | Focus stack, `focu` variant, `neut` grading |

Stack folders use the first image's base name with a `-stack` suffix: `20260416095559-m4azzz-2126-stack/`.

#### ppsp_photos.csv

Written by `--rename`. The `StackName` column is added and populated by `--stacks-organize`.

| Column | Description |
|---|---|
| `FileName` | Canonical filename after renaming |
| `SourceFile` | Original filename before renaming |
| `FileSize` | File size in bytes |
| `DateTimeOriginal` | EXIF timestamp (`YYYY:MM:DD HH:MM:SS`) |
| `SubSecTimeOriginal` | Sub-second component |
| `Model` | Camera model string |
| `SerialNumber` | Camera serial number |
| `LensID` | Lens identifier |
| `ExposureTime` | Shutter speed |
| `FNumber` | Aperture |
| `ISO` | ISO sensitivity |
| `ExposureCompensation` | EV offset |
| `FocalLength` | Focal length in mm |
| `WhiteBalance` | White balance setting |
| `StackName` | Stack folder this file belongs to (set by Step 2) |

### Step 2 — Organize stacks (`--stacks-organize` / `-o`)

Group renamed files into per-stack directories named after the first image in the group, and populate the `StackName` column in `ppsp_photos.csv`.

```bash
ppsp --stacks-organize                                                 # all renamed files
ppsp -o 20260416095559-m4azzz-2126-a.arw 20260416095559-m4azzz-2127-a.arw
ppsp --stacks-organize --gap 60                                        # longer gap threshold
```

#### Options

| Flag | Short | Default | Description |
|---|---|---|---|
| `--gap SECONDS` | `-G` | `30` | Time gap (s) between consecutive shots that triggers a new stack |

#### Stack detection

Photos are sorted by timestamp. A new stack begins when any of the following signals fires:

| Signal | Condition | Rationale |
|---|---|---|
| Time gap | `Δt > --gap` | Even at high EV, a single shot rarely takes more than 30 s |
| EV return to zero | `ExposureCompensation` returns to 0 after a non-zero sequence | Bracket finished; neutral shot starts a new scene |
| Focal length change | `ΔFocalLength > 0.5 mm` | Zoom adjusted — new scene |
| F-number change | `ΔFNumber > 0.1` | Deliberate aperture change — new setup |
| White balance change | `WhiteBalance` string differs | Deliberate lighting or mode change |

Any single signal is sufficient to start a new stack. After grouping, each stack's type is determined by its exposure-compensation spread: more than one distinct rounded EV value → **HDR stack** (e.g. 0, −2, +2); all at the same EV → **focus stack**.

### Step 3 — Generate culling previews (`--stacks-cull` / `-c`)

Produce one labeled JPG preview per stack in `cull/`, named `<stack-name>_count<N>.jpg`.

```bash
ppsp --stacks-cull
```

The representative image is chosen in this priority order: a JPG at EV 0 → any JPG → any file at EV 0 (ARW-derived) → middle image of the stack. It is resized to 1920×1080 and annotated in the top-right corner with its filename (Liberation-Sans 26 pt, white text on 50 % black undercolor).

Review with any image viewer before proceeding:
```bash
eog cull/ &
```

### Step 4 — Manual culling and prune (`--stacks-prune` / `-p`)

Delete the preview files from `cull/` for any stacks you do not want to process. Stacks with no surviving preview are ignored by all subsequent steps. Then run:

```bash
ppsp --stacks-prune
```

This removes the stack directories that no longer have a corresponding preview in `cull/`.

### Step 5 — Variant discovery (`--stacks-process` / `-P`)

For each surviving stack, convert RAW files at reduced resolution, align the frames with `align_image_stack`, generate the requested variants, and assemble a labeled collage.

```bash
ppsp --stacks-process                                                  # z25, 'some' variants
ppsp -P 20260416095559-m4azzz-2126-stack                               # one specific stack
ppsp --stacks-process --fast --variants many --quality 70              # z13, 25 combos
ppsp --stacks-process --variants natu,sel3,fatt,ma06                   # custom ID selection
ppsp --stacks-process --variants sel4-fatt-dvi1,sel4-fatt-neut,sel4-ma06-dvi1  # exact chains
```

#### Variant discovery options

| Flag | Short | Default | Description |
|---|---|---|---|
| `--variants SPEC` | `-V` | `some` | What to generate — see the three modes below |
| `--fast` | `-f` | off | Use z13 resolution instead of z25 |

#### Three ways to specify variants

**Mode 1 — Preset level** (`some` / `many` / `all`): runs the cross-product of all enfuse IDs × all TMO IDs × all 6 grading presets for the chosen level.

```bash
ppsp --stacks-process --variants some    # default: 3 enfuse × 3 TMO × 6 gradings = 54 combos
ppsp --stacks-process --variants many    # 5 enfuse × 5 TMO × 6 gradings = 150 combos
ppsp --stacks-process --variants all     # all 9 enfuse × all 5 TMO × 6 gradings = 270 combos
```

**Mode 2 — Comma-separated IDs** (no `-` in any token): selects which enfuse, TMO, and grading IDs to include, then runs the cross-product. If no grading IDs are given, all 6 presets are used; otherwise only the listed ones.

```bash
ppsp --stacks-process --variants natu,sel3,fatt,ma06
# → enfuse: [natu, sel3]  TMO: [fatt, ma06]  gradings: all 6 → 24 variants

ppsp --stacks-process --variants sel3,fatt,ma06,dvi1
# → enfuse: [sel3]  TMO: [fatt, ma06]  gradings: [dvi1] → 2 variants
```

**Mode 3 — Exact chain specs** (any token contains `-`): generates precisely those chains, one output file per spec. The format per spec is `{enfuse-id}-{grading-id}` or `{enfuse-id}-{tmo-id}-{grading-id}`.

```bash
ppsp --stacks-process --variants sel4-fatt-dvi1,sel4-fatt-neut,sel4-ma06-dvi1
# → exactly 3 variants per stack, with exactly those processing chains
```

This mode is useful when you already know which chains you want — for example, after a previous discovery run — and want to skip the full cross-product.

#### Resolution tiers

The z-tier label is encoded in every output filename. `--generate` uses whatever z-tier is specified in the target filename.

| Label | Pixel count | How produced |
|---|---|---|
| `z100` | 100 % | `dcraw` without `-h`; used by `--generate` for full-quality output |
| `z25` | ≈25 % | `dcraw -h`; default for discovery |
| `z13` | ≈12.5 % | `dcraw -h` then `mogrify -resize 50%`; selected with `--fast` |

#### Preset variant levels (Mode 1)

Each preset also includes a default set of grading presets. Variants = (enfuse × gradings) + (enfuse × TMO × gradings).

| Level | Enfuse IDs | TMO IDs | Grading IDs | Total variants |
|---|---|---|---|---|
| `some` *(default)* | `natu`, `sel3`, `sel4` | `ma06`, `fatt`, `ferw` | `neut`, `brig`, `dvi1` | 36 |
| `many` | `natu`, `sel3`, `sel4`, `sel6`, `cont` | `ma06`, `ma08`, `fatt`, `ferr`, `ferw` | `neut`, `warm`, `brig`, `dvi1`, `dvi2` | 150 |
| `all` | all nine | all five | all six | 540 |

#### Enfuse variants

Flags are passed directly to `enfuse`:

| ID | Character | Parameters |
|---|---|---|
| `natu` | Natural, balanced | `--exposure-weight=1.0 --saturation-weight=0.2 --contrast-weight=0.2` |
| `cons` | Conservative, slightly darker | `--exposure-weight=0.8 --saturation-weight=0.2 --contrast-weight=0.3` |
| `sel1` | Selective, wide window | `--exposure-weight=1.0 --saturation-weight=0.1 --contrast-weight=0.4 --exposure-width=0.9` |
| `sel2` | Selective, hard mask, bright | `--exposure-weight=1.0 --saturation-weight=0.1 --contrast-weight=0.3 --exposure-width=0.7 --hard-mask` |
| `sel3` | Selective, good all-rounder | `--exposure-weight=1.0 --saturation-weight=0.1 --contrast-weight=0.5 --exposure-width=0.5 --hard-mask` |
| `sel4` | Selective, best overall | `--exposure-weight=1.0 --saturation-weight=0.1 --contrast-weight=0.6 --exposure-width=0.4 --hard-mask` |
| `sel5` | Selective, very high contrast | `--exposure-weight=1.0 --saturation-weight=0.1 --contrast-weight=0.8 --exposure-width=0.3 --hard-mask` |
| `sel6` | Selective, maximum contrast | `--exposure-weight=1.0 --saturation-weight=0.1 --contrast-weight=0.8 --exposure-width=0.2 --hard-mask` |
| `cont` | Contrast-focused, no exposure width | `--exposure-weight=0.6 --saturation-weight=0.1 --contrast-weight=0.8 --hard-mask` |

For focus stacks, a single `focu` variant is used instead: `--contrast-weight=1 --saturation-weight=0 --exposure-weight=0 --hard-mask --contrast-window-size=9`.

#### Tone-mapping operators

Invoked via `luminance-hdr-cli --tmo <id>` on the 16-bit TIFF produced by enfuse:

| ID | Operator |
|---|---|
| `ma06` | Mantiuk '06 |
| `ma08` | Mantiuk '08 |
| `ferr` | Ferradans |
| `fatt` | Fattal |
| `ferw` | Ferwerda |

#### Color-grading presets

Applied via ImageMagick `convert` as the final stage after fusion/TMO:

| ID | Effect | ImageMagick parameters |
|---|---|---|
| `neut` | Clean, minimal processing | `-colorspace sRGB -unsharp 0x0.8+0.5+0.05` |
| `warm` | Subtle warmth, slightly desaturated blue | `-colorspace sRGB -modulate 100,108,97 -unsharp 0x0.8+0.5+0.05` |
| `brig` | Brighter and slightly vivid, gentle sharpening | `-colorspace sRGB -sigmoidal-contrast 3,50% -brightness-contrast 8x-5 -modulate 100,105,100 -unsharp 0x1+0.5+0.05` |
| `deno` | Denoised, mild brightness and saturation boost | `-colorspace sRGB -despeckle -sigmoidal-contrast 3,50% -brightness-contrast 6x-4 -modulate 100,106,100 -unsharp 0x1.5+1.0+0.05` |
| `dvi1` | Punchy and vivid, strong saturation | `-colorspace sRGB -despeckle -sigmoidal-contrast 3,50% -brightness-contrast 7x-5 -modulate 100,125,100 -unsharp 0x1+0.8+0.05` |
| `dvi2` | Very vivid, high local contrast | `-colorspace sRGB -despeckle -sigmoidal-contrast 4,45% -brightness-contrast 12x-8 -modulate 100,118,100 -unsharp 0x1.2+0.6+0.05` |

#### Output structure after discovery

Each stack's discovery variants — and all combined intermediates — are written into a z-tier subfolder (`z25/` or `z13/`) inside the stack directory. Only the per-frame source files (ARW, JPG companions, and their raw-converted TIFs) stay in the stack root. The collage is also written into the z-tier subfolder. Alongside this, `ppsp` creates a flat `variants/` folder at the shoot root containing hard links (fallback: copies) to every variant and collage from all stacks — this is the folder you browse and cull from.

```
shoot/
├── 20260416095559-m4azzz-2126-stack/
│   ├── 20260416095559-m4azzz-2126-a.arw          ← per-frame source files stay in root
│   ├── 20260416095559-m4azzz-2126-a-z25.tif      ← per-frame raw-converted TIF stays in root
│   └── z25/                                       ← all combined outputs here
│       ├── 20260416095559-m4azzz-2126-z25-aligned0000.tif   ← aligned (removed by --cleanup)
│       ├── 20260416095559-m4azzz-2126-z25-aligned0001.tif
│       ├── 20260416095559-m4azzz-2126-z25-sel4.tif          ← enfuse temp (removed by --cleanup)
│       ├── 20260416095559-m4azzz-2126-z25-sel4-fatt.jpg     ← TMO temp (removed by --cleanup)
│       ├── 20260416095559-m4azzz-2126-z25-sel3-fatt-dvi1.jpg
│       ├── 20260416095559-m4azzz-2126-z25-sel4-ma06-neut.jpg
│       ├── ...
│       └── 20260416095559-m4azzz-2126-stack-collage.jpg
└── variants/                                      ← hard links to variants + collages
    ├── 20260416095559-m4azzz-2126-z25-sel3-fatt-dvi1.jpg
    ├── 20260416095559-m4azzz-2126-stack-collage.jpg
    └── ...
```

#### Collage

After all variants for a stack are produced, a single `<stack-name>-collage.jpg` is written into the z-tier subfolder alongside the variants. All tiles (originals first, then variants) are arranged in a grid whose dimensions are chosen to approximate a 16:9 aspect ratio. Each tile is 640 px wide (preserving the source aspect ratio) and labeled with its chain identifier (`z25-sel3-fatt-dvi2`) in 32 pt white text overlaid at the bottom center of the tile.

### Step 6 — Variant selection

After discovery, browse the `variants/` folder with any image viewer (e.g. `eog variants/ &`). Two selection methods are available; `ppsp` asks you to choose when running interactively.

#### Method A — Folder-based (recommended)

Simply delete the variants you do **not** want from `variants/`. Because these are hard links, the originals in the stack's z-tier subfolder are unaffected — you are only removing entries from the selection set.

```bash
# Delete unwanted variants, e.g.:
rm variants/*-natu-*.jpg
rm variants/*-collage.jpg
# Then generate what remains:
ppsp --generate variants/
```

#### Method B — CSV-based

`ppsp` also writes `ppsp_generate.csv` (tab-separated). Open it in any spreadsheet or editor and mark desired variants with `x` in the `Generate` column.

| Column | Description |
|---|---|
| `Filename` | Full-resolution target filename (`z100`) |
| `Generate` | `-` (skip) or `x` (generate) |

```
Filename	Generate
20260416095559-m4azzz-2126-z100-sel3-fatt-dvi2.jpg	-
20260416095559-m4azzz-2126-z100-sel4-ma06-dvi1.jpg	x
```

```bash
ppsp --generate ppsp_generate.csv
```

### Step 7 — Generate variants (`--generate` / `-g`)

Generates outputs from the surviving selection. The z-tier is read from each target's chain and executed in sequence, skipping any intermediate that already exists (unless `--redo`). Outputs land in `out_full/` and `out_web/`.

```bash
ppsp --generate variants/                                              # Method A: folder → z100
ppsp --generate variants/ --half                                        # Method A: folder → z25
ppsp --generate ppsp_generate.csv                                      # Method B: CSV
ppsp -g my_selection.txt                                               # one filename per line
ppsp --generate 20260416095559-m4azzz-2126-z100-sel3-fatt-dvi2.jpg    # direct filename
ppsp --generate z25-sel4-ma06-dvi1                                     # chain spec, all stacks
ppsp --generate variants/ --redo                                        # force regeneration
```

`out_full/` holds the generated JPEG at quality 95. `out_web/` holds a web-ready copy (max 2048 px, quality 80, `-strip`).

#### Chain spec syntax

Pass one or more z-tier chain specs directly as arguments. Each spec is expanded to all stacks under `--source` — no need to list individual files:

```bash
ppsp --generate z25-sel4-ma06-dvi1                      # one chain, all stacks, at z25
ppsp --generate z100-sel4-ma06-dvi1                     # same chain at full resolution
ppsp --generate z25-sel4-ma06-dvi1 z100-natu-neut       # two chains across all stacks
ppsp --generate z25-focu-neut                           # focus stack chain, all stacks
```

Form: `{z-tier}-{enfuse-id}-{grading-id}` or `{z-tier}-{enfuse-id}-{tmo-id}-{grading-id}`. All component IDs must be valid (see tables above). The embedded z-tier is used directly — `--half` is not needed.

#### `--half` — z25 for directory scans

When scanning a directory (e.g. `variants/`), filenames are converted to z100 by default. Pass `--half` to keep them at z25 and reuse all discovery-phase intermediates:

```bash
ppsp --stacks-process --fast        # z13 discovery; z25 TIFFs also saved as side-effect
ppsp --generate variants/ --half    # grade to z25 at quality 95 — reuses all intermediates
```

#### CSV and TXT — z-tier from each filename

When reading from a CSV or TXT file, filenames are used exactly as written. The z-tier in each filename drives which intermediates are reused, so a single CSV can mix tiers:

```
Filename	Generate
20260416095559-m4azzz-2126-z25-sel4-ma06-dvi1.jpg	x
20260416095559-m4azzz-2127-z100-natu-neut.jpg	x
```

```bash
ppsp --generate my_selection.csv    # no --half needed; z-tier from each filename
```

## Additional commands

`--arws-enhance [FILES...]` (`-e`) converts individual ARW files to high-quality enhanced JPGs without stacking or grading. Defaults to all ARWs under `--source`.

`--cleanup` (`-C`) removes intermediate files from all z-tier subfolders under `--source`: all TIFFs (aligned frames + enfuse temps) and TMO temp JPGs (identified by having a TMO id as their last chain component rather than a grading id). Final variant JPGs and collages are preserved. Run this after generation is complete and you no longer need to regenerate variants.

## Output structure

```
shoot/
├── ppsp_photos.csv                       # EXIF catalogue + StackName (tab-separated)
├── ppsp_generate.csv                     # Variant selection file (tab-separated)
├── ppsp.log                              # Full run log
├── cull/                                 # One labeled preview per stack
│   └── 20260416095559-m4azzz-2126-stack_count5.jpg
├── variants/                             # Hard links to all discovery variants + collages
│   ├── 20260416095559-m4azzz-2126-z25-sel3-fatt-dvi1.jpg
│   └── 20260416095559-m4azzz-2126-stack-collage.jpg
├── 20260416095559-m4azzz-2126-stack/     # One folder per stack
│   ├── 20260416095559-m4azzz-2126-a.arw  # Per-frame source files stay in root
│   ├── 20260416095559-m4azzz-2126-a-z25.tif  # Per-frame raw-converted TIF
│   └── z25/                             # All combined outputs: intermediates + variants + collage
│       ├── *-z25-aligned0000.tif         # Aligned TIFs (removed by --cleanup)
│       ├── *-z25-sel4.tif               # Enfuse temp TIF (removed by --cleanup)
│       ├── *-z25-sel4-fatt.jpg          # TMO temp JPG (removed by --cleanup)
│       ├── 20260416095559-m4azzz-2126-z25-sel3-fatt-dvi1.jpg
│       └── 20260416095559-m4azzz-2126-stack-collage.jpg
├── out_full/                             # Full-quality finals (from --generate)
│   └── 20260416095559-m4azzz-2126-z100-sel3-fatt-dvi2.jpg
└── out_web/                              # Web-ready finals
    └── 20260416095559-m4azzz-2126-z100-sel3-fatt-dvi2-web.jpg
```

## Development

```bash
git clone <repo>
cd ppsp
pip install -e ".[dev]"

# Run all tests
pytest

# Run a single test
pytest tests/test_rename.py::test_compute_refined_name

# Lint
ruff check src/
```

**Test data:** place a small set of Sony ARW + JPG pairs in `test_data/`. Tests requiring real image data are automatically skipped if `test_data/` is absent or empty. The directory is gitignored and not distributed with the package. See [DESIGN.md](DESIGN.md) for the full testing strategy and code architecture.
