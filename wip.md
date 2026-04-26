# wip.md — Work in progress

Active specs, wireframes, brainstorming, and annotations for work currently in
flight. Not stable documentation.

Lifecycle: write here while working → annotate with TODO/FIXME/IDEA/QUESTION →
commit annotated state → revise → when shipped, commit final state then flush
content here and summarise into journal.md and possibly design.md.


## GUI — pending items (chain stubs + CT step)

QUESTION: For chain stub generation (items below), need clarity before implementing:
- Are stubs additive? i.e. save `z25-sel4.jpg` (enfuse-only) AND `z25-sel4-fatn.jpg`
  (enfuse+TMO without grading) alongside the existing full chains?
- Filename convention for stubs: just omit the missing suffix components?
- In the Discover tab's enfuse step, show ONLY enfuse-only stubs (not full chains)?
  Same for TMO step: show ONLY enfuse+TMO stubs (no grading)?

- Let's refine the whole tool's discovery generation logic such that it generates also chain stub variants: Only enfuse applied, only enfuse + TMO applied, only enfuse + TMO + grading applied. In general, consider refactoring the chain pattern processing logic in the codebase such that it is flexible.
- In the GUI's enfuse and tmo selection steps only show the "chain stub" variants that allow comparison of like vs like (e.g. sel4-fatn vs sel4-fatc without grading differences) that helps make correct decisions within the enfuse or tmo step.
- Add the color temperature discovery/selection step as the fourth step in the GUI's Discovery tab.
