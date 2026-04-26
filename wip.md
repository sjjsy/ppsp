# wip.md — Work in progress

Active specs, wireframes, brainstorming, and annotations for work currently in
flight. Not stable documentation.

Lifecycle: write here while working → annotate with TODO/FIXME/IDEA/QUESTION →
commit annotated state → revise → when shipped, commit final state then flush
content here and summarise into journal.md and possibly design.md.

---

## Add support and facility for image/stack naming

Motivation: In many cases the top 20 stacks/photos from a photoshoot are important enough to deserve their own human name.
This helps when sharing, publishing and discussing the images.
We should allow the user the optional step of specifying short human names or titles for the images after culling. It should be its own command and phase and have its own flags (e.g. --name/-n) and be independent and it should be possible to redo/update the naming.
The given titles should be stored in the image metadata (of all variants and generates but also the original ARWs and JPEGs; using the standard metadata formats EXIF and XMP) such that they are never lost, because naming the stacks is a lot of work for the user, and losing the names is frustrating.
However, short filesystem optimized versions of the titles should also be added to the file names after the image/stack number.
For example: the image/stack 2441 could be added the title "Bedroom B from the door to the window" and this could later result in the following:
     `20260415115544-m4aens-2441-bbfdtw` -- the stack folder
     `20260415115544-m4aens-2441-bbfdtw-z25-sel4-fatd-dvi1-ctw5.jpg` -- the generate file
So the file name shorthand could be a simple lowercase concatenation of the first char of each word while ommitting any smaller filler words in the English dictionary.
Note that we can omit the "-stack" term from all the stack folders; Note that these stack folders would be renamed after every human-led naming round.
Note that we have now both the automatic simple renaming and this human proper naming feature.
One should be able to do an interactive naming round (ppsp -n), or supply a CSV with the titles for each stack to the flag (ppsp -n ppsp_stacks.csv). Also one should be able to run the flag with a specific stack specified (e.g. ppsp -s 1234 -n "Bedroom B from the door to the window").
Actually, let's have the tool automatically create ppsp_stacks.csv whenever --name is invoked and one does not exist and the tool should keep it uptodate. The stacks CSV should provide the basic info for each stack: stack folder name, title, number of photos in the stack and a comma separated list of full filename based generate specs that could be defined and modifed to generate the stacks based on the CSV.
This would allow the user to open the CSV to name the stacks and then simply specify the full processing chains for each generate for each stack (f. ex. z25-sel4-fatd-dvi1-ctw5-q70-r2048). The user might update the CSV during/after discovery, and then simply run `ppsp -g ppsp_stacks.csv` to generate the photos for each stack. If some stack does not have any processing chain spec, the it is simply not generated.
Please update relevant code and documentation.

## GUI specification — v2

Reference: commit `0395460`. The current code implements a rough skeleton.

Design intent: three-tab interface. Tab 1 = Discover (generate variants);
Tab 2 = Review (per-stack pruning in three sequential sub-steps);
Tab 3 = Export (produce full-res finals).

### Pre-tab: Stack culling phase

TODO not in current implementation. Needs to run before the notebook is
constructed, or as a modal sheet launched from Tab 1.

Before showing the three-tab view, present a culling grid:
- Thumbnail grid of one representative photo per stack.
- Click toggles keep / prune state (visual distinction — dimmed for prune).
- Double-click → fullscreen with keyboard browse: Space = toggle keep/prune,
  ← / → = previous / next stack, Esc = return to grid.
- "Confirm" button → calls `cmd_stacks_prune()` then rebuilds the stack list.

### Tab 1 — Discover

Chain configurator (right pane, current implementation):
- Checkbutton sections for Enfuse, TMO, Grading, Color temp.
- Win counts shown as badge on each option, e.g. `sel4 (×5)`.

FIXME badge reads `session.chain_stats` keyed by full chain strings, not by
component ID. `sel4` only gets a count if there is a chain_stats entry for the
bare key "sel4", which there isn't. Need to aggregate component-level win counts
by summing across all chains that contain that component.

- Quick preset buttons (some / many / lots / all) — implemented and working.

Stacks list (left pane, current implementation):
- Full-height rows with small thumbnail and last-selected chains shown.

TODO redesign as a compact progress-status strip:
- One tight row per stack: checkbox, short ID, status icon (✓ done / ↻ in
  progress / — not started). Done = has at least one session round.
- Keyboard: ← / → navigate between stacks; Enter = toggle selected.

### Tab 2 — Review

Three sequential sub-steps: Enfuse → TMO → Grading.

Default carry-forward:

TODO when the user moves to a new stack, sub-step selections should be
pre-populated from the previous stack's final selections. Currently each stack
starts empty. After `_refresh_review()` sets up `self._review_sel[sname]`,
if empty, copy the final selection from the most recently reviewed stack.

Double-click fullscreen:

TODO double-clicking a tile should open the full-size JPG in the system viewer
(or a simple tkinter Toplevel canvas). Within that view: ← / → browse variants
in the same step, Space = toggle selection, Esc = return to tile grid.

Discard / Reintroduce:

TODO D key (or right-click menu) on a tile calls `session.discard_chain(chain_id)`
permanently. R key reintroduces. `SessionState` already has `discarded: bool` on
`ChainStat` but the GUI has no control for it. Discarded chains rendered with
`_TILE_BG_DISCARDED` and excluded from active set.

Sub-step gating: "Next step ▶" advances Enfuse → TMO → Grading. Implemented.

TODO gate advancement — require at least one tile selected before allowing Next.
Show a warning label (not a modal) if the user tries to advance with nothing.

### Tab 3 — Export

Quality vs. resolution: quality (compression) and resolution (long-side cap)
are already separated — shared `_quality_var` Spinbox and a separate resolution
Entry. The v1 FIXME is resolved. Verify and close.

Log panel:

TODO embed a scrollable text widget below export options that tails `ppsp.log`
in real time.
- On Tab 3 show, open `ppsp.log` (if exists) and populate the widget.
- Background thread reads new lines, puts them on `self._queue`.
- Poll loop appends and auto-scrolls (unless user scrolled up).
- Collapse/expand button top-right. Ctrl+L toggles.
- Log location: `source / "ppsp.log"` — confirm in `util.py:setup_logging`.

### Keyboard shortcuts — full coverage plan

| Key | Action |
|---|---|
| Space / Enter | Toggle selection of focused tile |
| ← / → | Previous / next stack (Tab 1 list; Tab 2 combobox) |
| Tab | Advance sub-step in Tab 2 |
| D | Discard focused chain permanently |
| R | Reintroduce discarded chain |
| F / double-click | Fullscreen view of focused tile |
| Ctrl+E | Trigger Export |
| Ctrl+L | Toggle log panel |
| Esc | Return from fullscreen to tile grid |

TODO none of the above are currently bound. Add `_bind_shortcuts()` called at
end of `__init__`. Use `self.root.bind("<Key-…>", handler)` at Tk root level so
shortcuts work regardless of which widget has focus.

---

## Interactive CLI — open items

Viewer default: `xdg-open` opens a folder (hands off to Nautilus/Thunar). For
rapid variant review a dedicated image viewer with keyboard browse is better:
`feh --auto-zoom --recursive` or `eog`.

TODO update `_open_viewer` default in `interactive.py` and the `--viewer` help
text in `cli.py` to recommend `feh` as an alternative.

Convergence streak and CT variants: `convergence_streak()` compares the full
selected chain list. If the user always picks `sel4-m08n-dvi1` plus a varying
CT preset (`ctw5` one round, `ctc7` the next), the streak never converges even
though the base chain is stable.

FIXME add optional `strip_ct` parameter to `convergence_streak()` in
`session.py` (default True) that strips any `ct*` suffix from chain IDs before
comparing rounds.

