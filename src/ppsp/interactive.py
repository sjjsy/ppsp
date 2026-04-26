"""Per-stack interactive discovery CLI loop with session-based variant narrowing.

Invoked via ``ppsp -D --interactive`` or from ``run_full_workflow`` with ``interactive=True``.
Recommended viewer for rapid variant review: ``feh --auto-zoom --recursive``
(pass via ``--viewer`` flag); default ``xdg-open`` opens a folder browser instead.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from .naming import find_stack_dirs, is_stack_dir
from .session import SessionState, load_session, save_session
from .variants import VARIANT_LEVELS, parse_variant_chain

_BATCH_THRESHOLD = 3  # consecutive identical rounds before offering auto mode


def run_interactive_discovery(
    source: Path,
    z_tier: str = "z25",
    quality: int = 80,
    redo: bool = False,
    viewer: str = "xdg-open",
    stacks_specs: Optional[List[str]] = None,
    batch_threshold: int = _BATCH_THRESHOLD,
) -> None:
    """Run per-stack interactive discovery with session tracking and convergence narrowing.

    For each stack the user chooses a variant set, reviews results in a viewer, deletes
    unwanted JPGs, then presses Enter.  After ``batch_threshold`` rounds selecting the same
    chains the user is offered to auto-apply those chains to all remaining stacks.
    """
    from .commands import cmd_discover, _resolve_stack_specs

    session = load_session(source)

    stacks_filter = _resolve_stack_specs(stacks_specs or [], source)
    if stacks_filter is not None:
        stack_dirs = sorted(
            source / n for n in sorted(stacks_filter) if (source / n).is_dir()
        )
    else:
        stack_dirs = find_stack_dirs(source)

    if not stack_dirs:
        logging.warning("No stack directories found under %s", source)
        return

    total = len(stack_dirs)
    print(f"\nInteractive discovery: {total} stacks at {z_tier}")
    if session.active_chains():
        print(f"Session active chains: {session.win_summary()}")

    auto_chains: Optional[List[str]] = None  # set when user activates auto mode

    i = 0
    while i < len(stack_dirs):
        stack_dir = stack_dirs[i]
        stack_name = stack_dir.name

        print(f"\n{'─'*60}")
        print(f"Stack {i + 1}/{total}: {stack_name}")

        if auto_chains is not None:
            print(f"Auto mode ({len(auto_chains)} chains): {', '.join(auto_chains)}")
            ans = input("Override? [y = choose manually, Enter = use auto]: ").strip().lower()
            if ans == "y":
                auto_chains = None
            else:
                _generate_and_review(
                    source, stack_dir, stack_name,
                    ",".join(auto_chains), z_tier, quality, redo, viewer,
                    session,
                )
                i += 1
                continue

        variants_arg = _prompt_variant_set(session)
        if variants_arg is None:
            print("Stack skipped.")
            i += 1
            continue

        selected_chains = _generate_and_review(
            source, stack_dir, stack_name,
            variants_arg, z_tier, quality, redo, viewer,
            session,
        )

        if session.active_chains():
            print(f"  Session wins: {session.win_summary()}")

        # Convergence check — offer auto-apply if stable pattern emerging
        if session.convergence_streak() >= batch_threshold and i < len(stack_dirs) - 1:
            remaining = len(stack_dirs) - i - 1
            active = session.active_chains()
            print(
                f"\n✓  {', '.join(active[:4])} have won {session.convergence_streak()} rounds in a row."
            )
            ans = input(
                f"Apply only these {len(active)} chains to all {remaining} remaining stacks"
                " without asking? [Y/n]: "
            ).strip().lower()
            if ans != "n":
                auto_chains = active

        i += 1

    # Rebuild variants/ with only the selected chains for all processed stacks
    _rebuild_variants_dir(source, z_tier, session)
    print(f"\nInteractive discovery complete. Summary: {session.win_summary()}")


def _generate_and_review(
    source: Path,
    stack_dir: Path,
    stack_name: str,
    variants_arg: str,
    z_tier: str,
    quality: int,
    redo: bool,
    viewer: str,
    session: SessionState,
) -> List[str]:
    """Generate variants for one stack, open viewer, detect survivors, record round."""
    from .commands import cmd_discover

    print(f"Generating ({variants_arg} / {z_tier})…", end=" ", flush=True)
    cmd_discover(
        source,
        variants_arg=variants_arg,
        z_tier=z_tier,
        quality=quality,
        redo=redo,
        stacks_specs=[stack_name],
    )

    generated = _scan_z_dir(stack_dir, z_tier)
    print(f"{len(generated)} variants")

    if not generated:
        return []

    z_dir = stack_dir / z_tier
    _open_viewer(viewer, z_dir)
    print(f"Viewer opened on {z_dir.name}/")
    print("Delete unwanted variant JPGs, then press Enter.")
    input()

    selected = _scan_z_dir(stack_dir, z_tier)
    if not selected:
        print("Nothing survived — keeping all variants.")
        selected = generated

    removed = set(generated) - set(selected)
    if removed:
        print(f"Removed: {', '.join(sorted(removed))}")
    print(f"Kept:    {', '.join(selected)}")

    session.record_round(stack_name, generated, selected)
    save_session(session, source)
    return selected


def _prompt_variant_set(session: SessionState) -> Optional[str]:
    """Prompt the user to choose a variant set. Returns variants_arg string or None to skip."""
    active = session.active_chains()

    opts = [
        ("1", "some  ", "sel4 × {m08n, fatn} × {neut, dvi1}"),
        ("2", "many  ", "natu, sel4 × {m08n, r02p, fatn} × {neut, dvi1} + ctw5"),
        ("3", "lots  ", "5 enfuse × 8 TMO × 4 grading + ctw5"),
        ("4", "tmod  ", "sel4 × all default TMOs × neut + ctw5"),
    ]
    if active:
        opts.append(("5", "active", f"session winners: {session.win_summary()}"))
    opts.append(("c", "custom", "enter IDs or chain specs"))
    opts.append(("s", "skip  ", "skip this stack"))

    for key, label, desc in opts:
        print(f"  [{key}] {label} — {desc}")

    choice = input("Choice [1]: ").strip().lower()

    if choice in ("", "1"):
        return "some"
    if choice == "2":
        return "many"
    if choice == "3":
        return "lots"
    if choice == "4":
        return "tmod"
    if choice == "5" and active:
        return ",".join(active)
    if choice in ("c", "5"):
        val = input("IDs or chain specs (comma-separated): ").strip()
        return val if val else "some"
    if choice in ("s", "skip"):
        return None
    # Anything else is treated directly as a custom chain spec or ID list
    return choice or "some"


def _scan_z_dir(stack_dir: Path, z_tier: str) -> List[str]:
    """Return sorted list of variant chain IDs found in stack_dir/z_tier/."""
    z_dir = stack_dir / z_tier
    if not z_dir.exists():
        return []
    chains = []
    for f in sorted(z_dir.glob("*.jpg")):
        if "collage" in f.name:
            continue
        chain = _filename_to_chain(f.name, z_tier)
        if chain and chain not in chains:
            chains.append(chain)
    return chains


def _filename_to_chain(filename: str, z_tier: str) -> Optional[str]:
    """Extract bare chain string from a variant filename like '*-z25-sel4-m08n-dvi1.jpg'."""
    stem = Path(filename).stem
    marker = f"-{z_tier}-"
    idx = stem.find(marker)
    if idx == -1:
        return None
    chain_str = stem[idx + len(marker):]
    if parse_variant_chain(chain_str) is not None:
        return chain_str
    return None


def _open_viewer(viewer: str, path: Path) -> None:
    try:
        subprocess.Popen([viewer, str(path)])
    except OSError as exc:
        logging.warning("Could not open viewer '%s': %s", viewer, exc)


def _rebuild_variants_dir(source: Path, z_tier: str, session: SessionState) -> None:
    """Rebuild variants/ keeping only the last-selected chains for each processed stack."""
    variants_dir = source / "variants"
    variants_dir.mkdir(exist_ok=True)

    processed = {r.stack for r in session.rounds}

    for stack_dir in find_stack_dirs(source):
        if stack_dir.name not in processed:
            continue

        stack_rounds = [r for r in session.rounds if r.stack == stack_dir.name]
        selected = stack_rounds[-1].selected if stack_rounds else []
        z_dir = stack_dir / z_tier
        if not z_dir.exists():
            continue

        for chain in selected:
            for src in z_dir.glob(f"*-{z_tier}-{chain}.jpg"):
                dst = variants_dir / src.name
                if dst.exists():
                    continue
                try:
                    os.link(src, dst)
                except OSError:
                    shutil.copy2(src, dst)

        # Link collage too
        collage = z_dir / f"{stack_dir.name}-collage.jpg"
        if collage.exists():
            dst = variants_dir / collage.name
            if not dst.exists():
                try:
                    os.link(collage, dst)
                except OSError:
                    shutil.copy2(collage, dst)
