# wip.md — Work in progress

Active specs, wireframes, brainstorming, and annotations for work currently in
flight. Not stable documentation.

**Lifecycle:** write here while working → annotate with TODO/FIXME → commit
annotated state → revise → when shipped, commit final state then flush content
here and summarise into journal.md / design.md.

---

## GUI specification — v2 (annotated)

Reference: commit `0395460`. The current code implements a rough skeleton.
Items below marked `<!-- TODO -->` or `<!-- FIXME -->` are not yet done.

Design intent: three-tab interface. Tab 1 = Discover (generate variants);
Tab 2 = Review (per-stack pruning in three sequential sub-steps);
Tab 3 = Export (produce full-res finals).

### Pre-tab: Stack culling phase

<!-- TODO: not in current implementation. Needs to run before the notebook is
     constructed, or as a modal sheet launched from Tab 1. -->

Before showing the three-tab view, present a culling grid:
- Thumbnail grid of one representative photo per stack.
- Click toggles keep / prune state (visual distinction — dimmed for prune).
- Double-click → fullscreen with keyboard browse: Space = toggle keep/prune,
  ← / → = previous / next stack, Esc = return to grid.
- "Confirm" button → calls `cmd_stacks_prune()` then rebuilds the stack list.

### Tab 1 — Discover

**Chain configurator** (right pane, current implementation):
- Checkbutton sections for Enfuse, TMO, Grading, Color temp.
- Win counts shown as badge on each option, e.g. `sel4 (×5)`.
  <!-- FIXME: badge reads `session.chain_stats` keyed by full chain strings,
       not by component ID. `sel4` only shows a count if there is a chain_stats
       entry for the bare key "sel4", which there isn't. Need to aggregate
       component-level win counts by summing across all chains that contain
       that component. -->
- Quick preset buttons (some / many / lots / all) — implemented and working.

**Stacks list** (left pane, current implementation):
- Full-height rows with small thumbnail and last-selected chains shown.
  <!-- TODO: redesign as a compact progress-status strip per the spec:
       - One tight row per stack showing: checkbox, short ID, status icon
         (✓ done / ↻ in-progress / — not started).
       - "Done" = has at least one session round; "in-progress" = currently
         generating; "not started" = no rounds yet.
       - Keyboard: ← / → navigate between stacks; Enter = toggle selected. -->

### Tab 2 — Review

Three sequential sub-steps: Enfuse → TMO → Grading.

**Default carry-forward:**
<!-- TODO: when the user moves to a new stack, the sub-step selections should
     be pre-populated from the previous stack's final selections. Currently
     each stack starts empty. Implementation: after `_refresh_review()` sets
     up `self._review_sel[sname]`, if it is empty, copy the final selection
     from the most recently reviewed stack in `self._review_sel`. -->

**Double-click fullscreen:**
<!-- TODO: double-clicking a tile should open the full-size JPG in the system
     viewer (or a simple tkinter Toplevel canvas). Within that fullscreen view:
     ← / → to browse variants in the same step, Space = toggle selection,
     Esc = return to tile grid. -->

**Discard / Reintroduce:**
<!-- TODO: D key (or right-click menu) on a tile should call
     `session.discard_chain(chain_id)` permanently. R key reintroduces.
     SessionState already has `discarded: bool` on ChainStat but the GUI has
     no control for it. Discarded chains should be rendered with the
     `_TILE_BG_DISCARDED` colour and excluded from active set. -->

**Sub-step gating:**
- "Next step ▶" button advances Enfuse → TMO → Grading. Implemented.
  <!-- TODO: gate advancement — require at least one tile selected before
       allowing Next. Show a warning label, not a modal, if the user tries
       to advance with nothing selected. -->

### Tab 3 — Export

**Quality vs. resolution separation:**
<!-- FIXME: current implementation has a single quality Spinbox that appears
     in both Tab 1 (Discover) and Tab 3 (Export) via a shared `_quality_var`.
     The annotation-review FIXME on the v1 spec was that quality (compression)
     and resolution (long-side cap) are independent concerns and should be
     clearly separated in the UI. Current layout already does this (separate
     Entry for resolution, separate Spinbox for quality) — the FIXME is
     actually resolved. Verify and close. -->

**Log panel:**
<!-- TODO: embed a scrollable text widget below the export options that tails
     ppsp.log in real time. Implementation sketch:
     - On Tab 3 show, open ppsp.log (if it exists) and populate the widget.
     - Background thread reads new lines and puts them on `self._queue`.
     - Poll loop appends lines and auto-scrolls (unless user has scrolled up).
     - Collapse/expand button at the top-right of the panel.
     - Ctrl+L keyboard shortcut toggles the panel.
     Log file location: `source / "ppsp.log"` (or wherever `setup_logging`
     writes — check util.py). -->

### Keyboard shortcuts — full coverage plan

| Key | Action |
|---|---|
| Space / Enter | Toggle selection of focused tile |
| ← / → | Previous / next stack (in Tab 1 stack list; in Tab 2 stack combobox) |
| Tab | Advance sub-step in Tab 2 (Enfuse → TMO → Grading) |
| D | Discard focused chain permanently |
| R | Reintroduce discarded chain |
| F / double-click | Open fullscreen view of focused tile |
| Ctrl+E | Trigger Export |
| Ctrl+L | Toggle log panel |
| Esc | Return from fullscreen to tile grid |

<!-- TODO: none of the above shortcuts are currently bound. Add in a dedicated
     `_bind_shortcuts()` method called at end of `__init__`. Use
     `self.root.bind("<Key-…>", handler)` at the Tk root level so shortcuts
     work regardless of which widget has focus. -->

---

## Interactive CLI — open items

**Viewer default:**
The default `xdg-open` opens a folder, which hands off to the system file
manager (Nautilus, Thunar, etc.). For rapid variant review, a dedicated image
viewer with keyboard browse is better: `feh --auto-zoom --recursive` or
`eog` (GNOME Eye of GNOME). Consider changing the default or at least
documenting the recommendation in the CLI help string.
<!-- TODO: update `_open_viewer` default in interactive.py and the `--viewer`
     help text in cli.py to suggest `feh` as an alternative. -->

**Convergence streak and CT variants:**
`session.convergence_streak()` compares the full selected chain list across
the last N rounds. If the user always picks `sel4-m08n-dvi1` plus a varying
CT preset (`ctw5` one round, `ctc7` the next), the streak never converges even
though the base chain is stable.
<!-- FIXME: add an optional `strip_ct` parameter to `convergence_streak()` in
     session.py (default True) that strips any `ct*` suffix from chain IDs
     before comparing rounds. -->

---

## CT chain — resolved items (archive before flush)

The following were open during the 2026-04-25 session and are now resolved:

- CT args prepended to grading args in a single `convert` call, after a single
  `-colorspace sRGB`. Order: `-colorspace sRGB` → CT args → grading args (with
  leading `-colorspace sRGB` stripped from grading to avoid duplication).
  **Implemented** in `processing.py:apply_grading()`.

- `warm` and `dv1w` grading presets retired when CT became a separate element.
  **Done** in variants.py `GRADING_PRESETS`.

- `ctw5` included in `many` and `lots` discovery levels.
  **Done** in variants.py `VARIANT_LEVELS`.

- `_expand_chain_spec_to_all_stacks` was silently omitting `ct_id` from built
  filenames. **Fixed** in commands.py (commit `181f51f`).
