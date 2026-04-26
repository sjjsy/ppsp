# ppsp Development Journal

Human-readable collaboration log: one entry per working session.
The git log is the technical record; this file is the narrative one — it captures context, the
reasoning behind decisions, and which commits a session produced.

Entries are in reverse-chronological order. Timestamps are local time (EEST, UTC+3).

## How to use this file

**Reading:** each entry has a short summary, decisions worth recording, and a commits table.
Design decisions with lasting architectural significance go in DESIGN.md; ephemeral discussion
is omitted here.

**Writing an entry:** at the end of a session, ask Claude to write the entry and commit it.
The git log of this file is itself a record of when entries were written.

**Annotation workflow:** when Claude writes a plan or design spec, review it by editing the
document directly with inline TODO/FIXME annotations. Then commit the annotated version before
asking Claude to revise:
```
git add journal.md && git commit -m "Annotate YYYY-MM-DD plan"
```
The diff between the annotated commit and the revised one captures the full review round.
This approach gives spatially-anchored feedback (the comment lives next to the thing it
responds to) while still preserving the exchange in git history.

**Relationship to other documents:**
- `git log` — what changed in code and why, in technical terms
- `DESIGN.md` — architecture decisions with lasting structural significance
- `journal.md` — session context, conversation-driven decisions, human narrative

---

## 2026-04-26 07:56 — Bug fixes, commit catch-up, workflow redesign

Two-part session: implementing six improvement notes left in the previous session; and catching up
on commits for session.py, interactive.py, and gui.py which had been written on 2026-04-25 but
not yet committed. Also a meta-discussion that produced the redesign of devlog.md → journal.md.

### Decisions

- `_generate_one` now forces `redo=True` on the grading step so that discover-annotated
  intermediates in the z-tier folder are never exported as final output. Previously, if a discover
  run had annotated a JPG in the z-dir, a subsequent generate would reuse it.
- `export_at_resolution` was creating `out{N}/` (no dash); corrected to `out-{N}/` to match
  `export_at_full_res` and the `out-*/` glob used for existence checks throughout commands.py.
- `_expand_chain_spec_to_all_stacks` was silently omitting `ct_id` from built filenames in the
  generate path, causing CT variants (e.g. `ctw5`) to be dropped even though `parse_chain` could
  extract them correctly from the filename.
- `_generate_one` skip logic now handles the case where a full-res copy already exists but the
  requested resized copy (`out-{resolution}/`) is missing: fast-paths to resize-from-existing
  rather than reprocessing the full chain.
- Interactive quiz: `tmod` added as option 4; unrecognised input passed through as a custom spec
  rather than silently defaulting to `"some"`; `"skip"` accepted as synonym for `"s"`;
  post-round win summary printed so counts are visible between rounds without entering the menu.
- devlog.md redesigned and renamed to journal.md: HH:mm added to timestamps, entries summarise
  sessions rather than reproduce specs verbatim, commits tabulated per session, annotation
  workflow documented.

### Commits

| Hash | Message |
|---|---|
| `a45cfaf` | Add per-stack interactive discovery with cross-session chain tracking |
| `0395460` | Add tkinter GUI: early-stage prototype, not ready for regular use |
| `0bd2690` | Expand TMO variant table with 10 new presets; revise many/lots/tmod levels |
| `181f51f` | Wire interactive/GUI into CLI; fix generate bugs (ct\_id, out-NNNN, annotations) |

`a45cfaf` and `0395460` contain code written in the 2026-04-25 18:37 session; committed here
after review.

---

## 2026-04-25 18:37 — Interactive discovery, GUI prototype, CT chain, TMO expansion

Long session (18:37 → 00:05 the next morning). Opened with "please read all the TODOs in
README.md and implement them." The TODOs encoded features designed in a planning session around
2026-04-24 (see entry below): the CT chain element, quality/resolution chain suffixes, and TMO
preset expansion. After those were implemented, the session continued into designing and
implementing the interactive per-stack discovery loop and the GUI prototype.

The GUI spec went through an inline annotation review round: Claude wrote a v1 spec; the user
annotated it directly with TODOs and FIXMEs; Claude revised to v2 in the same session. The
interactive loop (session.py, interactive.py) was fully working by end of session. The GUI
prototype (gui.py) was written but committed the next day after review.

### Decisions

- **CT as a separate chain element**: CT adjustments (white-point shift + per-channel gamma) are
  prepended to grading args in a single `convert` call, after a single `-colorspace sRGB`. Order:
  `-colorspace sRGB` → CT args → grading args (leading `-colorspace sRGB` stripped from grading to
  avoid duplication). This keeps visual processing and colour temperature orthogonal; allows CT to
  be varied without changing the grading preset. `warm` and `dv1w` grading presets retired.
- **q/r as generate-time suffixes only**: quality (`-qAA`) and resolution cap (`-rBBBB`) don't
  affect discovery counts or visual chain identity. Omitting them means the CLI `--quality` and
  `--resolution` defaults apply at generate time. They can be encoded in ppsp_generate.csv rows
  to request specific output formats per variant.
- **Session active-set threshold: round 4** (user revised from v1's round 2 during annotation
  review): three full exploratory rounds complete before the active set narrows the default prompt
  choices. Rationale: users need a fair breadth view before the tool starts hiding options.
- **`tmod` preset**: runs every `*d`-suffix (operator-default) TMO variant against a single enfuse
  and grading — useful as a broad first sweep to identify which TMO family suits a scene without
  exploring parameter variants.
- **z2 tier**: half of z6 resolution, for ultra-fast preview at ~1/12 full resolution.
- **GUI architecture**: tkinter front-end calling the same `cmd_*` functions as the CLI; no
  processing logic duplicated. Pillow ≥ 9.0 optional for thumbnails; ImageMagick fallback.

**Session file schema** (`ppsp_session.json` — decided here, still current):
```json
{
  "chain_stats": {
    "sel4-m08n-neut": { "wins": 4, "seen": 6, "discarded": false }
  },
  "rounds": [
    {
      "stack": "20260411-m4aens-2101-stack",
      "generated": ["sel4-m08n-neut", "sel4-fatn-dvi1"],
      "selected":  ["sel4-m08n-neut"]
    }
  ]
}
```
Active set = `wins ≥ 1 && !discarded`, ordered by win count descending.

### Open GUI design items

Not yet implemented. Retained here as a design reference; the GUI is early-stage (see commit
`0395460`). These emerged from the v1→v2 annotation review round.

- **Stack culling phase** before the three-tab view: thumbnail grid, toggle keep/prune,
  double-click fullscreen with keyboard browse (Space = toggle, Esc = return), `cmd_prune()` on confirm.
- **Tab 1**: chain configurator at top with win counts per option (e.g. `sel4(5w)`); stacks as a
  compact progress-status strip below (`✓` done, `↻` in progress, `—` not started).
- **Tab 2**: three sequential sub-steps (Enfuse → TMO → Grading); default selections for a new
  stack copied from previous stack; double-click fullscreen browse within a category.
- **Tab 3**: single quality slider independent of resolution tier (user FIXME on v1 spec).
- **Log panel**: live `ppsp.log` tail, auto-scrolls, loads existing log on launch,
  scrollable/selectable, collapsible; integrated into Tab 3 below export options.
- **Keyboard shortcuts**: full coverage (Space/Enter, ←/→ stacks, Tab sub-steps, D=discard,
  R=reintroduce, F/double-click=fullscreen, Ctrl+E=export, Ctrl+L=toggle log).

### Commits

| Hash | Message |
|---|---|
| `71b3827` | Add z2-tier and several flow and usability improvements |
| `02aca59` | Add several extensions, upgrades and fixes (esp. related to ImageMagick) |

session.py, interactive.py, gui.py were written in this session and committed in the
2026-04-26 07:56 session (`a45cfaf`, `0395460`).

---

## 2026-04-24 (time unknown) — Planning: CT chain, q/r suffixes, TMO expansion

Planning session for which no transcript is available in the project's Claude history — may have
run from a different working directory. Output was a spec encoded as TODOs in README.md,
implemented in the 2026-04-25 18:37 session.

### Decisions

- CT chain element as an optional fourth segment: `enfuse[-tmo]-grading[-ct]`. Five presets
  (`ctw4` through `ctc9`) covering ~4000–9000 K. CT included in `many` and `lots` discovery
  levels with `ctw5`; excluded from `some` to keep it compact.
- Quality and resolution as generate-only format suffixes (`-qAA`, `-rBBBB`), not part of the
  visual chain identity and not expanding discovery counts.
- TMO expansion target: 3 tuned variants per operator beyond the `*d` default. Ferradans and
  Ferwerda deferred (documented flags insufficient for confident preset values at this stage).

### Commits

None — implementation in the 2026-04-25 18:37 session.

---

## 2026-04-21 18:40 — Regex chain expansion and CLI polish

Session focused on making `--variants` expressible as a Python regex pattern matched against the
full enumerated space of valid chain strings, and on general CLI output quality.

### Decisions

- Regex expansion via `re.fullmatch` against an enumerated set of all valid chain strings.
  Two entry points: `expand_chain_pattern` (full specs with z-tier) and
  `expand_variant_chain_pattern` (bare chains for the discover path). Pattern errors log a warning
  and return empty rather than raising.
- `original.py` removed — all functionality had migrated to `commands.py`.
- README restructured into a stable technical reference with a consistent section hierarchy.

### Commits

| Hash | Message |
|---|---|
| `611386b` | Add stdout coloring, improve flag system, argument handling, labels, usability improvements and refactor the README |
| `ec66ca2` | Remove original.py due to deprecation |
| `f89512d` | Clean .gitignore |
| `074718e` | Update text content |
| `b10e9f1` | Add links to related projects |

---

## 2026-04-19 19:53 — Development marathon: bug fixes and first feature wave

Multi-day session through 2026-04-21 16:44 (with likely breaks). Opened with the
align_image_stack bug (JPG companion files were included in alignment input alongside TIFFs;
the aligner requires TIFFs only). Expanded into a broad range of fixes and additions as further
issues emerged during use.

Notable additions: GUIDE.md (deep-dive into tools and preset rationale), the grading and CT
preset tables, usability improvements to the interactive workflow, and processing variations.

### Commits

| Hash | Message |
|---|---|
| `d353eed` | First version with known bugs |
| `aedf235` | Fix companion photo bug |
| `646481d` | Various fixes and improvements |
| `4ee0b77` | Add several improvements and fixes |
| `7c4295d` | Add several usability improvements, processing variations and GUIDE.md |

---

## 2026-04-19 13:29 — Project initialization

Bootstrap session using the `/init` skill to generate the initial CLAUDE.md and project
structure, then iterating to produce the first working implementation.

### Commits

| Hash | Message |
|---|---|
| `1753f10` | Initial version with todo notes |
