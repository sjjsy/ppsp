# wip.md — Work in progress

Active specs, wireframes, brainstorming, and annotations for work currently in
flight. Not stable documentation.

Lifecycle: write here while working → annotate with TODO/FIXME/IDEA/QUESTION →
commit annotated state → revise → when shipped, commit final state then flush
content here and summarise into journal.md and possibly design.md.


## Improvements to the GUI flow
- Add a note the GUI app and the GUI CLI option that the feature is WiP (Work in Progress).
- The "Discover", "Review" and "Export" tabs should be named "Cull", "Discover", and "Generate"
- Ensure there is a "Metadata" tab/step between the Cull and Discover steps that allows the editing of title, tags and rating.
- In general the GUI should match the flow of the whole tool: Indeed add the Rename, Organize and Cleanup steps/tabs into the tool as well into their correct positions and with the relevant options.
- The log should always be visible on the lower one third of the window but collapsible. It should auto uncollapse when starting to generate either discovery variants or exports.
- The thumbnails in all the views should be double the width and height.
- The double click to open full screen does not work. Let's make it such that clicking does moves the "focus" / selection to the image, but does not select it yet as a win.
- Toggle select/unselect and other operations result in the view flickering. This should not happen.
- With the arrows one can move the selection/focus in the grid and with F move to full screen, with D discard the variant, with Space select or unselect it.
- While browsing the candidates in full view, pressing 'c' (c for compare) should show the previously selected variant, to facilitate comparison.
- The relevant keyboard shortcuts for each window/view should always be visible
- In the full screen view of the stack culling phase, show the photo title, rating and tags if available
- I presume it is the "Session winners" that should by default be the variant source and it should be at the top of the radio select.
- The Z-tier choice should be available at the top of the Output options with the default preselected.
- In general the GUI is a GUI for the whole tool but it should work even if some steps would be done before or after via the CLI only.
- Let's refine the whole tool's discovery generation logic such that it generates also chain stub variants: Only enfuse applied, only enfuse + TMO applied, only enfuse + TMO + grading applied. In general, consider refactoring the chain pattern processing logic in the codebase such that it is flexible.
- In the GUI's enfuse and tmo selection steps only show the "chain stub" variants that allow comparison of like vs like (e.g. sel4-fatn vs sel4-fatc without grading differences) that helps make correct decisions within the enfuse or tmo step.
- Add the color temperature discovery/selection step as the fourth step in the GUI's Discovery tab.
