# ppsp — Post Photoshoot Processing

A CLI tool for real-estate and architectural photographers who shoot 200+ images per session and publish 10–20 polished finals.
`ppsp` is purpose-built around **stack processing**: every image is treated as part of an HDR exposure bracket or focus stack, and the tool is designed to handle dozens of stacks in a single automated run.
It automates the tedious mechanical work — renaming, organizing, stacking/aligning, fusing, tone-mapping, grading, resizing — while keeping you as the creative director.

This README explains how ppsp can be used, but complementary documents are available:
* **[GUIDE.md](GUIDE.md)** provides a deep-dive into the underlying theory and tools behind ppsp and its built-in presets.
* **[DESIGN.md](DESIGN.md)** provides a technical overview of the tool from a developer's prespective.

## Motivation

A typical architectural session produces hundreds of RAW images belonging to dozens of HDR and focus stacks that require a lot of processing steps before results can be shared.
The optimum tone-mapping and color-grading parameters are impossible to know upfront, so you end up generating dozens of variants per image.
`ppsp` speeds through that discovery phase at reduced resolution, presents the candidates in labeled collages, then generates only the keepers at full quality — with a single command.

Key design goals:

- **Minimize human time.** Make every choice among clearly prepared options, not from scratch.
- **Minimize processing time.** Variant discovery runs at reduced resolution (z25 or z6); full-quality output is generated only for selected results.
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
ppsp --dir /path/to/shoot/

# Fully automated (no prompts)
ppsp --dir /path/to/shoot/ --batch
```

## Processing flow and command reference

Running `ppsp` without a command flag walks you through all steps interactively. Every step can also be invoked individually. All file-accepting commands default to all matching files under `--dir` (or the current directory) when no files are given explicitly.

| Step | Command | Short | Description |
|---|---|---|---|
| 1 | `--rename [FILES...]` | `-r` | Normalize filenames + write `ppsp_photos.csv` |
| 2 | `--organize [FILES...]` | `-o` | Group files into per-stack folders |
| 3 | `--cull` | `-c` | Generate labeled culling previews in `cull/` |
| 4 | `--prune` | `-P` | Remove stack folders with no surviving preview |
| 5 | `--discover` | `-D` | Generate variants with annotations for discovery |
| 6 | *(manual)* | | Browse `variants/`, delete unwanted files or mark CSV |
| 7 | `--generate` | `-g` | Generate variants for publishing |
| — | `--cleanup` | `-C` | Remove z-tier discovery folders and `variants/` |
| — | `--arws-enhance [FILES...]` | `-e` | Convert ARW files to enhanced JPGs |

**All options** — flags that tune command behaviour:

| Flag | Short | Default | Affects | Description |
|---|---|---|---|---|
| `--verbose` | `-v` | off | all | Debug-level logging |
| `--batch` | `-b` | off | full workflow | Skip all interactive prompts |
| `--dir DIR` | `-d` | `.` | all | Directory containing shoot images |
| `--default-model MODEL` | `-m` | — | `-r` | Camera model fallback when missing from EXIF |
| `--default-lens LENS` | `-l` | — | `-r` | Lens ID fallback when missing from EXIF |
| `--gap SECONDS` | `-G` | `30` | `-o` | Time gap (s) between shots that triggers a new stack |
| `--stacks SPEC...` | `-s` | — | `-D`, `-g` | Limit scope to specific stacks: full name, 4-digit frame number, or `NNNN-NNNN` range |
| `--variants SPEC` | `-V` | see note | `-D`, `-g` | What to discover or generate — see [§ --variants (-V)](#--variants--v); default is `some` for `-D` and `variants/` for `-g` |
| `--size SIZE` | `-z` | see note | `-D`, `-g` | Resolution tier: `z6`/`quarter`, `z25`/`half`, `z100`/`full` — default is `z25` for `-D` and `z100` for `-g` |
| `--quality INT` | `-q` | `80` | all | JPEG quality for internal conversions |
| `--redo` | `-R` | off | all | Regenerate outputs even if they already exist |

> **Warning:** Three of the uppercase flags are destructive: `-P` deletes stack directories, `-C` removes z-tier and `variants/` folders, `-R` forces regeneration of existing outputs.

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
| `20260416095559-m4azzz-2126-z25-sel3-fatc-dvi2.jpg` | Discovery variant at z25 |
| `20260416095559-m4azzz-2126-z100-sel3-fatc-dvi2.jpg` | Full-quality generation |
| `20260416095559-m4azzz-2126-z100-sel3-fatc-dvi2-web.jpg` | Web export |
| `20260416095559-m4azzz-2126-z25-focu-neut.jpg` | Focus stack, `focu` variant, `neut` grading |

Stack folders use the first image's base name with a `-stack` suffix: `20260416095559-m4azzz-2126-stack/`.

#### ppsp_photos.csv

Written by `--rename`. The `StackName` column is added and populated by `--organize`.

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

### Step 2 — Organize stacks (`--organize` / `-o`)

Group renamed files into per-stack directories named after the first image in the group, and populate the `StackName` column in `ppsp_photos.csv`.

```bash
ppsp --organize                                                        # all renamed files
ppsp -o 20260416095559-m4azzz-2126-a.arw 20260416095559-m4azzz-2127-a.arw
ppsp --organize --gap 60                                               # longer gap threshold
```

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

### Step 3 — Generate culling previews (`--cull` / `-c`)

Produce one labeled JPG preview per stack in `cull/`, named `<stack-name>_count<N>.jpg`.

```bash
ppsp --cull
```

The representative image is chosen in this priority order: a JPG at EV 0 → any JPG → any file at EV 0 (ARW-derived) → middle image of the stack.
The representatives are resized to 1920×1080 and annotated in the bottom-center: the image number (NNNN) in large bold, and the frame count (`×N`) in smaller text below it.

Review with any image viewer before proceeding:
```bash
eog cull/ &
```

### Step 4 — Manual culling and prune (`--prune` / `-P`)

Delete the preview files from `cull/` for any stacks you do not want to keep.
Then run:

```bash
ppsp --prune
```

This deletes the stack directories that no longer have a corresponding preview in `cull/` and thus completely eliminates them from further processing.

**WARNING**: If you have no backups, you will lose the culled images!

### Step 5 — Variant discovery (`--discover` / `-D`)

For each surviving stack, convert RAW files at reduced resolution, align the frames, generate the requested variants, annotate each with its full filename, and assemble a collage. Results land in a z-tier subfolder inside each stack directory and are hard-linked into `variants/` for easy browsing.

```bash
ppsp --discover                                                        # z25, 'some' variants
ppsp -D --stacks 2126                                                  # one specific stack
ppsp --stacks 2126-2200 -D -z z6 -V many --quality 70                  # z6, stacks 2126-2200
ppsp -D -V natu,sel3,fatc,m06p                                         # custom ID selection
ppsp -D -V sel4-fatc-dvi1,sel4-fatc-neut,sel4-m06p-dvi1                # exact chains
```

Use `-V` to specify which variants to run and `-z` to override the resolution tier — see [§ --variants (-V)](#--variants--v).

#### Resolution tiers

The z-tier label is encoded in every output filename. For `-g`, the tier is determined by each filename's embedded z-tier (directory/CSV/TXT inputs) or by `-z` (chain specs / presets; default: `z100`).

| Label | Pixel count | How produced |
|---|---|---|
| `z100` | 100 % | `dcraw` without `-h`; default for `-g` |
| `z25` | ≈25 % | `dcraw -h`; default for `-D` |
| `z6` | ≈6.25 % | `dcraw -h` then `mogrify -resize 50%`; selected with `-z z6` |

#### Preset variant levels

Each preset also includes a default set of grading presets. Variants = (enfuse × gradings) + (enfuse × TMO × gradings).

| Level | Enfuse IDs | TMO IDs | Grading IDs |
|---|---|---|---|
| `some` *(default)* | `sel4` | `m08n`, `fatn` | `neut`, `dvi1` |
| `many` | `natu`, `sel3`, `sel4` | `m08n`, `fatn` | `neut`, `dvi1` |
| `lots` | `natu`, `sel3`, `sel4`, `sel6`, `cont` | `m08n`, `m08c`, `m06p`, `r02p`, `dras`, `fatc` | `neut`, `warm`, `brig`, `dvi1`, `dvi2` |
| `all` | all nine | all sixteen | all six |

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

Invoked via `luminance-hdr-cli` on the 16-bit TIFF produced by enfuse. The TIFF is passed as a positional argument (not `-l`, which is for existing `.hdr`/`.exr` HDR files). Tuned variants use individual `--tmoXxx` flags specific to each operator. **Requires Luminance HDR v2.6.0.**

For each operator, a `d`-suffix "defaults" variant is listed first (no extra flags — Luminance uses its built-in defaults), followed by tuned variants.

> For single-frame stacks (no HDR brackets), enfuse is skipped and tone-mapping runs directly on the converted TIFF, producing a "pseudo-HDR" polish effect.

| ID | Operator | Character | Key tuning flags |
|---|---|---|---|
| `m08d` | Mantiuk '08 | Luminance defaults | — |
| `m08n` | Mantiuk '08 | Natural / balanced; bright editorial look — best all-rounder for interiors | `--tmoM08ColorSaturation 1.2 --tmoM08ConstrastEnh 2.0 --gamma 1.2 --saturation 1.2 --postgamma 1.1` |
| `m08c` | Mantiuk '08 | Higher contrast, same brightness as m08n; windows and mixed-light scenes | `--tmoM08ColorSaturation 1.3 --tmoM08ConstrastEnh 3.0 --gamma 1.2 --postgamma 1.1` |
| `m06d` | Mantiuk '06 | Luminance defaults | — |
| `m06p` | Mantiuk '06 | Punch / pop; strong texture micro-contrast — wood, stone, tile | `--tmoM06Contrast 0.7 --tmoM06Saturation 1.4 --tmoM06Detail 1.0 --gamma 1.2 --postgamma 1.1` |
| `drad` | Drago | Luminance defaults | — |
| `dras` | Drago | Soft logarithmic highlight roll-off with shadow lift; contre-jour and blue-hour | `--tmoDrgBias 0.85 --postgamma 1.1` |
| `r02d` | Reinhard '02 | Luminance defaults | — |
| `r02p` | Reinhard '02 | Zone-system photographic tone curve; lowest artefact risk, brightened | `--tmoR02Key 0.18 --tmoR02Phi 1.0 --postgamma 1.1` |
| `fatd` | Fattal | Luminance defaults | — |
| `fatn` | Fattal | Tamed / natural; gradient pop with desaturated output and moderate brightness lift | `--tmoFatColor 0.8 --gamma 1.1 --postgamma 1.1` |
| `fatc` | Fattal | Creative / dramatic; full local contrast on exteriors and high-contrast architecture | `--tmoFatAlpha 0.8 --tmoFatBeta 0.9 --postgamma 1.05` |
| `ferr` | Ferradans | Luminance defaults | — |
| `ferw` | Ferwerda | Luminance defaults | — |
| `kimd` | KimKautz | Luminance defaults | — |
| `kimn` | KimKautz | Clean magazine look; no halos, no colour shift — luxury interiors and white walls | `--tmoKimKautzC1 0.8 --tmoKimKautzC2 1.2 --postgamma 1.1` |

Note: The author compared the results with these tone-mapping presets with some sample indoor photos taken with the Sony a7R IV, and the following seemed to provide the best results by image content:

| Image content | Good TMO presets |
|---------------|------------------|
| living room with a somewhat distant large bright window with a little sunshine indoors | fatd, kimd, m06p, r02p |
| dining room with somewhat distant bright window | fatd, kimd, m06p, m08c, r02p |
| white bathroom with small window in the evening | fatn, kimn, m06p, r02p |
| bedroom with a large window in shadow | fatd, kimd, r02p |
| any of the above | r02p |
| most of the above | fatd, kimd, m06p |

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

Each stack's discovery variants — and all combined intermediates — are written into a z-tier subfolder (`z25/` or `z6/`) inside the stack directory. Only the per-frame source files (ARW, JPG companions, and their raw-converted TIFs) stay in the stack root. The collage is also written into the z-tier subfolder. Alongside this, `ppsp` creates a flat `variants/` folder at the shoot root containing hard links (fallback: copies) to every variant and collage from all stacks — this is the folder you browse and cull from.

```
shoot/
├── 20260416095559-m4azzz-2126-stack/
│   ├── 20260416095559-m4azzz-2126-a.arw          ← per-frame source files stay in root
│   ├── 20260416095559-m4azzz-2126-a-z25.tif      ← per-frame raw-converted TIF stays in root
│   └── z25/                                       ← discovery outputs; removed by -C
│       ├── 20260416095559-m4azzz-2126-z25-aligned0000.tif
│       ├── 20260416095559-m4azzz-2126-z25-aligned0001.tif
│       ├── 20260416095559-m4azzz-2126-z25-sel4.tif
│       ├── 20260416095559-m4azzz-2126-z25-sel4-fatc.jpg
│       ├── 20260416095559-m4azzz-2126-z25-sel3-fatc-dvi1.jpg
│       ├── 20260416095559-m4azzz-2126-z25-sel4-m06p-neut.jpg
│       ├── ...
│       └── 20260416095559-m4azzz-2126-stack-collage.jpg
└── variants/                                      ← hard links to variants + collages; removed by -C
    ├── 20260416095559-m4azzz-2126-z25-sel3-fatc-dvi1.jpg
    ├── 20260416095559-m4azzz-2126-stack-collage.jpg
    └── ...
```

#### Collage

After all variants for a stack are produced, a single `<stack-name>-collage.jpg` is written into the z-tier subfolder alongside the variants. All tiles (originals first, then variants) are arranged in a grid whose dimensions are chosen to approximate a 16:9 aspect ratio. Each tile is 640 px wide (preserving the source aspect ratio). Each tile is annotated at the bottom center with its full filename stem in large bold. Individual variant JPEGs are also annotated the same way, so you can identify them from any image viewer without relying on filename display.

### Step 6 — Variant selection

After discovery, browse the `variants/` folder with any image viewer (e.g. `eog variants/ &`). Two selection methods are available; `ppsp` asks you to choose when running interactively.

#### Method A — Folder-based (recommended)

Simply delete the variants you do **not** want from `variants/`. Because these are hard links, the originals in the stack's z-tier subfolder are unaffected — you are only removing entries from the selection set.

```bash
# Delete unwanted variants, for example:
eog variants/ # browse through them and press delete on the unwanted
# or:
rm variants/*-natu-*.jpg
rm variants/*-collage.jpg
# Then generate what remains:
ppsp -g
```

#### Method B — CSV-based

`ppsp` also writes `ppsp_generate.csv` (tab-separated). Open it in any spreadsheet or editor and mark desired variants with `x` in the `Generate` column.

| Column | Description |
|---|---|
| `Filename` | Full-resolution target filename (`z100`) |
| `Generate` | `-` (skip) or `x` (generate) |

```
Filename	Generate
20260416095559-m4azzz-2126-z100-sel3-fatc-dvi2.jpg	-
20260416095559-m4azzz-2126-z100-sel4-m06p-dvi1.jpg	x
```

```bash
ppsp -g -V ppsp_generate.csv
```

### Step 7 — Generate variants (`--generate` / `-g`)

Generates selected variants at full quality for publishing. Outputs land in `out_full/` (quality 95) and `out_web/` (max 2048 px, quality 80, stripped metadata). Any variant already present in `out_full/` is skipped automatically; pass `--redo` to force regeneration. The `-s` flag limits generation to matching stacks.

Use `-V` to specify the source and `-z` to override the resolution tier — see [§ --variants (-V)](#--variants--v). The default is `-V variants/` (the folder that `-D` populates).

```bash
ppsp --generate                                                        # default: from variants/
ppsp -g -V ppsp_generate.csv                                           # from CSV
ppsp -g -V my_selection.txt                                            # from TXT file
ppsp -g -V sel4-m06p-dvi1                                              # chain spec, all stacks
ppsp -g -V "(z25|z100)-sel4-m.*[pn]-dvi1"                              # regex, all stacks
ppsp --generate --redo                                                 # force regeneration
ppsp -g --stacks 2126-2200                                             # limit to stacks 2126-2200
```

When reading from a directory, CSV, or TXT file, the z-tier is taken from each filename and overridden by `-z` if specified. When using chain specs or presets, `-z` determines the tier (default: `z100`).

### --variants (`-V`)

The `-V` option specifies what variants to run in `-D` (discovery) and `-g` (generate). It is evaluated in this order:

**File path — directory**: scans for `*.jpg` files; each filename's embedded z-tier is used as-is and overridden by `-z` if specified. Default for `-g` is `variants/`.

```bash
ppsp -g                            # reads variants/ (default)
ppsp -g -V /path/to/my_folder
```

**File path — CSV** (`.csv`): reads rows where `Generate == x`; z-tier from each filename, overridden by `-z`.

```bash
ppsp -g -V ppsp_generate.csv
```

**File path — TXT** (`.txt`): one target filename per line; z-tier as above.

```bash
ppsp -g -V my_selection.txt
```

**Mode 1 — Preset level** (`some` / `many` / `lots` / `all`): cross-product of the level's enfuse × TMO × grading IDs. Default for `-D` is `some`.

```bash
ppsp -D -V some    # 1 enfuse × 2 TMO × 2 gradings (+ enfuse-only)
ppsp -D -V many    # 3 enfuse × 2 TMO × 2 gradings
ppsp -D -V lots    # 5 enfuse × 6 TMO × 5 gradings
ppsp -D -V all     # all enfuse × all TMO × all gradings
```

**Mode 2 — Comma-separated IDs** (no `-` in any token): selects enfuse, TMO, and grading IDs and runs the cross-product. If no grading IDs are given, all six presets are used.

```bash
ppsp -D -V natu,sel3,fatc,m06p
# → enfuse: [natu, sel3]  TMO: [fatc, m06p]  gradings: all 6

ppsp -D -V sel3,fatc,m06p,dvi1
# → enfuse: [sel3]  TMO: [fatc, m06p]  gradings: [dvi1]
```

**Mode 3 — Chain specs with Python regex** (any token contains `-`): for `-D` each token is `{enfuse-id}-{grading-id}` or `{enfuse-id}-{tmo-id}-{grading-id}` (no z-tier);
for `-g` a z-tier prefix is optional and overridden by `-z`.
Standard Python `re` syntax is used for pattern matching against all valid chain combinations.

```bash
# Exact chains for -D:
ppsp -D -V sel4-fatc-dvi1,sel4-fatc-neut,sel4-m06p-dvi1

# Chain spec for -g:
ppsp -g -V z100-sel4-m06p-dvi1

# Alternation — same chain at two z-tiers:
ppsp -g -V "(z25|z100)-sel4-m06p-dvi1"

# Wildcard — all TMO variants for a fixed tier, enfuse ID, and grading:
ppsp -g -V "z6-sel4-.*-dvi1"
# → z6-sel4-m08d-dvi1, z6-sel4-m08n-dvi1, … (one per TMO variant)

# Combined — two z-tiers, only TMO IDs ending in p or n:
ppsp -g -V "(z25|z100)-sel4-m.*[pn]-dvi1"
# → z25-sel4-m06p-dvi1, z25-sel4-m08n-dvi1, z100-sel4-m06p-dvi1, z100-sel4-m08n-dvi1
```

Quote the pattern to prevent shell glob expansion. Patterns that match nothing emit a warning and produce no output.

## Additional commands

`--arws-enhance [FILES...]` (`-e`) converts individual ARW files to high-quality enhanced JPGs without stacking or grading. Defaults to all ARWs under `--dir`.

`--cleanup` (`-C`) removes all z-tier subfolders (`z6/`, `z25/`, `z100/`) inside every stack directory, and the flat `variants/` folder at the shoot root.
Original ARW and JPG source files, and the `out_full/`/`out_web/` export folders, are untouched.
Run this after generation is complete and you no longer need to re-run discovery.

## Output structure

```
shoot/
├── ppsp_photos.csv                       # EXIF catalogue + StackName (tab-separated)
├── ppsp_generate.csv                     # Variant selection file (tab-separated)
├── ppsp.log                              # Full run log
├── cull/                                 # One labeled preview per stack
│   └── 20260416095559-m4azzz-2126-stack_count5.jpg
├── variants/                             # Hard links to all discovery variants + collages; removed by -C
│   ├── 20260416095559-m4azzz-2126-z25-sel3-fatc-dvi1.jpg
│   └── 20260416095559-m4azzz-2126-stack-collage.jpg
├── 20260416095559-m4azzz-2126-stack/     # One folder per stack
│   ├── 20260416095559-m4azzz-2126-a.arw  # Per-frame source files stay in root
│   ├── 20260416095559-m4azzz-2126-a-z25.tif  # Per-frame raw-converted TIF
│   └── z25/                             # Discovery outputs: intermediates + variants + collage; removed by -C
│       ├── *-z25-aligned0000.tif
│       ├── *-z25-sel4.tif
│       ├── *-z25-sel4-fatc.jpg
│       ├── 20260416095559-m4azzz-2126-z25-sel3-fatc-dvi1.jpg
│       └── 20260416095559-m4azzz-2126-stack-collage.jpg
├── out_full/                             # Full-quality finals (from --generate)
│   └── 20260416095559-m4azzz-2126-z100-sel3-fatc-dvi2.jpg
└── out_web/                              # Web-ready finals
    └── 20260416095559-m4azzz-2126-z100-sel3-fatc-dvi2-web.jpg
```

## Usage example (actually used on 2026-04-22)

ppsp --rename -l L15
ppsp --organize
ppsp --cull
ppsp --prune
ppsp --discover -V 'sel4,sel5,r02p,fatd,kimd,m06p,deno,dvi1,dvi2' -z z6
ppsp --generate -z z25

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

## Further reading

For a deep-dive into the underlying tools and the reasoning behind ppsp's built-in presets, see **[GUIDE.md](GUIDE.md)**. It covers:

- RAW conversion with `dcraw` — parameters, colour science, resolution tiers
- Image alignment with `align_image_stack` — feature detection, HDR vs focus-stack modes
- Exposure fusion with `enfuse` — Laplacian pyramid, weight functions, all built-in variant IDs
- Tone-mapping with `luminance-hdr-cli` — every supported operator, parameter guide, when to use each one
- Color grading with ImageMagick — S-curve contrast, sharpening, the six built-in grading presets
- Photography-context guide — which operator combinations work best for each shot type

