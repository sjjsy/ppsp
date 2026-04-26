# ppsp Development Note Log

Captures ideation, planning sessions, and design decisions as they happen.
Each entry is timestamped and self-contained so that the full line of reasoning can be
reconstructed even after the described features are long implemented.

Entries are in reverse-chronological order (newest first).

---

## 2026-04-26 — Improvement notes

Other:
- I modified the TMO variants in the many/lots presets in variants.py. Please propagate the updates everywhere necessary.
- When I run `ppsp -z z25 -gV variants/ -q 70 -i 2048` after generating images without the -q and -i args it complains "All 5 requested variants already exist in out2048/" even though there is not even such folder. Also, I added dash "-" to the out-NNNN folder name into most places but it seems not all (at least not this complaint).
- When I run `ppsp -gz z25 -V 'sel4-fatd-dvi1-ctw5'` the ctw5 is ignored even though it should definitely not.
- When I run `ppsp -gz z25 -V variants/*ctw5.jpg` the images generated end up having annotations in small font at the bottom center even though generates never should.

CLI flow:
- Variant quiz should accept an alternative number (e.g. 3; include "tmod" as an option!), s or "skip" and anything else should be automatically considered as c/custom and directly processed.
- The active session winners count did not seem to work.

### Implementation — 2026-04-26

**TMO variant propagation** (`interactive.py`): Updated description strings in `_prompt_variant_set` for "many" (now `natu, sel4 × {m08n, r02p, fatn}`) and "lots" (now `5 enfuse × 8 TMO × 4 grading`) to match the current `VARIANT_LEVELS` in `variants.py`. `models.py:_KNOWN_TMOS` already matched.

**out-NNNN folder naming** (`export.py`, `commands.py`): `export_at_resolution` was creating `out{N}/` (no dash); changed to `out-{N}/` matching `export_at_full_res`. Updated `out_desc` in `cmd_generate` log message likewise. Fixed `_generate_one` skip logic: now checks both full-res in `out-*/` AND the resized copy in `out-{resolution}/`; if full-res exists but resized is missing it fast-paths to resize-and-export without reprocessing.

**ctw5 ignored in generate** (`commands.py`): `_expand_chain_spec_to_all_stacks` was building filenames without the `ct_id` segment, so the chain spec was silently dropped before reaching `_generate_one`. Fixed to append `-{ct_id}` when present; `parse_chain` already extracts it correctly.

**Annotations on generate output** (`commands.py`): `_generate_one` grading step now uses `redo=True` unconditionally so it always regenerates the final JPG clean — previously it reused the annotated intermediate left by a prior discover run. The outer `out-*/` existence check still short-circuits when a clean export already exists.

**Variant quiz** (`interactive.py`): Added `tmod` as option 4; shifted `active` to option 5. Added `"skip"` as accepted synonym for `"s"`. Any unrecognised input is now returned directly as a custom chain spec/ID list rather than defaulting to `"some"`. Updated descriptions to match current presets.

**Session winners count** (`interactive.py`): Added a `Session wins: …` print after each round so the cumulative win counts are visible without having to look at the menu option. The count was always tracked correctly; it just wasn't surfaced between rounds.

## 2026-04-25 — Updated spec: CLI narrowing tree + GUI tile selector (v2, post-user-review)

*Author: Claude (incorporating user refinements; see v1 entry below for original brainstorm and v1 spec)*

### Changes from the user between v1 and v2

After reviewing the initial spec the user made the following directed edits and added feedback inline:

**CLI adjustments:**
- "From round 2 onwards" → **"from round 4 onwards"**: the active set should not narrow until three full exploratory rounds have been completed, not just one. This gives the user a fair chance to observe a breadth of chains before the tool starts hiding options by default.
- Default variant level in the one-by-one prompt changed from `[1]` (some) to **`[2]`** (many): starting with a richer initial set on each first-encounter round is more valuable.
- Added `[3] lots — FIXME` to the variant-set menu, requesting that the "lots" preset also be offered and described in the prompt.

**GUI additions (all new):**
- `FIXME` on Tab 3: quality should be a **single control independent of resolution** — not a separate quality per resolution tier.
- `TODO`: add a **stack culling phase before the three-tab view** (browsable thumbnails → mark for deletion → `cmd_prune()`).
- `TODO`: **double-click fullscreen** in Tab 2 (and culling phase) — hide all tabs, show one variant at a time at maximum available resolution, keyboard-browse alternatives, toggle selection.
- `TODO`: **Tab 1 layout rethink** — chain configurator at top, stacks as a progress-status grid below it; keep the tab compact.
- `TODO`: **copy previous-stack selections as defaults** when moving to a new stack — both for per-category selections (Tab 2) and export options (Tab 3). Covers the typical case where similar choices work for consecutive stacks.
- `TODO`: **log panel** — ppsp.log output + progress bar, integrated into Tab 3 below export options, also visible as a side panel in the culling phase, collapsible, loads existing log on launch, scrollable/selectable/copy-pasteable text.
- `TODO`: **keyboard shortcuts** for the full GUI.

---

### Updated CLI spec (v2)

#### Session file

`ppsp_session.json` in the shoot directory, updated after every per-stack review round:

```json
{
  "chain_stats": {
    "sel4-m08n-neut":  { "wins": 4, "seen": 6, "discarded": false },
    "sel4-fatn-dvi1":  { "wins": 3, "seen": 6, "discarded": false },
    "natu-m08n-neut":  { "wins": 0, "seen": 4, "discarded": true  }
  },
  "rounds": [
    {
      "stack": "20260411-m4aens-2101-stack",
      "generated": ["sel4-m08n-neut", "sel4-fatn-dvi1", "natu-m08n-neut"],
      "selected":  ["sel4-m08n-neut"]
    }
  ]
}
```

**Active set** = chains with `wins ≥ 1` and `discarded == false`. On rounds 1–3 the full initial preset is always shown (exploratory phase); from round 4 onwards the default shrinks to the active set, with an explicit option to expand.

**Narrowing trigger**: after every 3 consecutive converging rounds, ppsp offers to apply the current active set to all remaining stacks automatically.

**Wide mode**: any stack can expand to show all chains including discarded ones; a discarded chain that wins prompts for reactivation.

#### Per-stack interactive flow (one-by-one mode) — complete prompt design

```
[Step 6] Discovery — one-by-one or all at once? [1=one-by-one (default) / 2=all]:

--- Stack 1 of 12: 20260411-m4aens-2101-stack ---
Variant set:
  [1] some   — sel4 × {m08n, fatn} × {neut, dvi1}  (8 variants + 2 enfuse-only = 10)
  [2] many   — natu, sel3, sel4 × {m08n, fatn} × {neut, dvi1}  (24 + 6 = 30 variants)
  [3] lots   — natu, sel3, sel4, sel6, cont × {m08n, m08c, m06p, r02p, dras, fatc} × {neut, brig, dvi1, dvi2} × {∅, ctw5}  (≈280 variants)
  [4] active — top chains from session  (not yet available on round 1)
  [5] custom — enter IDs or chain specs as with -V
Choice [2]: 1

Generating 10 variants at z2... done (8.1s)
Opening viewer. Delete unwanted variants, then press Enter.

Detected survivors: sel4-m08n-neut, sel4-fatn-dvi1
Session updated: sel4-m08n-neut×1 (seen 1), sel4-fatn-dvi1×1 (seen 1)

...

--- Stack 4 of 12 ---                    ← active set kicks in from round 4
Active set (2 chains): sel4-m08n-neut, sel4-fatn-dvi1
Expand? [1=some / 2=many / 3=lots / 5=custom / w=wide mode / n=use active set (default)]:
```

After 3 consecutive rounds with a stable winner set:

```
sel4-m08n-neut and sel4-fatn-dvi1 have won the last 3 rounds in a row.
Apply only these to all 8 remaining stacks without asking? [Y / n / ask per stack]:
```

No good options on this stack? Wide mode:

```
None of these work? [w = wide mode (show all chains including discarded)]:
```
If a discarded chain wins, ppsp offers to reactivate it globally.

#### Implementation

New files:
| File | Purpose |
|---|---|
| `src/ppsp/session.py` | `SessionState` dataclass + `load_session()` / `save_session()` JSON helpers |
| `src/ppsp/interactive.py` | `run_interactive_discovery()` — the one-by-one loop |

`cmd_discover()` gains `session: Optional[SessionState] = None`; when set, it snapshots the z-tier folder before opening the viewer, compares after Enter, and records `selected` = surviving files. `run_full_workflow()` gains `mode` parameter (`"batch"`, `"all"`, `"one-by-one"`).

---

### Updated GUI spec (v2)

#### Architecture (unchanged from v1)

`ppsp --gui` / `ppsp-gui` → tkinter app. Calls `cmd_discover()`, `cmd_generate()`, session helpers. No processing logic duplicated. Optional dep: `Pillow ≥ 9.0` (`pip install ppsp[gui]`); fallback: ImageMagick thumbnail generation.

#### Phase 0 — Stack culling (new)

Shown on launch if no cull has been completed yet, or re-entered from Tab 1 via a "Re-cull stacks" button.

```
┌─────────────────────────────────────────────────────────────────────┐
│  Stack culling  (14 stacks)                              [Log ▶ |]  │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐                        │
│  │    │ │    │ │    │ │    │ │    │ │    │  ...  (scrollable grid) │
│  └────┘ └────┘ └────┘ └────┘ └────┘ └────┘                        │
│  [✓]2101 [✗]2102 [✓]2103 [✓]2104  [✓]2105 [✓]2106                │
│  keep   PRUNE   keep    keep    keep    keep                        │
│                                                                     │
│     [Prune marked stacks and continue to discovery ▶]              │
└─────────────────────────────────────────────────────────────────────┘
```

- Click a tile or checkbox to toggle keep/prune.
- Double-click a tile → **fullscreen single-image view**: image fills the window, all chrome hidden. Left/Right arrow keys browse the other stacks one-by-one. Space = toggle keep/prune. Esc = return to grid.
- "Prune marked stacks" calls `cmd_prune()` and advances to Tab 1.
- Log panel side-bar (collapsible, right side): shows live `ppsp.log` tail.

*Tile size (resolved):* Tiles are sized at a comfortable default (≈200 px) and the grid respects a global tile-size slider accessible from a toolbar. The same slider applies to Phase 0, Tab 1 stack grid, and Tab 2 variant tiles.

#### Tab 1 — Discovery setup

Chain configurator at top; stacks progress grid below it as a compact status strip.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Chain configurator                                                   │
│  Enfuse: [✓]sel4(5w) [✓]natu(0w) [✓]sel3(3w) [ ]sel6 [ ]cont ...   │
│  TMO:    [✓]m08n(4w) [✓]fatn(3w) [ ]m06p(2w) [ ]fatc [ ]dras ...   │
│  Grade:  [✓]neut(4w) [✓]dvi1(3w) [ ]brig(1w) [ ]dvi2 [ ]deno ...   │
│  CT:     [ ]ctw4    [✓]ctw5(3w) [ ]ctd6    [ ]ctc7  [ ]ctc9 ...   │
│  Size: ● z2  ○ z6  ○ z25                                             │
│                                  [Generate for checked stacks ▶]     │
│──────────────────────────────────────────────────────────────────────│
│  Stacks                                    [Re-cull stacks]          │
│  ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ┌──┐ ...  (thumbnail + status)     │
│  │  │ │  │ │  │ │  │ │  │ │  │ │  │                                 │
│  └──┘ └──┘ └──┘ └──┘ └──┘ └──┘ └──┘                                │
│  ✓2101 ✓2102 ↻2103 —2104 —2105 —2106 —2107                          │
└──────────────────────────────────────────────────────────────────────┘
```

Stack status icons: `✓` = selections complete, `↻` = in progress, `—` = not yet started.
Win counts shown in brackets per option (e.g., `sel4(5w)`) inform which IDs have consistently won.

#### Tab 2 — Per-stack review tree

```
┌─────────────────────────────────────────────────────────────────────┐
│  [← 2102]  Stack 2103 (3 of 12)  [2104 →]     Step 1/3: Enfuse     │
│                                                                      │
│  ┌──────┐  ┌──────┐  ┌──────┐                                       │
│  │ img  │  │ img  │  │ img  │                                        │
│  │ sel4 │  │ natu │  │ sel3 │   wins: 5w  0w  3w                    │
│  │ [✓]  │  │ [🗑] │  │ [ ]  │                                        │
│  └──────┘  └──────┘  └──────┘                                       │
│                                                                      │
│                                         [Next: TMO variants ▶]      │
└─────────────────────────────────────────────────────────────────────┘
```

- **Three sequential sub-steps**: Enfuse → TMO (for each selected enfuse) → Grading (for each selected enfuse-TMO).
- **Win count badge** on every tile.
- **🗑** = discard globally (remove from active set for all future stacks). **↩** = reintroduce discarded option.
- **Default selections when opening a new stack** = copy of the selections made for the previous stack (at each sub-step). The user can change them; this is just the pre-fill.
- **Double-click a tile** → fullscreen single-image view: one variant at a time centred in the window, all tabs hidden. Left/Right navigates through the category alternatives (e.g., all enfuse options for this stack). Space = toggle selection. Esc = return to tile grid.

#### Tab 3 — Export + log

```
┌──────────────────────────────────────────────────────────────────────┐
│  Export options  (stack 2103: sel4×m08n×neut, sel4×fatn×dvi1)        │
│                                                                       │
│  Z-tier:   [ ] z6   [✓] z25   [ ] z100                               │
│  Quality: [────────●────────] 85                                      │
│  Output size: [     2048     ] px long side  (blank = full z-tier)   │
│                                                                       │
│  [✓] Prune non-selected variants from variants/                        │
│  [ ] Run ppsp --cleanup (remove z-tier discovery folders)             │
│                                                                       │
│  Session CSV: ppsp_generate_20260425-143012.csv         [Export ▶]    │
│                                                                       │
│  *Default export options copied from previous stack; adjust as needed │
│──────────────────────────────────────────────────────────────────────│
│  ppsp.log                                               [▲ collapse]  │
│  2026-04-25 14:30:01 | INFO | === Full workflow starting ===          │
│  2026-04-25 14:30:12 | INFO | Stack 2103: 10 variants generated       │
│  2026-04-25 14:31:02 | INFO | Stack 2104: 10 variants generated       │
│  ...                                                                   │
│  [████████████░░░░░░░░░░░░░░] 48%                                     │
└──────────────────────────────────────────────────────────────────────┘
```

Key design notes:
- **Quality is a single slider** applying to all selected z-tiers.
- **Output size** (`--resolution` / `-i`): optional long-side pixel cap. When specified, the resized copy is written to `out-{N}/` in addition to (or instead of) the full-tier output in `out-{BBBB}/`. If blank, the output is at the z-tier's native resolution.
- **Output folder naming** (`out-BBBB`): outputs are no longer written to `out_full/` and `out_web/`. Each output file goes to a folder named `out-{BBBB}/` where BBBB is the actual long-side pixel count of the file (measured after generation). A `--resolution N` export goes to `out-{N}/`. This makes folder names self-documenting.
- **Export options are pre-filled** from the previous stack's choices.
- **Log panel** (`ppsp.log` tail): auto-scrolls, loads existing log content on GUI launch, scrollable/selectable/copy-pasteable, collapsible.
- **Progress bar** appears below log during active generate/discover runs.
- Export calls `cmd_generate()` in a background thread.

#### Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` / `Enter` | Toggle tile selection / confirm action |
| `←` / `→` or `h` / `l` | Navigate between stacks |
| `↑` / `↓` or `k` / `j` | Navigate within tile grid |
| `Tab` | Advance to next sub-step (Enfuse → TMO → Grading → Export) |
| `Shift+Tab` | Go back one sub-step |
| `D` | Discard hovered/focused tile globally |
| `R` | Reintroduce last discarded option |
| `W` | Wide mode (show all options including discarded) |
| `F` / `Double-click` | Fullscreen view of hovered tile |
| `Esc` | Close fullscreen / return to grid |
| `Ctrl+E` | Trigger export |
| `Ctrl+L` | Toggle log panel |
| `Ctrl+←` / `Ctrl+→` | Jump to first unprocessed stack |
| `1`–`5` | Select preset level in CLI one-by-one prompt |

#### New files / entry points (updated)

| Path | Purpose |
|---|---|
| `src/ppsp/session.py` | `SessionState` dataclass + `load_session()` / `save_session()` JSON helpers |
| `src/ppsp/interactive.py` | `run_interactive_discovery()` — CLI one-by-one loop |
| `src/ppsp/gui.py` | `App(tk.Tk)` — Phase 0 + three-tab application; global tile-size toolbar slider |
| `src/ppsp/export.py` | Replace `copy_to_full`/`make_web_copy` with `export_at_full_res` / `export_at_resolution`; `outBBBB` folder naming via `_get_long_side()` |
| `src/ppsp/cli.py` | Add `--resolution` / `-i` flag; pass to `cmd_generate()` and `run_full_workflow()` |
| `pyproject.toml` | `ppsp-gui` console script; `[gui]` optional dep: `Pillow >= 9.0` |

#### Shared session state (unchanged from v1)

Both CLI and GUI read/write `ppsp_session.json`. The timestamped `ppsp_generate_YYYYMMDD-HHmmss.csv` output is identically formatted and consumed by `ppsp -g -V`.

---

---

## 2026-04-25 — Flow improvements: CLI narrowing tree and GUI tile selector (v1, initial)

*Author: user (ideas) + Claude (initial spec)*

### Discussion summary

The user observed that the current `ppsp` discovery workflow is stateless: every run requires manually specifying which variants to generate and then manually culling results. There is no memory of which processing chains performed well across stacks, forcing repetitive choices. Two complementary improvements were proposed:

1. **CLI**: make the per-stack interactive discovery loop smarter by tracking which chains have historically been selected ("won") and using that history to narrow the default variant set in subsequent rounds. The narrowing should be gradual and reversible, and the user should always be able to explore the full space.

2. **GUI**: provide a visual tile-selection flow (`ppsp --gui`) where the user progresses through a three-stage tree (enfuse → TMO → grading), selecting winners at each stage with visual feedback and persistent win-count badges. The GUI should eventually produce the same output formats as the CLI.

Both flows should share a session state file so a session started in one can be continued in the other.

---

### Idea 1 (original, user-authored)

For variants discovery, it could ask whether to do discovery for stacks one-by-one or all at one go.
If one-by-one, the discovery variants are generated for a single stack and then user is asked to cull the variants for that and only after that another round is started.
It could interactively ask how many or which variants to do: list the predefined options and their contents (e.g. "some" which would be the default/recommendation), but also offer a custom input choice which would be processed exactly like -V arguments.
It should list all the variants that were selected on one or more of the previous rounds for information (along with the selection counts of each), and after the first three rounds, it should also offer the option of only including those "winning" variants into this next round's discovery process.
After every 3 rounds of the user choosing the same option, it should ask whether to apply it to all of the remaining stacks.

---

### Idea 2 (original, user-authored)

Let's add a --gui flag that provides the following GUI tile selection tree based pruning flow:
- presents a browsable tiling of all the stacks for stack selection
- asks for the processing chain alternatives to include in the tree: enfuse + tmo + color-grading; The selection could be faciliated with series of checkboxes or similar, then generates them in z2; by default all included in "many" should be selected
- then goes through each stack and ...
    - presents a browsable tiling of all the generated enfuse variants for enfuse selection (if two or more per stack; allows the user to select more than one for next stages)
    - presents a browsable tiling of all the generated tmo variants for each selected stack-enfuse combo (if two or more per combo; allows the user to select more than one for each for next stages)
    - presents a browsable tiling of all the generated color grading variants for each selected stack-enfuse-tmo combo (if two or more per combo; allows the user to select more than one for each)
    - for each step, the tiling should somehow show how many times each option was chosen in the past for previous rounds, such as to help the user to "learn" and remember, and choose accordingly; The tool could also allow the user to discard a processing chain option from the tree such to avoid having it to clutter future rounds; However, the tool should also allow to reintroduce initially or later discarded options (ie. edit the tree)
- provides checkboxes: a) generate all the chosen combos in z6, z25 and/or z100 and which quality (60, 80, 90, 95); b) prune the variants from non-selected variants; c) Run `ppsp -C`
- then executes according to the checkbox selections for all chosen enfuse-tmo-grading combos, storing the generate decisions into ppsp_generate_YYYYMMDD-HHmmss.csv

---

### Initial spec (Claude, v1)

Both flows share a **session file** (`ppsp_session.json`) in the shoot directory and the same underlying processing functions. The GUI is a front-end, not a reimplementation. The CLI uses `--viewer` to open images; the GUI displays its own tile grid.

#### CLI flow (Idea 1)

##### Session tracking and the narrowing tree

`ppsp_session.json` is written after every per-stack review round:

```json
{
  "chain_stats": {
    "sel4-m08n-neut":  { "wins": 4, "seen": 6, "discarded": false },
    "sel4-fatn-dvi1":  { "wins": 3, "seen": 6, "discarded": false },
    "natu-m08n-neut":  { "wins": 0, "seen": 4, "discarded": true  }
  },
  "rounds": [
    {
      "stack": "20260411-m4aens-2101-stack",
      "generated": ["sel4-m08n-neut", "sel4-fatn-dvi1", "natu-m08n-neut"],
      "selected":  ["sel4-m08n-neut"]
    }
  ]
}
```

**Active set** = chains with `wins ≥ 1` and `discarded == false`. On round 1 the full initial preset is the active set; from round 2 onwards only past winners appear by default.
*(Note: the user later revised "round 2" to "round 4" — see v2 entry.)*

**Narrowing trigger**: after 3 consecutive rounds in which all selected chains are a strict subset of the winning chains seen so far, ppsp offers to apply just those chains to all remaining stacks without asking again.

**Wide mode**: for any individual stack the user can request wide mode to expose all chains, including discarded ones. If a discarded chain wins in wide mode, ppsp asks whether to reactivate it globally.

##### Per-stack interactive discovery flow (one-by-one mode, v1)

```
[Step 6] Discovery — one-by-one or all at once? [1=one-by-one (default) / 2=all]:

--- Stack 1 of 12: 20260411-m4aens-2101-stack ---
Variant set:
  [1] some   — sel4 × {m08n, fatn} × {neut, dvi1}  (8 variants)
  [2] many   — natu, sel3, sel4 × {m08n, fatn} × {neut, dvi1}  (24 variants)
  [3] active — top chains from session  (sel4-m08n-neut×3, sel4-fatn-dvi1×2)  (2 variants)
  [4] custom — enter IDs or chain specs as with -V
Choice [1]:

Generating 8 variants at z2... done (8.1s)
Opening viewer. Delete unwanted variants, then press Enter.

Detected survivors: sel4-m08n-neut, sel4-fatn-dvi1
Session updated: sel4-m08n-neut×4 (seen 5), sel4-fatn-dvi1×3 (seen 5)

--- Stack 2 of 12 ---
Active set (2 chains): sel4-m08n-neut, sel4-fatn-dvi1
Expand? [some / many / custom / w=wide mode / n=use active set (default)]:
```
*(Note: user later added `[3] lots` option, changed default to `[2]`, and pushed active-set activation to Stack 4 — see v2.)*

##### Implementation (v1)

New files: `src/ppsp/session.py`, `src/ppsp/interactive.py`. `cmd_discover()` gains optional `session` parameter.

---

#### GUI flow (Idea 2, v1)

##### Architecture

`ppsp --gui` / `ppsp-gui` → tkinter. Calls `cmd_discover()`, `cmd_generate()`, session helpers. Optional dep: `Pillow ≥ 9.0`.

##### Window layout — three tabs (v1)

**Tab 1 — Stacks & chains**

```
┌──────────────────────────────────────────────────────────────────────┐
│  Stacks (14)                         Chain configurator               │
│  ┌────┐ ┌────┐ ┌────┐ ┌────┐        Enfuse: [✓]sel4 [✓]natu [✓]sel3│
│  │cull│ │cull│ │cull│ │cull│                [ ]cons [ ]sel1 ...      │
│  └────┘ └────┘ └────┘ └────┘        TMO:    [✓]m08n [✓]fatn [ ]m06p│
│  [✓]2101 [✓]2102 [ ]2103 [✓]2104           (win counts in brackets) │
│  ...                                 Grade:  [✓]neut [✓]dvi1 [ ]brig│
│                                      Size:  ● z2  ○ z6  ○ z25       │
│                                      Quality: [──────●──] 80         │
│                               [Generate for checked stacks ▶]        │
└──────────────────────────────────────────────────────────────────────┘
```

**Tab 2 — Per-stack review tree** (three sub-steps: Enfuse → TMO → Grading; win count badges; 🗑/↩ per tile; ←/→ stack navigator)

**Tab 3 — Export**

```
  [ ] z6 resolution    Quality: [80]
  [✓] z25 resolution   Quality: [90]    ← FIXME (user): quality should be
  [ ] z100 resolution  Quality: [95]       independent of resolution choice
  [✓] Prune non-selected variants
  [ ] Run ppsp --cleanup
  Session CSV: ppsp_generate_20260422-143012.csv  [Export ▶]
```

##### User TODOs on the v1 GUI spec (verbatim)

> **FIXME (Tab 3):** Quality choice should be independent of resolution choice.

> **TODO:** Let's add a stack culling step before this three tab view that focuses on just the stack culling; after the selections have been made, it should ask whether to delete the images from cull/ and run cmd_prune() to remove the corresponding stack folders.

> **TODO (Tab 2):** Allow the user to double click an image to open it in max resolution at the center of the window (hiding all the tabs) and browse the category alternatives one by one (only one variant in view at a time at the same spot; largest z-tier available; of course with `ppsp --gui -z z6` only z6 variants would be available) and toggle the selection; This should also be available for the stack selection/culling step.

> **TODO (Tab 1):** Let's allow the user to return to do further stack culling but otherwise the focus is on discovery and generation, so let's show the stack thumbnails and progress status (whether the chains and export options have been selected for which stack yet) below the chain configurator as a distinct component in tab 1; Also to make the tab not consume that much screen real estate.

> **TODO:** While I understand the chain configurator in tab 1 controls which variants to generate for discovery, I propose that when moving to discover a new stack in tab 2, the selections for each category would by default be copied from those for the previous stack. Similarly, the export options in tab 3 should allow individual export option selection for each stack but when moving to a new stack, the default selection should also here be a copy of those for the previous stack.

> **TODO:** A panel should be added to the right to show ppsp.log output (including all prune, discover, generate and cleanup and other command outputs as they progress) and the progress bar below it; The log output and the progress bar complement the user in understanding the progress and what is happening "under the hood". This panel should appear also in the stack culling phase should be hideable and reopenable. When just starting the GUI it should show whatever the log file already contained if it existed. The log view should be browsable (up and down and the text should be selectable and copy-pasteable). In the three tab view it should be integrated into tab 3 below the export options as a distinct component.

> **TODO:** Add keyboard shortcuts for efficient mouse-free operation over the whole GUI app.

##### Implementation (v1)

New files: `src/ppsp/gui.py`. Entry point: `ppsp-gui` + `ppsp --gui`. Optional dep `[gui]`: `Pillow >= 9.0`.

---

---

## 2026-04-24 — Variant system: CT chain element, quality/resolution chain elements, and TMO preset expansion

*Author: user (problem statement) + Claude (spec)*

### Context

Three improvements to `variants.py` and the chain spec were identified during a review of the grading preset table:

1. **Color temperature as a separate chain element.** `warm` and `dv1w` currently bake CT adjustments (white point shift + per-channel gamma) together with tone/contrast operations, making it impossible to vary them independently. The fix: introduce an optional `ct` chain segment whose args are prepended to the grading args in the same ImageMagick `convert` call, then retire `warm` and `dv1w`. CT participates in discovery and is included in the `some`/`many`/`lots` shortcuts.

2. **Quality and resolution as explicit chain elements.** The old `-web` suffix triggered a hardcoded quality/resize step. Replace it with `-qAA` (JPEG quality, 0–100) and `-rBBBB` (long-side pixel cap, e.g. 2048) as optional chain segments with explicit numeric values. These are generate-time output-format parameters — they do not affect the visual processing decision and are therefore **not** part of discovery; they do not increase combination counts for `some`/`many`/`lots`.

3. **TMO preset expansion.** The target is 3 tuned variants per operator (beyond the `d`-suffix default). Most operators currently have 1 or 2. Ferradans and Ferwerda have no documented tunable flags and are deferred.

---

### CT stage spec

#### Chain position and arg ordering

The full chain spec is now: `z_tier-enfuse[-tmo]-grading[-ct][-qAA][-rBBBB]`

The core visual-processing chain (used for discovery and naming) is `enfuse[-tmo]-grading[-ct]`.
The output-format suffixes `[-qAA][-rBBBB]` are appended at generate time only.

Examples:
- `sel4-m08n-dvi1` — no CT, no format override (backward-compatible)
- `sel4-m08n-dvi1-ctw5` — dvi1 grading with warm ~5000 K shift
- `sel4-dvi1-ctw4` — enfuse-only chain, very warm ~4000 K shift
- `z25-sel4-m08n-dvi1-ctw5-q90-r2048` — full spec: z25 discovery tier, warm CT, 90% JPEG at max 2048 px long side

CT and grading args are merged into a **single ImageMagick `convert` call**. Within that call the order is: `-colorspace sRGB` → CT args → grading args (with their own leading `-colorspace sRGB` stripped). This preserves the ordering from `warm`/`dv1w`, where colour-channel adjustments precede contrast/brightness/sharpening — the correct sequence since those ops should operate on the colour-shifted values.

#### CT presets

| ID | Effect | ImageMagick args (inserted before grading args) |
|---|---|---|
| `ctw4` | Very warm ~4000 K | `+level-colors black,#fff8e8 -channel R -gamma 1.10 -channel G -gamma 1.04 -channel B -gamma 0.90 +channel` |
| `ctw5` | Warm ~5000 K | `+level-colors black,#fffef5 -channel R -gamma 1.07 -channel G -gamma 1.03 -channel B -gamma 0.95 +channel` |
| `ctd6` | Neutral anchor ~6500 K (near-identity) | `+level-colors black,#fffffe` |
| `ctc7` | Slightly cool ~7500 K | `+level-colors black,#f5f8ff -channel R -gamma 0.95 -channel G -gamma 0.97 -channel B -gamma 1.06 +channel` |
| `ctc9` | Cool ~9000 K / overcast blue | `+level-colors black,#f0f4ff -channel R -gamma 0.92 -channel G -gamma 0.95 -channel B -gamma 1.12 +channel` |

`ctw5` reproduces the CT component of the existing `warm`/`dv1w` presets.

#### CT in discovery shortcuts

`VARIANT_LEVELS` gains a 4th tuple element `ct_ids`. The discovery engine cross-products `grading × ct_ids` (empty `ct_ids` means no CT variants are generated for that level):

| Level | CT IDs | Rationale |
|---|---|---|
| `some` | `[]` | Keeps the compact set truly compact |
| `many` | `["ctw5"]` | One warm option — the most common interior-photography case |
| `lots` | `["ctw5"]` | Same warm option; avoids count explosion (cool CT is lower-priority for interiors) |
| `all` | all CT IDs | Full cross-product |

With this, `many` roughly doubles in count (base chains + same chains with ctw5), and `lots` similarly. The resulting totals remain reasonable for z2 discovery.

#### Migration: retiring `warm` and `dv1w`

- `dv1w` → `dvi1` + `ctw5` (very close match; `dvi1` already has despeckle/sigmoidal/sharpening).
- `warm` → `neut` + `ctw5` (approximate; `warm` had a second B-channel gamma pass and a `modulate 100,105,97` not present in `neut` — acceptable for real-world use; a `neuw` grading ID can be added if exact parity is needed).

Both `warm` and `dv1w` are removed from `GRADING_PRESETS` immediately (no CSV files reference them yet). Any other CT content embedded in grading presets is extracted at the same time.

---

### Quality and resolution chain elements

#### `-qAA` — quality override

Encodes the JPEG quality used in the final `convert` call. `q80` → `-quality 80`. If absent, the chain inherits the `--quality` CLI flag (default 80) at generate time — so omitting it from the chain is equivalent to always matching the CLI default. Including it pins a specific quality to a named output, allowing e.g. `sel4-m08n-dvi1-q95` for a high-fidelity archival generate alongside a default-quality discovery variant.

#### `-rBBBB` — resolution cap (long side)

Caps the longest image dimension to BBBB pixels using `-resize BBBBx>` (ImageMagick's "shrink only, preserve aspect" form). `r2048` → `-resize 2048x>`. If absent, no resize is applied beyond what the z-tier already provides. Replaces the old `-web` flag, which was a hardcoded resize to an implicit web size.

#### Segment ordering in chain string

The format suffixes always trail the visual chain:

```
enfuse[-tmo]-grading[-ct][-qAA][-rBBBB]
```

Within a single ImageMagick call, the final command order is:

```
convert <input> -colorspace sRGB [CT args] [grading args] [-quality AA] [-resize BBBBx>] <output>
```

Quality and resize come last because they operate on the fully processed pixel data.

#### Parsing

`parse_variant_chain()` recognises `q\d+` and `r\d+` segments by pattern (not table lookup), since their values are numeric rather than predefined IDs. They are valid in any position after the core `grading` segment and before or after `ct`.

#### No discovery impact

`q` and `r` do not expand combination counts. The one-by-one flow, `some`/`many`/`lots` shortcut definitions, and `_all_valid_variant_chains()` enumerate chains without q/r segments. Quality and resolution are selected separately at generate time — either via CLI flags or via the GUI export panel.

Note: The user can however modify ppsp_generate.csv to include rows with specific -qAA-rBBBB segments to request specific generates.

---

### Code changes (all three features)

| File | Change |
|---|---|
| `src/ppsp/variants.py` | Add `CT_PRESETS: Dict[str, List[str]]`; expand `VARIANT_LEVELS` tuples to 4 elements; update `parse_variant_chain()` to accept 2–6-part specs (enfuse, optional tmo, grading, optional ct, optional q-segment, optional r-segment); extend `_all_valid_variant_chains()` to include ct combinations; remove `warm`/`dv1w` from `GRADING_PRESETS` |
| `src/ppsp/models.py` | `ChainSpec` gains `ct_id: Optional[str] = None`, `quality: Optional[int] = None`, `long_side: Optional[int] = None`; chain label and `parse_chain()` updated accordingly |
| `src/ppsp/processing.py` | `apply_grading()` accepts `ct_id`, `quality`, `long_side`; builds merged command: one `-colorspace sRGB`, then CT args, then grading args, then `-quality`, then `-resize`; removes `-web` handling |
| `src/ppsp/cli.py` | Remove `-web`/`--web` flag if present; no new flags needed (q/r are chain-encoded) |
| `README.md` / `GUIDE.md` | New "Color temperature presets" table; remove `warm`/`dv1w` rows; document q/r chain syntax; remove `-web` docs |

---

### TMO preset expansion

Target: 3 tuned variants per operator in addition to the `d`-suffix default. Existing variants must not change.

#### Gaps and proposed new IDs

**Mantiuk '08** — currently: `m08n`, `m08c` → needs 1 more
- `m08m` — Moody / restrained: `--tmoM08ColorSaturation 1.1 --tmoM08ConstrastEnh 1.5 --gamma 1.0 --postgamma 0.95` — lower enhancement, slightly darker; useful when m08n reads as over-processed

**Mantiuk '06** — currently: `m06p` → needs 2 more
- `m06b` — Balanced: `--tmoM06Contrast 0.5 --tmoM06Saturation 1.2 --tmoM06Detail 0.8 --gamma 1.1 --postgamma 1.05` — gentler than m06p; good general-purpose alternative
- `m06s` — Subtle / soft: `--tmoM06Contrast 0.3 --tmoM06Saturation 1.0 --tmoM06Detail 0.6 --gamma 1.15 --postgamma 1.1` — minimal operator signature; closest to a clean lift

**Drago** — currently: `dras` → needs 2 more
- `drab` — Higher bias (more shadow detail): `--tmoDrgBias 0.95 --postgamma 1.05`
- `dran` — Neutral bias: `--tmoDrgBias 0.75 --postgamma 1.0`

**Reinhard '02** — currently: `r02p` → needs 2 more
- `r02h` — High-key / bright: `--tmoR02Key 0.28 --tmoR02Phi 1.0 --postgamma 1.15`
- `r02m` — Moody / dark: `--tmoR02Key 0.10 --tmoR02Phi 1.0 --postgamma 1.0`

**Fattal** — currently: `fatn`, `fatc` → needs 1 more
- `fats` — Soft / low-gradient: `--tmoFatColor 0.6 --tmoFatAlpha 0.5 --tmoFatBeta 0.95 --gamma 1.1 --postgamma 1.1` — reduced local contrast for scenes where Fattal tends to over-texture

**KimKautz** — currently: `kimn` → needs 2 more
- `kiml` — Low contrast / dark: `--tmoKimKautzC1 0.5 --tmoKimKautzC2 0.9 --postgamma 1.0`
- `kimv` — Vibrant / punchy: `--tmoKimKautzC1 1.0 --tmoKimKautzC2 1.5 --postgamma 1.15`

**Ferradans / Ferwerda** — deferred. The available `--tmoFer*` flags are not documented in the Luminance HDR v2.6.0 man page and need empirical testing before committing to preset values.
