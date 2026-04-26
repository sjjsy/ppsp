# ppsp Development Journal

Human-readable collaboration log: one entry per working session.
The git log is the technical record; this file is the narrative one — it captures context, the
reasoning behind decisions, and which commits a session produced.

Entries are in reverse-chronological order. Timestamps are local time (EEST, UTC+3).

## How to use this file

**Reading:** each entry has a short summary, decisions worth recording, and a commits table.
Design decisions with lasting architectural significance go in design.md; ephemeral discussion
is omitted here.

**Writing an entry:** at the end of a session, ask Claude to write the entry and commit it.
The git log of this file is itself a record of when entries were written.

**Annotation workflow:** when Claude writes a plan or design spec, review it by editing the
document directly with inline TODO/FIXME annotations. Then commit the annotated version before
asking Claude to revise:
```
git add wip.md && git commit -m "Annotate YYYY-MM-DD plan"
```
The diff between the annotated commit and the revised one captures the full review round.
This approach gives spatially-anchored feedback (the comment lives next to the thing it
responds to) while still preserving the exchange in git history.

**Active work lives in wip.md.** Specs, wireframes, brainstorming, and review annotations go
there while work is in flight. When a piece of work is done, wip.md is committed as-is
(capturing the annotated state for the record), then flushed: the relevant decisions are
summarised into journal.md and design.md, and wip.md is emptied for the next topic.

**Session stats:** each entry closes with a Stats table covering wall time,
commit count and range, git diff summary, and logged token and estimated cost figures.
Wall time comes from transcript timestamps. Git numbers come from
`git diff --stat <first>^..<last>`. Token and cost figures are extracted from
`~/.claude/projects/*/\*.jsonl` at session end; leave as `—` if unavailable.

| | |
|---|---|
| Duration | ~Xh (HH:MM – HH:MM EEST) |
| Commits | N · abc1234 – def5678 |
| Files | N files changed, +X insertions(+), -Y deletions(-) |
| claude-sonnet-4-6 | Xk in · Xk out · XM cache↑ · XM cache↓ · ~$X |
| **Total** | **~$X** |

**Relationship to other documents:**
- `git log` — what changed in code and why, in technical terms
- `design.md` — architecture decisions with lasting structural significance
- `journal.md` — session context, conversation-driven decisions, human narrative
- `wip.md` — active specs and annotations; flushed to the above when work ships

---

## 2026-04-26 13:07 — Stack naming: `ppsp -n`, ppsp_stacks.csv, shorthand generation

New feature: human titles for stacks. After culling, the user can name their top stacks
(`ppsp -n`) and the tool stores the titles in EXIF/XMP metadata, renames the stack folders
and contained files to embed a shorthand, and maintains `ppsp_stacks.csv` as the single
source of truth for titles and per-stack generate specs.

### Design decisions

**Shorthand algorithm.** "Bedroom B from the door to the window" → "bbfdtw". The spec
says "omit smaller filler words in the English dictionary". The worked example keeps spatial
prepositions like "from" and "to" (they carry directional meaning in architectural scene
titles) and only omits articles and conjunctions ("the", "a", "an", "and", "or", "but").
The filler set was set conservatively — just those six words — to match the example exactly.

**Stack folder naming.** Named stacks lose the `-stack` suffix; the suffix is replaced by
the shorthand: `YYYYMMDDHHMMSS-CCCxxx-NNNN-stack/` → `YYYYMMDDHHMMSS-CCCxxx-NNNN-bbfdtw/`.
Unnamed stacks keep `-stack`. All code that previously detected stacks via `endswith("-stack")`
was updated to use `is_stack_dir()` from the new `naming.py`, which matches both forms via
`_STACK_DIR_RE = r"^\d{14}-[a-z0-9]{6}-\d{4}-.+$"`.

**Filename shorthand insertion.** Files inside a named stack get the shorthand inserted after
NNNN: `NNNN-a.arw` → `NNNN-bbfdtw-a.arw`; `NNNN-z25-sel4-...jpg` → `NNNN-bbfdtw-z25-sel4-...jpg`.
`parse_chain()` was updated to skip one non-z-tier component between NNNN and the z-tier, so
named-stack filenames parse correctly.

**ppsp_stacks.csv** (tab-separated, columns: StackFolder, Title, Shorthand, Photos, GenerateSpecs).
Auto-created on any `ppsp -n` invocation. GenerateSpecs is a comma-separated list of chain specs
(e.g. `z25-sel4-fatd-dvi1-ctw5`) that `ppsp -g ppsp_stacks.csv` expands per stack. Format is
detected in `_resolve_variants_for_generate` by checking for the `StackFolder` column header.

**out-BBBB/ files are not renamed.** Files exported to `out-BBBB/` are outside the stack dir and
would require a full scan to rename. The user regenerates them with `ppsp -g ppsp_stacks.csv`
after naming if needed. This was noted in the session rather than implemented.

**No new module for cmd_name.** `naming.py` is a pure-utility module (no imports from commands.py),
and `cmd_name` lives in `commands.py` alongside the other `cmd_*` functions. This avoids the
circular import that would arise if naming.py imported `_resolve_stack_specs`.

### New files
- `src/ppsp/naming.py` — shorthand algorithm, stacks CSV I/O, `rename_stack`, metadata writing
- `tests/test_naming.py` — 20 unit tests

### Modified files
- `src/ppsp/cli.py` — `--name`/`-n` flag and dispatch
- `src/ppsp/commands.py` — `cmd_name`; `_resolve_stacks_csv_for_generate`; updated all stack
  detection to `find_stack_dirs()`; updated `_generate_one`, `_expand_chain_spec_to_all_stacks`,
  `_derive_stack_from_filename`, `_filename_to_stack_name` for named stacks
- `src/ppsp/models.py` — `parse_chain()` skips shorthand prefix
- `tests/test_chain.py` — shorthand-prefix parse test

### Stats

| | |
|---|---|
| Duration | ~0.6h (13:07 – 13:44 EEST) |
| Commits | 1 · 5593cf8 |
| Files | 6 files changed, +682 insertions(+), -45 deletions(-) |
| claude-sonnet-4-6 | 6k in · 123k out · 276k cache↑ · 9.5M cache↓ · ~$5.75 |
| **Total** | **~$5.75** |

---

## 2026-04-26 (cont.) — Collaboration infrastructure: four-document system, session stats

Continuation of the 07:56 session (same Claude Code JSONL file). The whole session was
prompted by a question about whether the existing `devlog.md` approach was the best pattern
for collaborating with an AI coding assistant. It evolved into a thorough rethink of how
development context is captured and shared — both between sessions and with other people
joining the project.

The session produced a four-document system, a new active-work file (`wip.md`), automated
session stats extraction, and a changelog for eventual PyPI publication. All of this is
"collaboration infrastructure" rather than ppsp pipeline code — intended to make future
sessions faster and the project more legible to human collaborators.

### Decisions

**Four-document system.** Every development artifact now has a designated home:
- `git log` is the technical record: what changed in code and why.
- `design.md` holds architecture decisions with lasting structural significance —
  constraints, data models, invariants that shape how future code must be written.
- `journal.md` (this file) is the human narrative: session context, conversation-driven
  decisions, the reasoning behind choices that won't be obvious from reading the code.
- `wip.md` is the active-work scratch file: specs, wireframes, and annotation notes
  while work is in flight. Flushed to the above when work ships.

The key insight driving this split: git commit messages explain *what* and *why* in
technical terms, but they lose the conversational context — the wrong turns considered
and rejected, the annotation review round that changed a decision, the rationale behind a
naming choice. journal.md preserves that layer without duplicating the git record.

**wip.md as the annotation-review home.** Before this session, spec/planning content
lived in README.md as TODO markers, which cluttered user-facing documentation and made
it hard to distinguish "design spec under review" from "finished documentation." wip.md
gives that content a proper home with an explicit lifecycle: write → annotate with
TODO/FIXME/IDEA/QUESTION inline → commit annotated state → ask for revision → when
work ships, commit final wip.md state (preserving the review round in git history) then
flush to journal.md/design.md and empty the file for the next topic.

**Annotation notation: plain inline tags.** Chose plain `TODO`, `FIXME`, `IDEA`,
`QUESTION` on their own lines — no HTML comments, no bold asterisks. HTML comments are
invisible in rendered markdown, which defeats the purpose (you want annotations prominent
in a WIP doc). Plain tags are grep-friendly and work in any text editor's search/highlight
feature. The four tags cover the meaningful cases: work to do, something broken, a
suggestion, a decision needed.

**Lowercase documentation filenames.** `DESIGN.md` → `design.md`, `GUIDE.md` →
`guide.md`. The ALL-CAPS convention is a Unix holdover that made sense when directory
listings sorted caps before lowercase; modern tooling gives documentation files visual
distinction through other means. `README.md` stays caps (universally expected; GitHub
auto-renders it). `CLAUDE.md` stays caps (Claude Code requires that exact filename on
Linux).

**changelog.md.** Added following the Keep a Changelog / semver conventions, with
backfilled history: `[0.0.1]` for the initial working implementation, `[0.1.0]` for the
current PyPI-ready state. A CHANGELOG is distinct from journal.md: it is user-facing
(what changed that affects someone installing the package), while journal.md is
developer-facing (how and why the work happened). They don't duplicate each other.

**Stats table in journal entries.** Each entry closes with a Stats table covering
wall time, git diff summary, and per-model token/cost breakdown. The format is
deliberately tool-agnostic: one row per AI model used, so entries from Aider, Cursor,
or other tools can be added alongside Claude's row. This makes it easy to track cost
and effort across the project's history and compare the scope of different sessions.

**`session_stats.py` at user level.** The script that extracts token stats from Claude
Code's `.jsonl` transcript files lives at `~/.claude/scripts/session_stats.py`, not
inside the ppsp repo, because it is useful across all projects. It is paired with a
`/session-stats` Claude Code slash command at `~/.claude/commands/session-stats.md`.
At session end: run `/session-stats range <first>..<last>` and the stats table is
ready to paste into journal.md. All six historical sessions were backfilled using this
script in the same session it was written.

### Commits

| Hash | Message |
|---|---|
| `ce213a7` | Rename devlog.md → journal.md; document collaboration workflow |
| `0cc72f0` | Add wip.md workflow; create wip.md with GUI/interactive open items |
| `80e7982` | Rename DESIGN/GUIDE to lowercase; add changelog.md |
| `1af732d` | Rewrite wip.md notation; add Stats sections to journal entries |
| `ad2ad59` | Backfill journal Stats with real token/cost data |

`session_stats.py` and `/session-stats` are user-level files (`~/.claude/`), not
committed to the ppsp repo.

### Stats

| | |
|---|---|
| Duration | ~5.0h (07:56 – 12:59 EEST) |
| Commits | 5 · ce213a7 – ad2ad59 |
| Files | 18 files changed, 608 insertions(+), 637 deletions(-) |
| claude-sonnet-4-6 | 13k in · 280k out · 684k cache↑ · 21.8M cache↓ · ~$13.35 |
| **Total** | **~$13.35** |

Note: token totals cover the full bf2f9f9e session file, which also contains the
2026-04-26 07:56 bug-fixes work. The two entries cannot be separated at the JSONL level.

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

### Stats

| | |
|---|---|
| Duration | ~3.8h (07:56 – 11:45 EEST) |
| Commits | 4 · a45cfaf – 181f51f |
| Files | 12 files changed, 1916 insertions(+), 30 deletions(-) |
| claude-sonnet-4-6 | see current session — same JSONL file (bf2f9f9e) |
| **Total** | see current session |

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

### Stats

| | |
|---|---|
| Duration | ~6.3h (17:49 – 00:07 EEST) |
| Commits | 2 · 71b3827 – 02aca59 (+ 3 deferred to next session) |
| Files | 10 files changed, 671 insertions(+), 249 deletions(-) |
| claude-sonnet-4-6 | 533 in · 523k out · 2.0M cache↑ · 40.5M cache↓ · ~$27.53 |
| **Total** | **~$27.53** |

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

### Stats

| | |
|---|---|
| Duration | unknown (no transcript) |
| Commits | 0 |

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

### Stats

| | |
|---|---|
| Duration | ~6.0h (18:40 – 00:40 EEST) |
| Commits | 5 · 611386b – b10e9f1 |
| Files | 12 files changed, 659 insertions(+), 955 deletions(-) |
| claude-sonnet-4-6 | 13k in · 390k out · 1.6M cache↑ · 20.2M cache↓ · ~$18.03 |
| **Total** | **~$18.03** |

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

### Stats

| | |
|---|---|
| Duration | ~44.9h wall time (19:53 2026-04-19 – 16:47 2026-04-21, with breaks) |
| Commits | 5 · d353eed – 7c4295d |
| Files | 24 files changed, 4480 insertions(+), 10 deletions(-) |
| claude-sonnet-4-6 | 6k in · 841k out · 5.5M cache↑ · 45.0M cache↓ · ~$46.89 |
| **Total** | **~$46.89** |

---

## 2026-04-19 13:29 — Project initialization

Bootstrap session using the `/init` skill to generate the initial CLAUDE.md and project
structure, then iterating to produce the first working implementation.

### Commits

| Hash | Message |
|---|---|
| `1753f10` | Initial version with todo notes |

### Stats

| | |
|---|---|
| Duration | ~5.2h (13:29 – 18:39 EEST) |
| Commits | 1 · 1753f10 |
| Files | 1 file changed, 577 insertions(+) |
| claude-sonnet-4-6 | 226 in · 257k out · 1.4M cache↑ · 4.8M cache↓ · ~$10.44 |
| **Total** | **~$10.44** |
