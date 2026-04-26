# ppsp Technical Guide

A deep-dive into every tool in the processing pipeline, the reasoning behind ppsp's built-in presets, and a photography-first guide to choosing the right combinations for your scenes.

For the quick-reference preset tables (enfuse IDs, TMO IDs, grading IDs) and command reference, see [README.md](README.md).

---

## Table of contents

1. [The HDR pipeline — overview](#1-the-hdr-pipeline--overview)
2. [RAW conversion — `dcraw`](#2-raw-conversion--dcraw)
3. [Image alignment — `align_image_stack`](#3-image-alignment--align_image_stack)
4. [Exposure fusion — `enfuse`](#4-exposure-fusion--enfuse)
5. [Tone-mapping — `luminance-hdr-cli`](#5-tone-mapping--luminance-hdr-cli)
6. [Color grading — ImageMagick](#6-color-grading--imagemagick)
7. [Photography context guide](#7-photography-context-guide)
8. [Quick-selection table](#8-quick-selection-table)

---

## 1. The HDR pipeline — overview

A modern mirrorless camera captures roughly 14 stops of dynamic range in a single RAW exposure. A typical living room with a sunlit window spans about 16–20 stops from the dark corner behind a sofa to the overexposed sky outside. No single exposure captures all of it, so we shoot a **bracketed sequence** — typically three to five frames at different EV offsets — and merge them in software.

ppsp's discovery pipeline does this in five stages:

```
ARW files
  └─▶ 1. RAW → 16-bit linear TIFF  (dcraw)
  └─▶ 2. Align frames              (align_image_stack)
  └─▶ 3. Exposure fusion           (enfuse)  → TIFF
  └─▶ 4. Tone-mapping              (luminance-hdr-cli)  → JPG
  └─▶ 5. Color grading             (ImageMagick convert)  → final JPG
```

Steps 4 and 5 are each optional for certain stack types:
- Focus stacks skip step 4 entirely (no HDR content to compress).
- Steps 3–5 can be run in "pure enfuse" mode (no TMO) when the bracket is already narrow enough that enfuse output looks good directly.

---

## 2. RAW conversion — `dcraw`

### Why 16-bit linear TIFF?

Camera RAW files store raw sensor data with no tone curve applied. Before any processing, ppsp converts each RAW file to a **16-bit linear TIFF** so that `align_image_stack`, `enfuse`, and `luminance-hdr-cli` can work with standard files in a common colour space.

ppsp uses `dcraw` — the de-facto standard for camera RAW decoding — with these flags:

| Flag | Meaning |
|---|---|
| `-T` | Output TIFF (instead of the default PPM) |
| `-4` | 16-bit linear — no gamma applied; critical for correct exposure weighting downstream |
| `-w` | Use the white balance stored in the EXIF by the camera |
| `-q 3` | AHD (Adaptive Homogeneity-Directed) demosaicing — highest quality |
| `-M` | Auto black-point correction, removes hot-pixel bias |
| `-h` | Half-size output: averages each 2×2 Bayer block into one pixel — the source of `z25` |

The `-4` (linear) flag is the most critical. If a gamma curve were pre-applied, the exposure weight function inside enfuse would treat mid-tones as if they were at the "right" brightness even when the raw data shows them as over- or under-exposed. Linear TIFF ensures that the weight functions see the scene exactly as the sensor recorded it.

### Resolution tiers

ppsp trades pixel count for speed during the discovery phase. The z-tier label is encoded in every output filename so that `--generate` can trace the exact provenance of each intermediate and reuse it without re-running dcraw.

| Tier | Pixel count | How produced | Typical use |
|---|---|---|---|
| `z100` | 100 % | `dcraw` without `-h` | Final `--generate` output |
| `z25` | ≈ 25 % | `dcraw -h` | Default discovery |
| `z6` | ≈ 6.25 % | `dcraw -h` then `mogrify -resize 50%` | Fast discovery |
| `z2` | ≈ 1.56 % | same as `z6` then another `mogrify -resize 50%` | Fastest discovery; useful on very large shoots |

When `z6` is used, ppsp also saves the `dcraw -h` output as a `z25` sibling TIFF automatically. This means a later `--generate variants/ --half` can regenerate at 25% resolution — reusing the aligned and enfused z25 intermediates — without touching dcraw again.

### Darktable fallback

If `dcraw` is not found, ppsp falls back to `darktable-cli`. Darktable does not have a native half-size flag, so for `z6` ppsp saves the full-size output first and then downscales it with `mogrify`. The resulting TIFFs are equivalent for discovery purposes.

---

## 3. Image alignment — `align_image_stack`

### Why alignment matters

Even on a tripod, a bracketed sequence shows sub-pixel movement between frames from mirror slap (DSLR), sensor stabilisation drift, or thermal expansion. Without correction, enfuse blends across spatially mismatched pixels and produces double-edge "ghosting" artefacts at every high-contrast boundary. `align_image_stack` (part of the Hugin panorama project) corrects this by detecting SIFT keypoints in each frame and computing a projective warp that maps all frames into a common reference frame.

### How ppsp calls it

```bash
align_image_stack -a PREFIX -v [INPUT TIFFs...]     # HDR stacks
align_image_stack -a PREFIX -v -m [INPUT TIFFs...]  # focus stacks
```

| Flag | Meaning |
|---|---|
| `-a PREFIX` | Output prefix; produces `PREFIX0000.tif`, `PREFIX0001.tif`, … |
| `-v` | Verbose: logs feature detection progress to the ppsp log |
| `-m` | Optimise field of view — used for focus stacks to handle the tiny magnification change as focus shifts; omitted for HDR stacks |

Aligned TIFFs are written into the stack's `z-tier/` subfolder and removed by `--cleanup` once you no longer need to regenerate.

### Single-frame stacks

If a stack contains only one file (e.g., a single ambient exposure), ppsp skips alignment and passes the file directly to enfuse, which copies it unchanged. The downstream TMO and grading steps still execute, producing a "pseudo-HDR" polish effect — useful when you want the same grading pipeline applied to ambient-only shots alongside true brackets.

---

## 4. Exposure fusion — `enfuse`

### Exposure fusion vs. tone-mapping

Two approaches exist for merging a bracketed set into one displayable image:

**Exposure fusion** (this step): blend pixels from all input frames using per-pixel quality weights. The output is a standard-range TIFF — no HDR file is created. Enfuse uses a **Laplacian pyramid** to do the blending, which means seams are eliminated at every spatial frequency scale and transitions are imperceptible.

**Tone-mapping** (next step): create a full 32-bit HDR representation from all frames and then mathematically compress its range into a displayable image. This produces a separate, distinct look from exposure fusion and can be layered on top of the enfuse output.

In ppsp's pipeline, both happen: enfuse first (to consolidate the bracket into one well-exposed TIFF), then the TMO (to give it character). You can also skip the TMO entirely and grade the enfuse TIFF directly — ppsp does this automatically for all enfuse IDs in the cross-product.

For architectural photography, exposure fusion alone typically produces cleaner, more "photographic" results than tone-mapping alone. The most impactful variants usually combine both.

### How enfuse weights work

For each pixel position, enfuse measures three quality metrics across the input stack:

1. **Exposure quality** — how close the pixel brightness is to a configurable Gaussian target centred at mid-grey (default 0.5 in [0, 1]). Blown pixels and crushed shadows score near zero; well-exposed pixels score near one.
2. **Local contrast** — standard deviation of a small neighbourhood. Sharp detail (window frames, texture) scores high; flat areas (sky, plain walls) score low.
3. **Saturation** — chromatic spread of the neighbourhood. Colourful regions score high; grey or near-white regions score low.

The three scores are multiplied together at each pixel to produce a raw weight. These raw weights are normalised across the stack at each pixel position so they sum to 1.0. The Laplacian pyramid then blends the images at each frequency band using these weights, ensuring seamless transitions.

### Key parameters

| Parameter | Effect | Guidance for real-estate |
|---|---|---|
| `--exposure-weight` | Priority for mid-toned, well-exposed pixels | 0.8–1.0 for natural interiors; lower lifts contrast at the cost of naturalness |
| `--contrast-weight` | Priority for high-local-contrast regions | 0.2–0.4 for smooth rooms; 0.6–0.8 for texture-heavy surfaces |
| `--saturation-weight` | Priority for colourful regions | 0.1–0.2 for interiors; reduce to avoid over-saturating lamplight |
| `--exposure-width` | Width of the Gaussian exposure acceptance curve | Narrower (0.2–0.4) = picks from fewer frames; use with `--hard-mask` |
| `--hard-mask` | Binary 0/1 mask instead of soft weights | Use only for focus stacks — creates sharp transitions between focus planes |
| `--contrast-window-size` | Neighbourhood size for contrast metric | 7–9 prevents halos in large gradient regions (e.g. wall–window boundary) |

### ppsp's built-in enfuse variants

The nine enfuse IDs follow a design progression from broad-blend natural to increasingly selective contrast-focused. See [README.md § Enfuse variants](README.md#enfuse-variants) for the exact flag values.

| ID | Design intent |
|---|---|
| `natu` | Natural balanced blend; full Gaussian acceptance curve. Good default for most brackets. |
| `cons` | Conservative; slightly lower exposure weight prevents lifting hot spots. |
| `sel1`–`sel2` | Selective series begins: narrowing `--exposure-width` makes the tool pickier about which pixels qualify as "well-exposed". |
| `sel3` | Good all-rounder: balanced selectivity and contrast. Often the most versatile choice. |
| `sel4` | **Recommended starting point** for most real-estate work. Enough contrast pull to separate window frames from overexposed sky, without seams. |
| `sel5`–`sel6` | Maximum selectivity; useful for scenes with extreme contrast ratios. May introduce artefacts in low-bracket-count stacks. |
| `cont` | Pure contrast focus, no exposure-width constraint. Best for stone, brick, and industrial surfaces where texture is the whole point. |

**Focus stacks** always use `focu`: `--contrast-weight=1 --saturation-weight=0 --exposure-weight=0 --hard-mask --contrast-window-size=9` — selects pixels purely on sharpness.

---

## 5. Tone-mapping — `luminance-hdr-cli`

### What tone-mapping adds

After enfuse, you have a well-exposed TIFF. The values may still have sub-optimal dynamic range, or the image may look technically correct but tonally flat. Tone-mapping applies a mathematical model to compress or redistribute tonal values, adding the "character" that separates a flat merge from a polished editorial image.

ppsp uses **Luminance HDR CLI v2.6.0**. The enfuse TIFF is passed as a positional argument with a zero EV value:

```bash
luminance-hdr-cli INPUT.tif -e 0 -o OUTPUT.jpg --tmo OPERATOR [--tmoXxx FLAGS] -q QUALITY
```

> **Important:** `-l` is for loading existing `.hdr` or `.exr` HDR files — it does **not** accept TIFFs. The TIFF must be the first positional argument. `-e 0` supplies the mandatory EV metadata that luminance-hdr-cli expects for single-frame input.

### Global flags

These apply to all operators and are used in several of ppsp's tuned variants:

| Flag | Effect |
|---|---|
| `--gamma X` | Gamma applied to the final output (default 2.2). Higher values brighten mid-tones. |
| `--pregamma X` | Gamma applied before the TMO operator runs; lifts shadows into the operator's working range. |
| `--postgamma X` | Gamma applied after the operator; a lightweight brightness lift without re-running the full TMO. |
| `--saturation X` | Scale colour saturation of the output (1.0 = neutral). |
| `-q INT` | JPEG output quality (0–100). |

### Global operators vs. local operators

**Global operators** map every pixel using the same function, based only on scene-wide statistics. The result is always safe, artefact-free, and natural-looking. The trade-off is that they cannot enhance fine local detail independently of large-scale brightness.

**Local operators** analyse pixel neighbourhoods and apply a spatially varying tone curve. They can produce spectacular local contrast ("3D pop") but risk halo artefacts around high-contrast boundaries (window frames, lamp sources) if the parameters are pushed too hard.

| Operator | Family | Visual character | Best contexts |
|---|---|---|---|
| Mantiuk '08 | Local | Clean, editorial, natural sharpness | General interiors — most versatile |
| Mantiuk '06 | Local | Slightly punchier, higher micro-contrast | Textured walls, wood, stone |
| Drago | Global | Soft logarithmic highlight roll-off | Strong window light; blue-hour exteriors |
| Reinhard '02 | Global | Photographic, very clean, lowest artefact risk | Any scene needing safe, neutral results |
| Fattal | Local | High local contrast, "3D pop", dramatic | Exteriors, industrial, creative; risky on plain walls |
| KimKautz | Global | Clean, neutral, "high-end magazine" | Luxury interiors; bright white walls |
| Ferradans | Global | Conservative, neutral | Fallback |
| Ferwerda | Global | Perceptually motivated | Research / comparison |

### Operator parameter reference

#### Mantiuk '08 (`m08*`)

The best general-purpose operator for interior real-estate work. Its local contrast enhancement is subtle by default, producing results that look naturally "editorial" — similar to a high-quality in-camera JPEG from a pro body, but with the full dynamic range of a merged bracket.

| Flag | Effect | Range |
|---|---|---|
| `--tmoM08ColorSaturation X` | Post-mapping colour vibrancy | 1.0–1.3 |
| `--tmoM08ConstrastEnh X` | Contrast enhancement multiplier *(note: intentional Luminance typo)* | 1.5–3.5 |

ppsp presets (see [README.md § Tone-mapping operators](README.md#tone-mapping-operators)):
- `m08d` — Luminance defaults; safe baseline.
- `m08n` — Natural/balanced: `--tmoM08ColorSaturation 1.2 --tmoM08ConstrastEnh 2.0 --gamma 1.2 --saturation 1.2 --postgamma 1.1`. The combined gamma and post-gamma lift keeps the output bright and editorial without feeling pushed. **Default discovery choice for most interior shoots.**
- `m08c` — Contrast/punch: `--tmoM08ColorSaturation 1.3 --tmoM08ConstrastEnh 3.0 --gamma 1.2 --postgamma 1.1`. The same brightness as m08n but with noticeably higher local contrast — use when you need to visually separate window highlights from the room without changing the overall exposure feel.
- `m08m` — Moody/restrained: `--tmoM08ColorSaturation 1.1 --tmoM08ConstrastEnh 1.5 --gamma 1.0 --postgamma 0.95`. Deliberately low enhancement and no brightness lift — the result is darker and less saturated than m08n. Use when m08n reads as over-processed, or when the brief calls for a quiet, atmospheric look rather than an editorial one.

#### Mantiuk '06 (`m06*`)

Older algorithm with a more explicit parameter set. Produces slightly punchier output than Mantiuk '08 at equivalent settings. Very effective on surfaces where texture is the selling point.

| Flag | Effect | Range |
|---|---|---|
| `--tmoM06Contrast X` | Global contrast scale | 0.4–0.8 |
| `--tmoM06Saturation X` | Output saturation | 1.0–1.5 |
| `--tmoM06Detail X` | Local detail enhancement | 0.8–1.2 |

ppsp presets:
- `m06d` — Luminance defaults.
- `m06p` — Punch/pop: `--tmoM06Contrast 0.7 --tmoM06Saturation 1.4 --tmoM06Detail 1.0 --gamma 1.2 --postgamma 1.1`. The operator-specific saturation of 1.4 is the primary colour driver; the gamma lifts ensure brightness is comparable with other tuned presets. Excellent on kitchen worktops, wooden floors, and tiled bathrooms.
- `m06b` — Balanced: `--tmoM06Contrast 0.5 --tmoM06Saturation 1.2 --tmoM06Detail 0.8 --gamma 1.1 --postgamma 1.05`. A gentler version of m06p — enough punch to give surfaces depth without the saturation push becoming distracting. Good starting point when m06p feels too aggressive for a scene.
- `m06s` — Subtle/soft: `--tmoM06Contrast 0.3 --tmoM06Saturation 1.0 --tmoM06Detail 0.6 --gamma 1.15 --postgamma 1.1`. Minimal operator signature with a neutral-saturation, slightly lifted output. The closest Mantiuk '06 gets to a clean global exposure adjustment; useful when texture enhancement would be inappropriate (white walls, minimalist rooms).

#### Drago (`dra*`)

Uses an adaptive logarithmic model inspired by the human visual system's response to absolute luminance. The result is a naturally soft roll-off in bright areas — the closest thing to how your eyes actually experience a room with a sunlit window.

| Flag | Effect | Range |
|---|---|---|
| `--tmoDrgBias X` | Bias the log curve toward shadows (< 0.85) or highlights (> 0.85) | 0.75–0.95 |

ppsp presets:
- `drad` — Luminance defaults.
- `dras` — Soft highlight roll-off with shadow lift: `--tmoDrgBias 0.85 --postgamma 1.1`. The bias leans the logarithmic curve toward bright-area preservation while the post-gamma lift ensures shadows don't look crushed. Excellent for rooms shot toward a window (contre-jour) and for blue-hour exterior shots where point light sources need to stay contained.

#### Reinhard '02 (`r02*`)

Based on the photographic zone system.
Maps scene luminance to display luminance via a key-value-driven sigmoid.
Extremely clean and safe — no halos, no saturation shifts — at the cost of less local contrast enhancement.

| Flag | Effect | Range |
|---|---|---|
| `--tmoR02Key X` | Scene key value (target mid-point luminance) | 0.12–0.22 |
| `--tmoR02Phi X` | Sharpening of the local adaptation curve | 0.8–1.2 |

ppsp presets:
- `r02d` — Luminance defaults.
- `r02p` — Photographic/clean: `--tmoR02Key 0.18 --tmoR02Phi 1.0 --postgamma 1.1`. The 0.18 key is the zone-system standard midpoint. The postgamma lift brings the output brightness in line with other tuned presets, which Reinhard alone tends to leave flat. Lowest artefact risk; good for shots with extreme interior/exterior lighting contrast.

> **Note:** Luminance HDR also includes **Reinhard '05** (`--tmo reinhard05`) — a perceptually more sophisticated evolution. It uses `--tmoR05Brightness`, `--tmoR05Chroma`, and `--tmoR05Lightness` parameters for finer control. It is not currently included in ppsp's preset library but can be used via Mode 3 chain specs or direct `luminance-hdr-cli` invocation.

#### Fattal (`fat*`)

A gradient-domain operator that works on the logarithm of the luminance gradient rather than on luminance itself.
The result is intense local contrast enhancement — images appear almost three-dimensional.
The trade-off is that large luminance gradients (window frames, lamp sources) can produce visible halos if `tmoFatBeta` drops below about 0.85.

| Flag | Effect | Range |
|---|---|---|
| `--tmoFatAlpha X` | Gradient attenuation strength for large edges | 0.7–0.9 |
| `--tmoFatBeta X` | Detail amplification | 0.85–0.95 (< 0.85 risks halos) |
| `--tmoFatColor X` | Output colour saturation | 0.7–1.0 |

ppsp presets:
- `fatd` — Luminance defaults.
- `fatn` — Tamed/natural: `--tmoFatColor 0.8 --gamma 1.3 --postgamma 1.1`. Pulls back Fattal's typically oversaturated and high-contrast output with a reduced colour scale and moderate brightness lifts. The result still has Fattal's characteristic local depth but looks more restrained — useful for exteriors or textured surfaces where full `fatc` would be too aggressive.
- `fatc` — Creative/dramatic: `--tmoFatAlpha 0.8 --tmoFatBeta 0.9 --postgamma 1.05`. Full gradient enhancement with a subtle brightness lift to prevent the output from looking dark. Best for high-contrast exterior shots, exposed concrete, and staircases. **Use with caution on white-wall interiors — gradient enhancement makes surface noise visible.**

#### KimKautz (`kim*`)

A hybrid operator that combines global contrast compression with mild local detail enhancement. The result is clean, neutral, and highly polished — no halos, no colour shift, no artificial micro-contrast. This is the operator most likely to produce the "high-end magazine" look where images feel expensively processed without looking processed.

| Flag | Effect | Range |
|---|---|---|
| `--tmoKimKautzC1 X` | Local contrast enhancement scale | 0.6–1.0 |
| `--tmoKimKautzC2 X` | Global contrast/brightness balance | 0.8–1.4 |

ppsp presets:
- `kimd` — Luminance defaults.
- `kimn` — Natural/luxury: `--tmoKimKautzC1 0.8 --tmoKimKautzC2 1.2 --postgamma 1.1`. The brightness lift brings output in line with other tuned presets. **Recommended starting point for luxury interior and AirBnB listing photography.** Pairs extremely well with `brig` grading for bright, airy rooms.

**Selecting between KimKautz and Mantiuk '08:**
- KimKautz is safer and cleaner on plain white walls and bright rooms. If the key risk is "this room will look like it came out of a real-estate marketing package", use KimKautz.
- Mantiuk '08 adds more micro-contrast to surfaces that benefit from texture enhancement (wood grain, stone, upholstery). If the key asset is material quality, prefer Mantiuk '08.

#### Ferradans (`ferr`) and Ferwerda (`ferw`)

Perceptually motivated global operators included for completeness and research comparison. Ferwerda models chromatic and achromatic visual adaptation. Ferradans is a more recent perceptually-grounded model. Both produce conservative, artefact-free output but are rarely the first choice for real-estate work. ppsp exposes only their Luminance default variants.

---

## 6. Color grading — ImageMagick

### Purpose

Even the best tone-mapped output is often tonally correct but visually flat. The grading step applies a short ImageMagick `convert` pipeline as the last step before the JPEG is written. It adjusts brightness, contrast, colour temperature, and sharpness to produce the "polished" look that client-facing listing photography requires.

Because grading is the final step, its effect compounds with the TMO choice — a strong grading preset on top of a flat TMO can produce results comparable to a moderate grading on a punchier TMO.

### Key operations

#### `-colorspace sRGB`

Always the first operation. TIFF files from the pipeline may carry a linear or camera-native colour profile. Converting to sRGB ensures correct colours on browsers, displays, and print. **Always required; always first.**

#### `-sigmoidal-contrast X,Y%`

Applies a smooth S-curve centred at luminance level Y (as a percentage). X controls curve steepness. The sigmoidal function lifts shadows and deepens highlights simultaneously while protecting both extremes from hard clipping.

Compared to linear `-brightness-contrast`, the sigmoidal operator is safer because it never clips the histogram edges even at high contrast settings. This is why ppsp uses it exclusively for artistic contrast rather than `-contrast`.

Recommended range for interiors: `3–5, 45–50%`.

#### `-evaluate multiply X`

Scales every pixel value by factor X (e.g. `1.10` = +10 % exposure). A proportional lift: shadows stay proportionally darker, highlights scale cleanly, and the tonal relationships established by `-sigmoidal-contrast` are preserved. Used in `brig`, `deno`, and `dvi*` presets to apply a mild overall exposure lift after the S-curve without fighting the S-curve's contrast.

> **Why not `-brightness-contrast`?** The brightness-contrast operator's contrast component compresses the global tonal range — a negative value partially cancels the S-curve added by `-sigmoidal-contrast`. Using `-evaluate multiply` for the lift, and leaving contrast adjustment entirely to the sigmoidal, gives cleaner shadow separation and avoids muddy midtones.

#### `-modulate B,S,H`

Adjusts brightness (B), saturation (S), and hue (H) globally in HSL space. `100,100,100` = no change; values above 100 increase each dimension.

- Boosting S from 100 to 108–125 makes interiors feel more vivid without touching the tone curve.
- Using H slightly below 100 (e.g., 97) desaturates blue slightly — this corrects the common "cold window light" bias that makes interiors shot toward the outside look clinically blue.

#### `-unsharp RADIUSxSIGMA+AMOUNT+THRESHOLD`

Unsharp masking: subtracts a Gaussian-blurred version of the image from the original and adds back the difference, scaled by AMOUNT. Despite the name it sharpens.

- SIGMA controls what spatial scale of edge is targeted.
- AMOUNT controls sharpening strength.
- THRESHOLD sets the minimum edge magnitude to sharpen, preventing flat-area noise from being amplified.

Recommended starting values at discovery resolution (z25): `0x0.8+0.5+0.05`. For full-resolution output: `0x1.2+0.6+0.05`.

#### `-despeckle`

Removes isolated bright or dark pixels (impulse noise). Used in `deno`, `dvi1`, and `dvi2` presets. Most useful for high-ISO interior shots (ISO 800+) where the sensor floor introduces occasional hot pixels.

### ppsp's built-in grading presets

The five grading IDs form a progression from neutral to vivid. See [README.md § Color-grading presets](README.md#color-grading-presets) for the full parameter table.

| ID | Intent | When to use |
|---|---|---|
| `neut` | Minimal: colour space + mild sharpening only | When the TMO output already looks polished |
| `brig` | Bright and vivid, gentle S-curve | Standard AirBnB listing look |
| `deno` | Denoised + moderate punch | High-ISO shots; older sensors |
| `dvi1` | Punchy and vivid, strong saturation | Rooms that need to stand out in a listing grid |
| `dvi2` | Very vivid, high local contrast | Hero shots where maximum impact matters |

Colour-temperature shifts (formerly `warm` / `dv1w`) are now handled by CT presets — pair any grading with `ctw5` for a gentle warm shift (e.g. `neut+ctw5`, `dvi1+ctw5`). See [README.md § Color-temperature (CT) presets](README.md#color-temperature-ct-presets).

---

## 7. Photography context guide

### Real-estate / AirBnB listing shots

**Goal:** bright, airy, natural — viewer should feel the space, not see the processing.

| Scenario | Recommended chain |
|---|---|
| General interior | `sel4-m08n-brig` |
| White walls, luxury finish | `sel4-kimn-brig` |
| Room with strong window light | `sel3-dras-neut-ctw5` |
| Budget property, needs flattering lift | `sel4-m08n-dvi1` |
| High-ISO / dim interior | `sel4-m08n-deno` |

Avoid Fattal (`fatc`, `fatd`) on plain white-wall rooms. The gradient enhancement makes texture noise visible and walls appear dirty.

### High-end detail shots (kitchen fixtures, bathroom tile, flooring)

**Goal:** show material quality; micro-contrast is the key selling signal.

| Scenario | Recommended chain |
|---|---|
| Wood, stone, tile | `sel4-m06p-dvi1` |
| Polished concrete, industrial | `sel6-m06p-dvi1` |
| Maximum drama (feature shot) | `cont-fatc-dvi2` |

### Blue-hour / exterior / balcony views

**Goal:** capture ambient light and city glow without blown-out point sources.

| Scenario | Recommended chain |
|---|---|
| Blue-hour exterior | `natu-dras-neut` |
| Evening cityscape | `natu-r02p-neut-ctw5` |
| Strong sunset | `sel3-dras-neut-ctw5` |

Drago's logarithmic bias contains lamp bloom naturally, which is why it dominates blue-hour work. Reinhard '02 is a safe fallback when Drago feels too "painterly."

### Focus stacks

Focus stacks always use the `focu` enfuse variant. The TMO step is not used — focus stacks typically contain a single EV level, so there is no dynamic-range problem to solve. The grading step still applies.

Recommended: `focu-neut` or `focu-brig`.

### Industrial / stairwells / common areas

**Goal:** structural geometry and raw materials; more dramatic treatment acceptable.

| Scenario | Recommended chain |
|---|---|
| Concrete / brutalist architecture | `cont-fatc-dvi2` |
| Mixed-use / co-working | `sel4-m06p-dvi1` |
| Dark stairwell, details important | `sel6-m06p-deno` |

---

## 8. Quick-selection table

Use this as a starting point for `--variants` Mode 3 chain specs or when manually building a `ppsp_generate.csv`.

| Scene | Enfuse | TMO | Grading | ppsp chain |
|---|---|---|---|---|
| Bright interior, neutral walls | `sel4` | `m08n` | `brig` | `sel4-m08n-brig` |
| Bright interior, luxury finish | `sel4` | `kimn` | `brig` | `sel4-kimn-brig` |
| Room with strong window light | `sel3` | `dras` | `neut` + `ctw5` | `sel3-dras-neut-ctw5` |
| Kitchen / wood / stone texture | `sel4` | `m06p` | `dvi1` | `sel4-m06p-dvi1` |
| Dark interior, high ISO | `sel4` | `m08n` | `deno` | `sel4-m08n-deno` |
| Blue-hour / exterior | `natu` | `dras` | `neut` | `natu-dras-neut` |
| Industrial / dramatic exterior | `cont` | `fatc` | `dvi2` | `cont-fatc-dvi2` |
| Focus stack | `focu` | — | `brig` | `focu-brig` |
| Safe all-rounder (first pass) | `sel4` | `r02p` | `brig` | `sel4-r02p-brig` |

The `some` preset covers `sel4` with `m08n` and `fatn` TMOs and `neut`/`dvi1` gradings — a small, fast discovery set that hits the most useful quadrant of the variant space for most interior shoots.

---

## Further reading

- [Enfuse manual](https://enblend.sourceforge.io/enfuse.doc/enfuse_4.2.xhtml/enfuse.xhtml) — authoritative reference for all parameters
- [Luminance HDR documentation](https://qtpfsgui.sourceforge.net) — operator descriptions and parameter guide
- [Cambridge in Colour — HDR photography](https://www.cambridgeincolour.com/tutorials/high-dynamic-range.htm) — accessible introduction to the physics and workflow
- [ImageMagick usage guide](https://imagemagick.org/Usage/color_mods/#sigmoidal) — sigmoidal contrast and colour modification reference
- [Hugin / align_image_stack documentation](https://hugin.sourceforge.net/docs/manual/Align_image_stack.html) — alignment flags and feature detection details
