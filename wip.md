# wip.md — Work in progress

Active specs, wireframes, brainstorming, and annotations for work currently in
flight. Not stable documentation.

Lifecycle: write here while working → annotate with TODO/FIXME/IDEA/QUESTION →
commit annotated state → revise → when shipped, commit final state then flush
content here and summarise into journal.md and possibly design.md.

## Open items

- `ppsp -n` does not apply CSV edits back to disk. When the user hand-edits `ppsp_stacks.csv`
  and runs `ppsp -n` again, the command should treat the CSV as authoritative and update folder
  names, EXIF sidecars, and in-folder filenames accordingly. Currently the command reads disk
  state and overwrites the CSV (wrong direction).
