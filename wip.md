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
- Add to ppsp_stacks.csv a "Comment" column and store it similar to the other EXIF tags to the files and the JSON. Also show it in the Metadata editor view of the GUI.
- Add CT options for reducing a) red and b) green, relative to other colors. The thing is, in some photos from my living room with a large green carpet the whole room seems to become greenish with some TMOs. And with some TMOs my bathroom gets this reddish tint. It would be good to have CTs to counter those effects.
- Add CG option that is like deno but slightly reduces saturation. This can be good to counter cases where overly saturated TMOs can still be best with some tone down in the color grading phase.
