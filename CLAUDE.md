# CLAUDE.md

This repo is for the development of **ppsp** (Python Photo Stack Producer).

Optimize token spend; Spawn agents only when cost-effective; Advise the user in this.

Key files to rely on:

| File | Contains |
|---|---|
| `README.md` | Variant ID tables (enfuse/TMO/grading), command reference, naming convention, CSV format, collage layout |
| `guide.md` | Pipeline tool parameters and flags (dcraw, enfuse, luminance-hdr-cli, ImageMagick), preset rationale |
| `design.md` | Architecture, code organisation, data models, testing strategy |
| `src/variants.py` | Ground-truth definitions for all variant/TMO/grading IDs and their parameters |
| `src/models.py` | Core data models (Stack, Session, etc.) |
| `src/processing.py` | Image processing pipeline, annotation, collage logic |
| `src/cli.py` | CLI argument definitions |
| `src/naming.py` | File naming logic |
| `changelog.md` | Version history |
| `journal.md` | Work session summaries |
| `wip.md` | Active tasks/specs |

Read `wip.md` at the start of every session, and `journal.md` (or its topmost (=latest) entry) only when necessary.
