# ppsp — Post Photoshoot Processor (or Python Photo Stack Producer if you prefer)

A CLI tool for real-estate and architectural photographers who shoot 200+ images per session and publish 10–20 polished finals.
`ppsp` is purpose-built around **stack processing**: every image is treated as part of an HDR exposure bracket or focus stack, and the tool is designed to handle dozens of stacks in a single automated run.
It automates the tedious mechanical work — renaming, organizing, stacking/aligning, fusing, tone-mapping, grading, resizing — while keeping you as the creative director.

This README explains how ppsp can be used, but complementary documents are available:
* **[guide.md](guide.md)** provides a deep-dive into the underlying theory and tools behind ppsp and its built-in presets.
* **[design.md](design.md)** provides a technical overview of the tool from a developer's perspective.

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
| 4 | *(manual)* | | Browse `cull/`, delete previews for unwanted stacks |
| 5 | `--prune` | `-P` | Remove stack folders with no surviving preview |
| 6 | `--name [TITLE_OR_CSV]` | `-n` | Assign human titles to stacks; rename folders and files; write `ppsp_stacks.csv` |
| 7 | `--discover` | `-D` | Generate variants with annotations for discovery |
| 8 | *(manual)* | | Browse `variants/`, delete unwanted files or mark CSV |
| 9 | `--generate` | `-g` | Generate variants for publishing |
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
| `--stacks SPEC...` | `-s` | — | `-n`, `-D`, `-g` | Limit scope to specific stacks: full name, 4-digit frame number, `NNNN-NNNN` range, or file paths / CSV / TXT (stack names derived from filenames) |
| `--variants SPEC` | `-V` | see note | `-D`, `-g` | What to discover or generate — see [§ --variants (-V)](#--variants--v); default is `some` for `-D` and `variants/` for `-g` |
| `--size SIZE` | `-z` | see note | `-D`, `-g` | Resolution tier: `z2`/`micro`, `z6`/`quarter`, `z25`/`half`, `z100`/`full` — default is `z25` for `-D` and `z100` for `-g` |
| `--quality INT` | `-q` | `80` | all | JPEG quality for internal conversions |
| `--resolution PX` | `-i` | — | `-g` | Long-side pixel cap; adds a resized copy to `out-{PX}/` alongside the full-res `out-{BBBB}/` |
| `--redo` | `-R` | off | all | Regenerate outputs even if they already exist |
| `--viewer VIEWER` | — | `xdg-open` | full workflow | Image viewer opened automatically during cull and variants review steps |

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
[z-tier]-[enfuse-id]-[tmo-id]-[grading-id][-ct-id]
```

`tmo-id` is omitted for focus stacks and pure enfuse outputs. `ct-id` is optional and only present when a color-temperature preset was applied.

| Filename | Meaning |
|---|---|
| `20260416095559-m4azzz-2126-a.arw` | Original ARW |
| `20260416095559-m4azzz-2126-a.jpg` | Camera JPG companion |
| `20260416095559-m4azzz-2126-z25-sel3-fatc-dvi2.jpg` | Discovery variant at z25 |
| `20260416095559-m4azzz-2126-z100-sel3-fatc-dvi2.jpg` | Full-quality generation |
| `20260416095559-m4azzz-2126-z100-sel3-fatc-dvi1-ctw5.jpg` | Full-quality with warm CT shift |
| `20260416095559-m4azzz-2126-z25-focu-neut.jpg` | Focus stack, `focu` variant, `neut` grading |
| `20260416095559-m4azzz-2126-bbfdtw-z25-sel4-fatc-dvi1.jpg` | Named stack (shorthand `bbfdtw`); title was assigned with `--name` |

Stack folders use the first image's base name with a `-stack` suffix initially: `20260416095559-m4azzz-2126-stack/`. After running `--name` (step 6), the `-stack` suffix is replaced by a 1–6 character shorthand derived from the title (e.g. `20260416095559-m4azzz-2126-bbfdtw/` for "Bedroom B from the door to the window"). Files inside a named stack get the shorthand inserted after `NNNN`: `NNNN-bbfdtw-a.arw`, `NNNN-bbfdtw-z25-sel4-fatc-dvi1.jpg`.

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

### Step 4 — Manual culling

Browse the previews in `cull/` and delete the ones for stacks you do not want to keep. When running interactively, `ppsp` opens the folder automatically with the configured viewer. You can also open it manually:

```bash
eog cull/ &
```

### Step 5 — Prune (`--prune` / `-P`)

After deleting unwanted previews, run:

```bash
ppsp --prune
```

This deletes the stack directories that no longer have a corresponding preview in `cull/` and thus completely eliminates them from further processing.

**WARNING**: If you have no backups, you will lose the culled images!

### Step 6 — Name stacks (`--name` / `-n`)

Assign a human title to each stack, embed it in EXIF/XMP/IPTC metadata via `exiftool`, rename the stack folder and all contained files to include a compact shorthand, and maintain `ppsp_stacks.csv` as the single source of truth for titles and per-stack generate specs.

```bash
ppsp --name                                                            # interactive: name all stacks in turn
ppsp -n ppsp_stacks.csv                                                # apply titles from an existing CSV
ppsp -s 2126 -n "Bedroom B from the door to the window"                # inline title for one stack
ppsp -s 2126 2150 -n                                                   # interactive only for two stacks
```

The **shorthand** is derived from the title by taking the first character of each non-filler word (articles, conjunctions), lowercased. Spatial prepositions ("from", "to", "by", etc.) are kept because they carry directional meaning in architectural scene titles. "Bedroom B from the door to the window" → `bbfdtw`.

After renaming, the stack folder changes from `NNNN-stack/` to `NNNN-{shorthand}/` and every file inside gains the shorthand after NNNN: `NNNN-a.arw` → `NNNN-bbfdtw-a.arw`. The `--name` command is idempotent — running it again on already-named stacks with the same title is a no-op; pass `--redo` to force re-application.

#### ppsp_stacks.csv

Created or updated on every `--name` invocation (tab-separated):

| Column | Description |
|---|---|
| `StackFolder` | Stack directory name (used to match rows on rename) |
| `Title` | Human-readable scene title |
| `Shorthand` | Derived 1–6 character shorthand embedded in filenames |
| `Photos` | Number of source files in the stack |
| `GenerateSpecs` | Comma-separated chain specs for `ppsp -g ppsp_stacks.csv` |

Pass `ppsp_stacks.csv` to `--generate` to use per-stack generate specs:

```bash
ppsp -g ppsp_stacks.csv
```

### Step 7 — Variant discovery (`--discover` / `-D`)

For each surviving stack, convert RAW files at reduced resolution, align the frames, generate the requested variants, annotate each with its full filename, and assemble a collage. Results land in a z-tier subfolder inside each stack directory and are hard-linked into `variants/` for easy browsing.

```bash
ppsp --discover                                                        # z25, 'some' variants
ppsp -D --stacks 2126                                                  # one specific stack
ppsp --stacks 2126-2200 -D -z z6 -V many --quality 70                  # z6, stacks 2126-2200
ppsp -D -V natu,sel3,fatc,m06p                                         # custom ID selection
ppsp -D -V sel4-fatc-dvi1,sel4-fatc-neut,sel4-m06p-dvi1                # exact chains
```

Use `-V` to specify which variants to run and `-z` to override the resolution tier — see [§ --variants (-V)](#--variants--v).

#### Discovery philosophy — chain stubs

The discovery phase is intentionally **educational**: instead of showing only fully-processed final images, `-D` generates _chain stub_ variants at each processing level so you can see exactly what each step contributes.

For every enfuse × TMO combination the pipeline produces three stub levels (plus the CT layer on top):

| Stub level | Filename pattern | What you see |
|---|---|---|
| Enfuse-only | `{base}-{z}-{e}.jpg` | Raw exposure-fusion output — no tone mapping, no colour grading |
| Enfuse + TMO | `{base}-{z}-{e}-{t}.jpg` | After tone mapping — before any ImageMagick grading |
| Enfuse + TMO + grading | `{base}-{z}-{e}-{t}-{g}.jpg` | Final publishable variant (full chain) |
| Full chain with CT | `{base}-{z}-{e}-{t}-{g}-{ct}.jpg` | White-point shift applied on top of the grading |

The GUI's **Discover** tab steps through these levels one at a time, so each step shows a like-for-like comparison:
- **Step 1 (Enfuse)**: compare `sel3.jpg` vs `sel4.jpg` vs `sel6.jpg` — which fusion setting captures the exposure range best?
- **Step 2 (TMO)**: compare `sel4-fatn.jpg` vs `sel4-m08n.jpg` — which tone-mapping operator suits this scene?
- **Step 3 (Grading)**: compare `sel4-fatn-neut.jpg` vs `sel4-fatn-dvi1.jpg` — which colour grade to publish?
- **Step 4 (CT)**: optionally add a white-point shift to the chosen grading chain.

You can also mix processing levels freely — for example `sel6.jpg` (enfuse-only), `sel3-fatd.jpg` (enfuse+TMO), or `sel5-kimd-dvi2-ctw4.jpg` (full chain with CT) are all valid outputs that `-D` and `-g` can produce or export.

#### Resolution tiers

The z-tier label is encoded in every output filename. For `-g`, the tier is determined by each filename's embedded z-tier (directory/CSV/TXT inputs) or by `-z` (chain specs / presets; default: `z100`).

| Label | Pixel count | How produced |
|---|---|---|
| `z100` | 100 % | `dcraw` without `-h`; default for `-g` |
| `z25` | ≈25 % | `dcraw -h`; default for `-D` |
| `z6` | ≈6.25 % | `dcraw -h` then `mogrify -resize 50%`; selected with `-z z6` |
| `z2` | ≈1.56 % | same as `z6` then another `mogrify -resize 50%`; fastest discovery |

#### Preset variant levels

Each preset also includes a default set of grading presets. Variants = (enfuse × gradings) + (enfuse × TMO × gradings) × (no CT + CT IDs).

| Level | Enfuse IDs | TMO IDs | Grading IDs | CT IDs |
|---|---|---|---|---|
| `some` *(default)* | `sel4` | `m08n`, `fatn` | `neut`, `dvi1` | — |
| `many` | `natu`, `sel4` | `m08n`, `r02p`, `fatn` | `neut`, `dvi1` | `ctw5` |
| `lots` | `natu`, `sel3`, `sel4`, `sel6`, `cont` | `m08n`, `m08c`, `m06p`, `r02p`, `dras`, `fatn`, `fatc`, `kimn` | `neut`, `brig`, `dvi1`, `dvi2` | `ctw5` |
| `all` | all nine | all sixteen | all five | all five CT IDs |

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
| `m08m` | Mantiuk '08 | Moody / restrained; low enhancement, slightly darker than m08n | `--tmoM08ColorSaturation 1.1 --tmoM08ConstrastEnh 1.5 --gamma 1.0 --postgamma 0.95` |
| `m06d` | Mantiuk '06 | Luminance defaults | — |
| `m06p` | Mantiuk '06 | Punch / pop; strong texture micro-contrast — wood, stone, tile | `--tmoM06Contrast 0.7 --tmoM06Saturation 1.4 --tmoM06Detail 1.0 --gamma 1.2 --postgamma 1.1` |
| `m06b` | Mantiuk '06 | Balanced; gentler than m06p, good general-purpose alternative | `--tmoM06Contrast 0.5 --tmoM06Saturation 1.2 --tmoM06Detail 0.8 --gamma 1.1 --postgamma 1.05` |
| `m06s` | Mantiuk '06 | Subtle / soft; minimal operator signature, closest to a clean lift | `--tmoM06Contrast 0.3 --tmoM06Saturation 1.0 --tmoM06Detail 0.6 --gamma 1.15 --postgamma 1.1` |
| `drad` | Drago | Luminance defaults | — |
| `dras` | Drago | Soft logarithmic highlight roll-off with shadow lift; contre-jour and blue-hour | `--tmoDrgBias 0.85 --postgamma 1.1` |
| `drab` | Drago | Higher bias; maximum shadow detail recovery | `--tmoDrgBias 0.95 --postgamma 1.05` |
| `dran` | Drago | Neutral bias; lets highlights breathe, lower-key result | `--tmoDrgBias 0.75 --postgamma 1.0` |
| `r02d` | Reinhard '02 | Luminance defaults | — |
| `r02p` | Reinhard '02 | Zone-system photographic tone curve; lowest artefact risk, brightened | `--tmoR02Key 0.18 --tmoR02Phi 1.0 --postgamma 1.1` |
| `r02h` | Reinhard '02 | High-key / bright; elevated midtone exposure for light, airy results | `--tmoR02Key 0.28 --tmoR02Phi 1.0 --postgamma 1.15` |
| `r02m` | Reinhard '02 | Moody / dark; low key, naturally shadowy atmosphere | `--tmoR02Key 0.10 --tmoR02Phi 1.0 --postgamma 1.0` |
| `fatd` | Fattal | Luminance defaults | — |
| `fatn` | Fattal | Tamed / natural; gradient pop with desaturated output and moderate brightness lift | `--tmoFatColor 0.8 --gamma 1.1 --postgamma 1.1` |
| `fatc` | Fattal | Creative / dramatic; full local contrast on exteriors and high-contrast architecture | `--tmoFatAlpha 0.8 --tmoFatBeta 0.9 --postgamma 1.05` |
| `fats` | Fattal | Soft / low-gradient; reduced local contrast for plain walls and clean interiors | `--tmoFatColor 0.6 --tmoFatAlpha 0.5 --tmoFatBeta 0.95 --gamma 1.1 --postgamma 1.1` |
| `ferr` | Ferradans | Luminance defaults | — |
| `ferw` | Ferwerda | Luminance defaults | — |
| `kimd` | KimKautz | Luminance defaults | — |
| `kimn` | KimKautz | Clean magazine look; no halos, no colour shift — luxury interiors and white walls | `--tmoKimKautzC1 0.8 --tmoKimKautzC2 1.2 --postgamma 1.1` |
| `kiml` | KimKautz | Low contrast / dark; restrained and atmospheric | `--tmoKimKautzC1 0.5 --tmoKimKautzC2 0.9 --postgamma 1.0` |
| `kimv` | KimKautz | Vibrant / punchy; enhanced local and global contrast | `--tmoKimKautzC1 1.0 --tmoKimKautzC2 1.5 --postgamma 1.15` |

Note: The author compared the results with these tone-mapping presets with some sample indoor photos taken with the Sony a7R IV, and the following seemed to provide the best results by image content:

| Image content | Good TMO presets |
|---------------|------------------|
| living room with a somewhat distant large bright window with a little sunshine indoors | fatd, fatn, kimd, m06p, r02p |
| dining room with somewhat distant bright window | fatd, fatn, kimd, m06p, m08c, r02p |
| white bathroom with small window in the evening | fatn, kimn, m06p, r02p |
| bedroom with a large window in shadow | fatd, fatn, kimd, r02p |
| any of the above | fatn, r02p |
| most of the above | fatd, fatn, kimd, m06p |

#### Color-grading presets

Applied via ImageMagick `convert` as the final stage after fusion/TMO. Warm or cool colour-temperature shifts are handled by the separate CT presets below (combine `neut`+`ctw5` for the old `warm` look, `dvi1`+`ctw5` for the old `dv1w` look).

| ID | Effect | ImageMagick parameters |
|---|---|---|
| `neut` | Clean, minimal processing | `-colorspace sRGB -unsharp 0x0.8+0.5+0.05` |
| `brig` | Brighter and slightly vivid, gentle sharpening | `-colorspace sRGB -sigmoidal-contrast 3,50% -evaluate multiply 1.10 -modulate 100,105,100 -unsharp 0x1+0.5+0.05` |
| `deno` | Denoised, mild brightness and saturation boost | `-colorspace sRGB -despeckle -sigmoidal-contrast 3,50% -evaluate multiply 1.07 -modulate 100,105,100 -unsharp 0x1.5+1.0+0.05` |
| `dvi1` | Punchy and vivid, strong saturation | `-colorspace sRGB -despeckle -sigmoidal-contrast 3,50% -evaluate multiply 1.08 -modulate 100,112,100 -unsharp 0x1+0.8+0.05` |
| `dvi2` | Very vivid, high local contrast | `-colorspace sRGB -despeckle -sigmoidal-contrast 4,45% -evaluate multiply 1.12 -modulate 100,118,100 -unsharp 0x1.2+0.6+0.05` |

#### Color-temperature (CT) presets

CT presets are an optional chain element appended after grading (`ct-id`). They apply a white-point shift and per-channel gamma before the grading's sharpening stage. Combine any grading with any CT preset.

| ID | Effect | Description |
|---|---|---|
| `ctw4` | Warm +4 | Noticeable warm shift for mixed-light or candlelit interiors |
| `ctw5` | Warm +5 (gentle) | Subtle warm tint; equivalent of the old `warm`/`dv1w` built-in shift |
| `ctd6` | Daylight neutral | Near-neutral white-point clamp; very slight warm pull |
| `ctc7` | Cool −7 (gentle) | Subtle cool-blue shift; blue-hour and overcast exteriors |
| `ctc9` | Cool −9 | Stronger cool shift; deep blue-hour skies or intentionally cold scenes |

#### Output structure after discovery

Each stack's discovery variants — and all combined intermediates — are written into a z-tier subfolder (`z25/` or `z6/`) inside the stack directory. Only the per-frame source files (ARW, JPG companions, and their raw-converted TIFs) stay in the stack root. The collage is also written into the z-tier subfolder. Alongside this, `ppsp` creates a flat `variants/` folder at the shoot root containing hard links (fallback: copies) to every variant and collage from all stacks — this is the folder you browse and cull from.

```
shoot/
├── 20260416095559-m4azzz-2126-bbfdtw/             ← named stack (shorthand set by --name in step 6)
│   ├── 20260416095559-m4azzz-2126-bbfdtw-a.arw   ← per-frame source files stay in root
│   ├── 20260416095559-m4azzz-2126-bbfdtw-a-z25.tif  ← per-frame raw-converted TIF stays in root
│   └── z25/                                       ← discovery outputs; removed by -C
│       ├── 20260416095559-m4azzz-2126-bbfdtw-z25-aligned0000.tif
│       ├── 20260416095559-m4azzz-2126-bbfdtw-z25-aligned0001.tif
│       ├── 20260416095559-m4azzz-2126-bbfdtw-z25-sel4.tif
│       ├── 20260416095559-m4azzz-2126-bbfdtw-z25-sel4-fatc.jpg
│       ├── 20260416095559-m4azzz-2126-bbfdtw-z25-sel3-fatc-dvi1.jpg
│       ├── 20260416095559-m4azzz-2126-bbfdtw-z25-sel4-m06p-neut.jpg
│       ├── ...
│       └── 20260416095559-m4azzz-2126-bbfdtw-collage.jpg
└── variants/                                      ← hard links to variants + collages; removed by -C
    ├── 20260416095559-m4azzz-2126-bbfdtw-z25-sel3-fatc-dvi1.jpg
    ├── 20260416095559-m4azzz-2126-bbfdtw-collage.jpg
    └── ...
```

#### Collage

After all variants for a stack are produced, a single `<stack-name>-collage.jpg` is written into the z-tier subfolder alongside the variants. All tiles (originals first, then variants) are arranged in a grid whose dimensions are chosen to approximate a 16:9 aspect ratio. Each tile is 640 px wide (preserving the source aspect ratio). Each tile is annotated at the bottom center with its full filename stem in large bold. Individual variant JPEGs are also annotated the same way, so you can identify them from any image viewer without relying on filename display.

### Step 8 — Variant selection

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
| `Generate` | empty (skip) or `x` / `+` / `y` / `yes` (generate); `–`, `n`, `no` also accepted as skip |

```
Filename	Generate
20260416095559-m4azzz-2126-z100-sel3-fatc-dvi2.jpg
20260416095559-m4azzz-2126-z100-sel4-m06p-dvi1.jpg	x
```

```bash
ppsp -g -V ppsp_generate.csv
```

### Step 9 — Generate variants (`--generate` / `-g`)

Generates selected variants at full quality for publishing. Each output is written to `out-{BBBB}/` where `BBBB` is the actual long-side pixel count of the generated image (e.g. `out-7952/` for a z100 Sony a7R IV output). If `--resolution PX` is specified, a second resized copy is also exported to `out-{PX}/` (e.g. `out-2048/`). Any variant already present in any `out-*/` folder is skipped automatically; pass `--redo` to force regeneration. The `-s` flag limits generation to matching stacks.

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

**File path — single JPG**: if the path resolves to a single `.jpg` file, only that variant is processed.

```bash
ppsp -g                            # reads variants/ (default)
ppsp -gV /path/to/my_folder
ppsp -gV variants/20260416095559-m4azzz-2126-z25-sel4-fatn-dvi1.jpg
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
ppsp -D -V some    # 1 enfuse × 2 TMO × 2 gradings, no CT
ppsp -D -V many    # 2 enfuse × 3 TMO × 2 gradings × {∅, ctw5}
ppsp -D -V lots    # 5 enfuse × 8 TMO × 4 gradings × {∅, ctw5}  (≈640 variants)
ppsp -D -V all     # all enfuse × all TMO × all gradings × all CT IDs
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
Original ARW and JPG source files, and the `out-{BBBB}/` export folders, are untouched.
Run this after generation is complete and you no longer need to re-run discovery.

## Output structure

```
shoot/
├── ppsp_photos.csv                             # EXIF catalogue + StackName (tab-separated)
├── ppsp_stacks.csv                             # Stack titles, shorthands and per-stack generate specs (from --name)
├── ppsp_generate.csv                           # Variant selection file (tab-separated)
├── ppsp.log                                    # Full run log
├── cull/                                       # One labeled preview per stack
│   └── 20260416095559-m4azzz-2126-stack_count5.jpg
├── variants/                                   # Hard links to all discovery variants + collages; removed by -C
│   ├── 20260416095559-m4azzz-2126-bbfdtw-z25-sel3-fatc-dvi1.jpg
│   └── 20260416095559-m4azzz-2126-bbfdtw-collage.jpg
├── 20260416095559-m4azzz-2126-bbfdtw/          # Named stack folder (shorthand replaces -stack after --name)
│   ├── 20260416095559-m4azzz-2126-bbfdtw-a.arw  # Shorthand inserted after NNNN in all filenames
│   ├── 20260416095559-m4azzz-2126-bbfdtw-a-z25.tif
│   └── z25/                                    # Discovery outputs: intermediates + variants + collage; removed by -C
│       ├── *-z25-aligned0000.tif
│       ├── *-z25-sel4.tif
│       ├── *-bbfdtw-z25-sel4-fatc.jpg
│       ├── 20260416095559-m4azzz-2126-bbfdtw-z25-sel3-fatc-dvi1.jpg
│       └── 20260416095559-m4azzz-2126-bbfdtw-collage.jpg
├── out-7952/                                   # Full-res finals (from --generate; BBBB = actual long side)
│   └── 20260416095559-m4azzz-2126-bbfdtw-z100-sel3-fatc-dvi2.jpg
└── out-2048/                                   # Resized copies (from --generate --resolution 2048)
    └── 20260416095559-m4azzz-2126-bbfdtw-z100-sel3-fatc-dvi2.jpg
```

## Usage example (actually used on 2026-04-22)

```bash
ppsp -r -l L15
ppsp -o
ppsp -c
# Step 4: ppsp opens cull/ automatically; review and delete unwanted previews
ppsp -P
# Step 6: name surviving stacks interactively
ppsp -n
# Now we have clearly organized, titled stacks of the photos we are really interested in.
# Create discovery variants for the processing chain combinations that will surely include the best versions for each photo in this photoshoot (what is best for a photo depends on lighting and other photo-specific circumstances)
ppsp -DV 'sel4,r02p,fatd,kimd,m06p,neut,deno,dvi1,dvi2' -z z6
# Now we have 24 variants for each stack. Find the best enfuse + tone-mapping combo by comparing the denoised versions:
eog variants/*-deno.jpg

# Generate photos at z25 with one enfuse and one color-grading preset
ppsp -gV 'sel4,r02p,fatd,fatn,kimd,m06p,deno' -z z25
# For a specific stack, discover a specific variant
ppsp -DV sel6-r02p-dvi2 -z z6 -s 2101
ppsp -gz z25
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

**Test data:** place a small set of Sony ARW + JPG pairs in `test_data/`. Tests requiring real image data are automatically skipped if `test_data/` is absent or empty. The directory is gitignored and not distributed with the package. See [design.md](design.md) for the full testing strategy and code architecture.

**Development journal:** [journal.md](journal.md) is a session-by-session narrative log of collaboration and decisions — the human complement to `git log`. Each entry summarises what a working session covered and which commits it produced. Design decisions with lasting architectural significance go in [design.md](design.md) instead.

**Active work:** [wip.md](wip.md) holds specs, wireframes, and annotation notes while work is in flight. It is committed as a snapshot when each piece of work ships, then flushed and refilled for the next topic. See design.md § Development workflow for the full protocol.

## Further reading

For a deep-dive into the underlying tools and the reasoning behind ppsp's built-in presets, see **[guide.md](guide.md)**. It covers:

- RAW conversion with `dcraw` — parameters, colour science, resolution tiers
- Image alignment with `align_image_stack` — feature detection, HDR vs focus-stack modes
- Exposure fusion with `enfuse` — Laplacian pyramid, weight functions, all built-in variant IDs
- Tone-mapping with `luminance-hdr-cli` — every supported operator, parameter guide, when to use each one
- Color grading with ImageMagick — S-curve contrast, proportional brightness scaling, the five built-in grading presets
- Photography-context guide — which operator combinations work best for each shot type

## Related projects

### 1. Core tools used in this ppsp project

These are the foundational command-line utilities that ppsp is empowered by:

| Tool | Core Engine | Primary Focus | Best Used When... | Advantage over Alternatives |
| :--- | :--- | :--- | :--- | :--- |
| **[exiftool](https://exiftool.org/)** | Perl | Metadata | Extracting timestamps and Exposure Compensation. | Superior to `exiv2` for deep metadata coverage and complex tag processing. |
| **[dcraw](https://www.dechifro.org/dcraw/)** | C | RAW Decoding | Converting Sony ARW files to 16-bit TIFFs. | Extremely lightweight and fast compared to full-featured RAW processors. |
| **[hugin-tools](http://hugin.sourceforge.net/)** | PanoTools | Alignment | Pixel-perfect registration of hand-held or vibrating stacks. | `align_image_stack` is the industry-standard CLI for image registration. |
| **[enblend/enfuse](https://enblend.sourceforge.net/)** | C++ | Fusion | Blending exposures into a natural, "human-eye" look. | Produces far more realistic real-estate interiors than traditional HDR tone-mapping. |
| **[Luminance HDR](https://github.com/LuminanceHDR/LuminanceHDR)** | Qt / Multi-Engine | Tone-mapping | Applying specific mathematical operators (e.g., KimKautz, Mantiuk). | Provides access to multiple advanced tone-mapping algorithms in a single CLI/GUI. |
| **[Darktable (CLI)](https://www.darktable.org/)** | OpenCL / RAW | Batch Processing | Applying non-destructive edits and RAW development via scripts. | Highly extensible; allows complex "sidecar" based automation for high-end RAW development. |
| **[ImageMagick](https://imagemagick.org/)** | C / Multiple | Final Polish | Batch color-grading, sharpening, and JPEG conversion. | The most powerful scriptable image manipulation suite available for Linux servers. |

### 2. Other related open-source tools

This table includes the wider ecosystem, including GUI wrappers and specialized scientific stacking tools:

| Tool / Repository | Interface | Primary Focus | Best Used When... | Advantage over Alternatives |
| :--- | :--- | :--- | :--- | :--- |
| **[HDRMerge](https://github.com/jcelaya/hdrmerge)** | GUI / CLI | Raw Merging | Merging brackets into a single 32-bit DNG RAW file. | Better if you want to keep the final file in a RAW format for later editing in Lightroom. |
| **[RawTherapee](https://rawtherapee.com/)** | GUI | Demosaicing | Recovery of extreme highlight detail and noise reduction. | Often provides cleaner demosaicing than dcraw for complex, high-ISO textures. |
| **[Siril](https://siril.org/)** | GUI / CLI | Noise Reduction | Stacking many photos to eliminate sensor noise. | Originally for astrophotography; better than enfuse for extremely dark, noisy indoor scenes. |
| **[PyImageFuser](https://github.com/hvdwolf/PyImageFuser)** | GUI | Exposure Fusion | Simple, manual exposure fusion on a desktop. | Better for users who are uncomfortable with the command line but want the Enfuse look. |
| **[Macrofusion](https://github.com/dandv/macrofusion)** | GUI | Focus Stacking | Merging macro shots with shallow depth-of-field. | Specialized for focus-plane merging rather than dynamic range expansion. |
| **[GIMP](https://www.gimp.org/)** | GUI | Retouching | Removing unwanted objects (cables, trash) from the final shot. | Necessary for "cleaning" a room when the physical space wasn't perfectly staged. |

### 3. Proprietary (non-open-source) alternatives

For professional context, these are the "commercial" competitors that ppsp is designed to disrupt or emulate:

| Software | Platform | Real Estate Context | Best Known For | Why use ppsp instead? |
| :--- | :--- | :--- | :--- | :--- |
| **Adobe Lightroom** | Win / Mac | Industry Standard | Ease of use and cloud sync. | `ppsp` is free, open source, easily scriptable and extensible, and runs natively on Linux. |
| **Photomatix Pro** | Win / Mac | Interior Specialist | Robust "Interior" presets. | `ppsp` offers a more natural "fusion" look without licensing fees. |
| **Affinity Photo** | Multi | Budget Professional | Professional "HDR Persona." | `ppsp` allows for headless, fully automated batch processing. |
| **Aurora HDR** | Win / Mac | AI Automation | Automatic "look" generation. | `ppsp` provides more granular control over the math (mu, sigma, etc.). |
| **LrEnfuse** | Plugin | Adobe Bridge | Bringing Enfuse into Lightroom. | `ppsp` removes the dependency on expensive Adobe subscriptions. |

### 4. Novel AI-powered tools

The following tabulates novel image processing or enhancement tools that leverage AI models:

| Tool Name | Type | Key AI Capability | Best Use Case |
| :--- | :--- | :--- | :--- |
| **Auto-Enhance.ai** | Online | **Sky Replacement & Relighting** | Specifically built for real estate. It detects windows and fixes "blue" casts automatically. |
| **Luminar Neo** | Local / Hybrid | **Relight AI & GenErase** | Uses depth-mapping to adjust lighting in 3D space. Excellent for brightening dark corners naturally. |
| **Topaz Photo AI** | Local | **Sharpen & Denoise** | The gold standard for fixing slight motion blur or sensor noise without losing texture. |
| **Adobe Lightroom (AI)** | Cloud / Local | **Adaptive Presets & Denoise** | Its "Enhance" feature uses AI to demosaic RAWs better than standard algorithms. |
| **Photoroom** | Online / App | **Batch Background/Lighting** | Uses semantic segmentation to separate furniture from walls for localized lighting fixes. |
| **VanceAI** | Online | **HDR Upscaling** | Good for taking "flat" fused images and adding "AI Retouch" to boost local contrast intelligently. |
| **BeFunky AI** | Online | **Enhancer DLX** | A one-click solution that balances exposure and saturation using neural networks. |
| **Magnific.ai** | Online | **Generative Upscaling** | Can take a lower-res merge and "hallucinate" high-end detail (use with caution in real estate). |
| **Google Photos (Magic Editor)** | Online | **Object Erasure & Lighting** | Increasingly powerful for removing "distractions" like stray power cords or trash bins. |
