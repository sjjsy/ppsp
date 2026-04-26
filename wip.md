# wip.md — Work in progress

Active specs, wireframes, brainstorming, and annotations for work currently in
flight. Not stable documentation.

Lifecycle: write here while working → annotate with TODO/FIXME/IDEA/QUESTION →
commit annotated state → revise → when shipped, commit final state then flush
content here and summarise into journal.md and possibly design.md.

## Improvements to the GUI
- The Cull phase should have the "Review cull grid" feature the main and only thing; The Chain configurator and generation should be moved into a new "Variants" tab and step, and the current Discovery view should be named "Select". Basically one can think of the Variants tab as being a GUI for building a command line for a `ppsp -D` command while the Select tab is for building a list of variants (generate targets) for the later `ppsp -g` command. If variants already exist in the variants/ folder, then those should be available in the Select view.
- The Metadata phase should have a column of small thumbnails for each stack and then the whole folder name and RawPhotoCount before the editable metadata columns
- The log bottom panel should preferably be user-resizeable by dragging and by default take about 20% of the total window height.

## Fixes to core tool
- Your recent changes did not provide support for full chains with CT: Now e.g. `ppsp -Dz z6 -V sel4-fatn-neut-ct5w` leads to a "Unknown chain spec 'sel4-fatn-neut-ct5w' in --variants" warning. Make similar warnings an error that halts execution, unless batch mode is active. Also make --variants accept CT specs. Also `sel4-(fatn|kimn|m08n)-neut-ctw5` seemed to also get rejected although regex support was added a few days ago already.
- The --name command does not react to changes made to the CSV; It reports "ppsp_stacks.csv updated" even though it should be the other way: Metadata and stack names updated based on updates to the CSV.
