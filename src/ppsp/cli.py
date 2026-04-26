"""Argparse entry point — see design.md § CLI-to-function mapping and README.md § Command reference."""

from __future__ import annotations

import sys
from pathlib import Path

from .commands import (
    cmd_arws_enhance,
    cmd_cleanup,
    cmd_cull,
    cmd_discover,
    cmd_generate,
    cmd_name,
    cmd_organize,
    cmd_prune,
    cmd_rename,
    run_full_workflow,
)
from .util import setup_logging
from .interactive import run_interactive_discovery

_SIZE_MAP = {
    "micro": "z2", "z2": "z2",
    "quarter": "z6", "z6": "z6",
    "half": "z25", "z25": "z25",
    "full": "z100", "z100": "z100",
}


def _parse_size(size_str: str | None, default: str) -> str:
    if not size_str:
        return default
    return _SIZE_MAP.get(size_str.lower(), default)


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
    parser.add_argument("--dir", "-d", default=".", metavar="DIR",
                        help="Directory containing shoot images (default: current dir)")
    parser.add_argument("--stacks", "-s", nargs="+", metavar="SPEC",
                        help="Limit scope to matching stacks: full stack name, 4-digit frame number, "
                             "or NNNN-NNNN range (e.g. 2126 or 2126-2150)")
    parser.add_argument("--quality", "-q", type=int, default=80, metavar="INT",
                        help="JPEG quality (default: 80); applies to all conversions including -g output")
    parser.add_argument("--resolution", "-i", type=int, default=None, metavar="PX",
                        help="Long-side pixel cap for -g output; adds a resized copy to out-{PX}/ alongside the full-res out-{BBBB}/ (no default = no resize)")
    parser.add_argument("--batch", "-b", action="store_true",
                        help="Skip all interactive prompts")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Debug-level logging")
    parser.add_argument("--redo", "-R", action="store_true",
                        help="Regenerate outputs even if they already exist")
    parser.add_argument("--interactive", "-I", action="store_true",
                        help="Per-stack interactive discovery with session-based variant narrowing "
                             "(affects -D and full workflow)")
    parser.add_argument("--gui", action="store_true",
                        help="Launch the tkinter GUI — Work in Progress (requires tkinter; Pillow optional for thumbnails)")

    # Options (affect command behaviour)
    opts = parser.add_argument_group("options")
    opts.add_argument("--default-model", "-m", default="", metavar="MODEL",
                      help="Camera model fallback when missing from EXIF (affects -r)")
    opts.add_argument("--default-lens", "-l", default="", metavar="LENS",
                      help="Lens ID fallback when missing from EXIF (affects -r)")
    opts.add_argument("--gap", "-G", type=float, default=30.0, metavar="SECONDS",
                      help="Time gap (s) that triggers a new stack boundary (affects -o, default: 30)")
    opts.add_argument("--variants", "-V", default=None, metavar="SPEC",
                      help="Variant spec for -D and -g: preset level (some/many/lots/all), "
                           "comma-separated IDs, chain specs with Python regex, CSV/TXT file, "
                           "or directory (default for -D: some; default for -g: variants/)")
    opts.add_argument("--size", "-z", default=None, metavar="SIZE",
                      choices=list(_SIZE_MAP.keys()),
                      help="Override resolution tier: z2/micro, z6/quarter, z25/half, z100/full "
                           "(default for -D: z25; default for -g: z100)")
    opts.add_argument("--viewer", default="xdg-open", metavar="VIEWER",
                      help="Image viewer for interactive cull/variants review (default: xdg-open; "
                           "feh --auto-zoom --recursive recommended for rapid keyboard browse)")

    # Command flags
    cmds = parser.add_argument_group("commands")
    cmds.add_argument("--rename", "-r", nargs="*", metavar="FILE",
                      help="Normalize filenames and write ppsp_photos.csv")
    cmds.add_argument("--organize", "-o", nargs="*", metavar="FILE",
                      help="Group files into per-stack folders")
    cmds.add_argument("--cull", "-c", action="store_true",
                      help="Generate labeled culling previews in cull/")
    cmds.add_argument("--prune", "-P", action="store_true",
                      help="Remove stack folders with no surviving cull preview (destructive)")
    cmds.add_argument("--name", "-n", nargs="*", metavar="TITLE_OR_CSV",
                      help="Name stacks: -n (interactive all), -n ppsp_stacks.csv (from CSV), "
                           "-s NNNN -n 'My Title' (inline single stack), "
                           "-s NNNN NNNN -n (interactive for those stacks). "
                           "Creates/updates ppsp_stacks.csv.")
    cmds.add_argument("--discover", "-D", action="store_true",
                      help="Generate variants with annotations for discovery (see options -z, -s and -V)")
    cmds.add_argument("--generate", "-g", action="store_true",
                      help="Generate variants for publishing (see options -z, -s and -V)")
    cmds.add_argument("--arws-enhance", "-e", nargs="*", metavar="FILE",
                      help="Convert ARW files to enhanced JPGs")
    cmds.add_argument("--cleanup", "-C", action="store_true",
                      help="Remove z-tier discovery folders and variants/ (destructive)")

    return parser


def main(argv=None) -> None:
    """CLI entry point dispatching to cmd_* functions — see design.md § CLI-to-function mapping."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    source = Path(args.dir).resolve()
    stacks_specs = list(args.stacks) if args.stacks else None

    # Dispatch
    if args.gui:
        from .gui import launch
        launch(source)
        return

    if args.name is not None:
        name_args = args.name  # list, possibly empty
        title: str | None = None
        csv_path: Path | None = None
        if len(name_args) == 1:
            p = Path(name_args[0])
            if not p.is_absolute():
                p = source / name_args[0]
            if p.suffix.lower() == ".csv":
                csv_path = p
            else:
                title = name_args[0]
        elif len(name_args) > 1:
            title = " ".join(name_args)
        cmd_name(source, stacks_specs=stacks_specs, title=title, csv_path=csv_path, redo=args.redo, batch=args.batch)

    elif args.rename is not None:
        files = [Path(f) for f in args.rename] if args.rename else []
        cmd_rename(files, source,
                   default_model=args.default_model,
                   default_lens=args.default_lens,
                   redo=args.redo)

    elif args.organize is not None:
        files = [Path(f) for f in args.organize] if args.organize else []
        cmd_organize(files, source, gap=args.gap, redo=args.redo)

    elif args.cull:
        cmd_cull(source, quality=args.quality, redo=args.redo)

    elif args.prune:
        cmd_prune(source)

    elif args.discover:
        z_tier = _parse_size(args.size, "z25")
        if args.interactive:
            run_interactive_discovery(
                source,
                z_tier=z_tier,
                quality=args.quality,
                redo=args.redo,
                viewer=args.viewer,
                stacks_specs=stacks_specs,
            )
        else:
            variants = args.variants if args.variants is not None else "some"
            cmd_discover(
                source,
                variants_arg=variants,
                z_tier=z_tier,
                quality=args.quality,
                redo=args.redo,
                stacks_specs=stacks_specs,
                batch=args.batch,
            )

    elif args.generate:
        z_tier = _parse_size(args.size, "z100")
        variants = args.variants if args.variants is not None else "variants/"
        cmd_generate(
            source,
            variants_arg=variants,
            z_tier=z_tier,
            quality=args.quality,
            resolution=args.resolution,
            redo=args.redo,
            stacks_specs=stacks_specs,
        )

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
            resolution=args.resolution,
            batch=args.batch,
            verbose=args.verbose,
            redo=args.redo,
            default_model=args.default_model,
            default_lens=args.default_lens,
            variants_arg=args.variants if args.variants is not None else "some",
            discover_z_tier=_parse_size(args.size, "z25"),
            generate_z_tier=_parse_size(args.size, "z100"),
            viewer=args.viewer,
            interactive=args.interactive,
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
