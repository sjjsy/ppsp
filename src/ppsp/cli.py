"""Argparse entry point — see DESIGN.md § CLI-to-function mapping and README.md § Command reference."""

from __future__ import annotations

import sys
from pathlib import Path

from .commands import (
    cmd_arws_enhance,
    cmd_cleanup,
    cmd_generate,
    cmd_rename,
    cmd_stacks_cull,
    cmd_stacks_organize,
    cmd_stacks_prune,
    cmd_stacks_process,
    run_full_workflow,
)
from .util import setup_logging


def _build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="ppsp",
        description=(
            "ppsp — Post Photoshoot Processing\n\n"
            "Automates renaming, stacking, HDR/focus fusion, grading and export for\n"
            "real-estate and architectural photographers.  Run without a command flag\n"
            "to walk through all steps interactively.\n\n"
            "See README.md for the full command and variant reference."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global options
    parser.add_argument("--source", "-s", default=".", metavar="DIR",
                        help="Directory containing shoot images (default: current dir)")
    parser.add_argument("--quality", "-q", type=int, default=80, metavar="INT",
                        help="JPEG quality for all internal conversions (default: 80)")
    parser.add_argument("--batch", "-b", action="store_true",
                        help="Skip all interactive prompts")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Debug-level logging")
    parser.add_argument("--redo", "-R", action="store_true",
                        help="Regenerate outputs even if they already exist")

    # Command flags (mutually exclusive group allows one command at a time)
    cmds = parser.add_argument_group("commands")

    cmds.add_argument("--rename", "-r", nargs="*", metavar="FILE",
                      help="Normalize filenames and write ppsp_photos.csv")
    cmds.add_argument("--default-model", "-m", default="", metavar="MODEL",
                      help="Camera model fallback when missing from EXIF")
    cmds.add_argument("--default-lens", "-l", default="", metavar="LENS",
                      help="Lens ID fallback when missing from EXIF")

    cmds.add_argument("--stacks-organize", "-o", nargs="*", metavar="FILE",
                      help="Group files into per-stack folders")
    cmds.add_argument("--gap", "-G", type=float, default=30.0, metavar="SECONDS",
                      help="Time gap (s) that triggers a new stack (default: 30)")

    cmds.add_argument("--stacks-cull", "-c", action="store_true",
                      help="Generate labeled culling previews in cull/")

    cmds.add_argument("--stacks-prune", "-p", action="store_true",
                      help="Remove stack folders with no surviving cull preview")

    cmds.add_argument("--stacks-process", "-P", nargs="*", metavar="STACK",
                      help="Variant discovery at reduced resolution")
    cmds.add_argument("--variants", "-V", default="some", metavar="LEVEL_OR_LIST",
                      help="Preset level (some/many/all) or comma-separated IDs (default: some)")
    cmds.add_argument("--fast", "-f", action="store_true",
                      help="Use z13 resolution instead of z25")

    cmds.add_argument("--generate", "-g", nargs="+", metavar="TARGET",
                      help="Generate variants from chain filenames, CSV, or TXT")

    cmds.add_argument("--arws-enhance", "-e", nargs="*", metavar="FILE",
                      help="Convert ARW files to enhanced JPGs")

    cmds.add_argument("--cleanup", "-C", action="store_true",
                      help="Remove intermediate TIFFs from stack folders")

    return parser


def main(argv=None) -> None:
    """CLI entry point dispatching to cmd_* functions — see DESIGN.md § CLI-to-function mapping."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    source = Path(args.source).resolve()

    # Dispatch
    if args.rename is not None:
        files = [Path(f) for f in args.rename] if args.rename else []
        cmd_rename(files, source,
                   default_model=args.default_model,
                   default_lens=args.default_lens,
                   redo=args.redo)

    elif args.stacks_organize is not None:
        files = [Path(f) for f in args.stacks_organize] if args.stacks_organize else []
        cmd_stacks_organize(files, source, gap=args.gap, redo=args.redo)

    elif args.stacks_cull:
        cmd_stacks_cull(source, quality=args.quality, redo=args.redo)

    elif args.stacks_prune:
        cmd_stacks_prune(source)

    elif args.stacks_process is not None:
        stacks = list(args.stacks_process) if args.stacks_process else []
        cmd_stacks_process(stacks, source,
                           variants_arg=args.variants,
                           fast=args.fast,
                           quality=args.quality,
                           redo=args.redo)

    elif args.generate:
        cmd_generate(list(args.generate), source, quality=95, redo=args.redo)

    elif args.arws_enhance is not None:
        files = [Path(f) for f in args.arws_enhance] if args.arws_enhance else []
        cmd_arws_enhance(files, source, quality=args.quality, redo=args.redo)

    elif args.cleanup:
        cmd_cleanup(source)

    else:
        # Full interactive / batch workflow
        run_full_workflow(
            source=source,
            gap=args.gap,
            quality=args.quality,
            batch=args.batch,
            verbose=args.verbose,
            redo=args.redo,
            default_model=args.default_model,
            default_lens=args.default_lens,
            variants_arg=args.variants,
            fast=args.fast,
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        import logging
        logging.warning("Interrupted")
        sys.exit(130)
    except Exception:
        import logging
        logging.exception("Unhandled error")
        sys.exit(1)
