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
| 7 | `--generate FILES/CSV/TXT` | `-g` | Generate variants from chain specifications |
| — | `--arws-enhance [FILES...]` | `-e` | Convert ARW files to enhanced JPGs |
| — | `--cleanup` | `-C` | Remove intermediate TIFFs from stack folders |

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

For each surviving stack, convert RAW files at reduced resolution, align the frames with `align_image_stack`, generate all requested enfuse × TMO × grading variant combinations, and assemble a labeled collage.

```bash
ppsp --stacks-process                                                  # z25, 'some' variants
ppsp -P 20260416095559-m4azzz-2126-stack                               # one specific stack
ppsp --stacks-process --fast --variants many --quality 70              # z13, 25 combos
ppsp --stacks-process --variants natu,sel3,fatt,ma06                   # custom selection
```

#### Variant discovery options

| Flag | Short | Default | Description |
|---|---|---|---|
| `--variants LEVEL_OR_LIST` | `-V` | `some` | Preset level (`some`/`many`/`all`) or comma-separated IDs |
| `--fast` | `-f` | off | Use z13 resolution instead of z25 |

#### Resolution tiers

The z-tier label is encoded in every output filename. `--generate` uses whatever z-tier is specified in the target filename.

| Label | Pixel count | How produced |
|---|---|---|
| `z100` | 100 % | `dcraw` without `-h`; used by `--generate` for full-quality output |
| `z25` | ≈25 % | `dcraw -h`; default for discovery |
| `z13` | ≈12.5 % | `dcraw -h` then `mogrify -resize 50%`; selected with `--fast` |

#### Variant levels

Each enfuse variant is combined with each TMO variant to produce the full cross-product. Supply a comma-separated list of IDs to select exactly which enfuse and/or TMO variants to run:

| Level | Enfuse IDs | TMO IDs | Combinations |
|---|---|---|---|
| `some` *(default)* | `natu`, `sel3`, `sel4` | `ma06`, `fatt`, `ferw` | 9 |
| `many` | `natu`, `sel3`, `sel4`, `sel6`, `cont` | `ma06`, `ma08`, `fatt`, `ferr`, `ferw` | 25 |
| `all` | all nine | all five | 45 |

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

#### Collage

After all variants for a stack are produced, a single `<stack-name>-collage.jpg` (3840×3840) is written into the stack folder. Row 1 shows the original JPGs from the stack, Row 2 the enfuse outputs, Row 3 the tone-mapped outputs (omitted for focus stacks). Each tile is downsized to fit the 3840 px width and labeled with its variant chain.

### Step 6 — Variant selection

After discovery, `ppsp` writes `ppsp_generate.csv`. The file is tab-separated; open it in any spreadsheet application or text editor.

#### ppsp_generate.csv

| Column | Description |
|---|---|
| `Filename` | Target filename including the full variant chain |
| `Generate` | `-` (skip) or `x` (generate) |

Every row has `Generate` set to `-` by default — change it to `x` for each variant you want generated. You may also add new rows with custom variant chains; the tool will generate those too.

```
Filename	Generate
20260416095559-m4azzz-2126-z100-sel3-fatt-dvi2.jpg	-
20260416095559-m4azzz-2126-z100-sel4-ma06-dvi1.jpg	-
```

Note that the filenames pre-filled by `ppsp` use `z100` — these are the full-resolution targets that do not yet exist. The discovery variants (at `z25` or `z13`) live in the stack folder and served their purpose as previews.

### Step 7 — Generate variants (`--generate` / `-g`)

Reads the selection file (or explicit filenames or a plain TXT file) and generates all marked variants. The z-tier, enfuse variant, TMO, and grading preset are parsed from each filename's chain and executed in sequence, skipping any intermediate that already exists (unless `--redo`). Outputs land in `out_full/` and `out_web/`.

```bash
ppsp --generate ppsp_generate.csv                                      # from selection CSV
ppsp -g my_selection.txt                                               # one filename per line
ppsp --generate 20260416095559-m4azzz-2126-z100-sel3-fatt-dvi2.jpg    # direct
ppsp --generate ppsp_generate.csv --redo                               # force all intermediates
```

`out_full/` holds the generated JPEG at quality 95. `out_web/` holds a web-ready copy (max 2048 px, quality 80, `-strip`).

## Additional commands

`--arws-enhance [FILES...]` (`-e`) converts individual ARW files to high-quality enhanced JPGs without stacking or grading. Defaults to all ARWs under `--source`.

`--cleanup` (`-C`) removes intermediate TIFFs (`aligned_*`, `temp_*`) from all stack folders under `--source`. Run this after generation is complete and you no longer need to regenerate variants.

## Output structure

```
shoot/
├── ppsp_photos.csv                       # EXIF catalogue + StackName (tab-separated)
├── ppsp_generate.csv                     # Variant selection file (tab-separated)
├── ppsp.log                              # Full run log
├── cull/                                 # One labeled preview per stack
│   └── 20260416095559-m4azzz-2126-stack_count5.jpg
├── 20260416095559-m4azzz-2126-stack/     # One folder per stack
│   ├── 20260416095559-m4azzz-2126-a.arw
│   ├── ...
│   ├── 20260416095559-m4azzz-2126-z25-sel3-fatt-dvi2.jpg
│   ├── 20260416095559-m4azzz-2126-collage.jpg
│   └── ...
├── out_full/                             # Full-quality finals
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
