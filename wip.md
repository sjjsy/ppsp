# wip.md — Work in progress

Active specs, wireframes, brainstorming, and annotations for work currently in
flight. Not stable documentation.

Lifecycle: write here while working → annotate with TODO/FIXME/IDEA/QUESTION →
commit annotated state → revise → when shipped, commit final state then flush
content here and summarise into journal.md and possibly design.md.

## Open items
- Add a `--export DIR, -X` convenience command which takes a destination dir as input and then exports all the images from out folders with "cp -l" style hard linking to the destination. Any --stacks --resolution --variants and other relevant args should work in narrowing the selection of which exports to copy.
