"""Tkinter GUI for ppsp — launched via ``ppsp --gui`` or the ``ppsp-gui`` entry point.

Three-tab interface:
  Tab 1 "Discover"  — select stacks and chains, generate discovery variants
  Tab 2 "Review"    — per-stack step-by-step pruning (enfuse → TMO → grading)
  Tab 3 "Export"    — export final variants to full-res out-BBBB/ folder

Requires tkinter (stdlib).  Pillow is optional for native JPEG thumbnails;
falls back to ImageMagick ``convert`` if not installed.
"""

from __future__ import annotations

import logging
import os
import queue
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Thumbnail loading
# ---------------------------------------------------------------------------

try:
    from PIL import Image, ImageTk as _ImageTk
    _PILLOW = True
except ImportError:
    _PILLOW = False

_THUMB_SIZE = (192, 128)
_TILE_BG_DEFAULT = "#f0f0f0"
_TILE_BG_SELECTED = "#b8d8f8"
_TILE_BG_DISCARDED = "#e0e0e0"


def _load_thumb(path: Path, size: Tuple[int, int] = _THUMB_SIZE):
    """Return a tk.PhotoImage for the given JPEG, or None on failure."""
    import tkinter as tk
    if _PILLOW:
        try:
            img = Image.open(path).convert("RGB")
            img.thumbnail(size, Image.LANCZOS)
            return _ImageTk.PhotoImage(img)
        except Exception:
            return None
    # ImageMagick fallback
    try:
        import subprocess
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        subprocess.run(
            ["convert", str(path), "-resize", f"{size[0]}x{size[1]}", tmp.name],
            capture_output=True, timeout=15, check=False,
        )
        if os.path.exists(tmp.name) and os.path.getsize(tmp.name) > 0:
            img = tk.PhotoImage(file=tmp.name)
            os.unlink(tmp.name)
            return img
        os.unlink(tmp.name)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Tile widget
# ---------------------------------------------------------------------------

def _make_tile(parent, chain_id: str, img, wins: int, bg: str, on_click):
    """Create a clickable image+label tile frame."""
    import tkinter as tk

    frame = tk.Frame(parent, bg=bg, bd=1, relief="raised", width=_THUMB_SIZE[0] + 8, height=_THUMB_SIZE[1] + 36)
    frame.pack_propagate(False)

    if img:
        lbl_img = tk.Label(frame, image=img, bg=bg)
        lbl_img.image = img  # keep reference
        lbl_img.pack(pady=(4, 0))
        lbl_img.bind("<Button-1>", lambda _e: on_click(chain_id))

    badge = f"  ×{wins}" if wins > 0 else ""
    lbl_txt = tk.Label(frame, text=f"{chain_id}{badge}", bg=bg, font=("sans-serif", 9), wraplength=_THUMB_SIZE[0] + 4)
    lbl_txt.pack(pady=(2, 4))
    lbl_txt.bind("<Button-1>", lambda _e: on_click(chain_id))

    frame.bind("<Button-1>", lambda _e: on_click(chain_id))
    return frame


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class App:
    """ppsp tkinter application."""

    def __init__(self, source: Path) -> None:
        import tkinter as tk
        from tkinter import ttk

        from .session import load_session
        from .variants import ENFUSE_VARIANTS, TMO_VARIANTS, GRADING_PRESETS, CT_PRESETS

        self.source = source
        self.session = load_session(source)

        self.root = tk.Tk()
        self.root.title(f"ppsp — {source.name}")
        self.root.minsize(900, 600)

        self._queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._progress_text = tk.StringVar(value="")

        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)

        self._discover_frame = ttk.Frame(nb)
        self._review_frame = ttk.Frame(nb)
        self._export_frame = ttk.Frame(nb)

        nb.add(self._discover_frame, text=" Discover ")
        nb.add(self._review_frame, text=" Review ")
        nb.add(self._export_frame, text=" Export ")

        self._nb = nb
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Shared controls state
        self._quality_var = tk.IntVar(value=80)
        self._size_var = tk.StringVar(value="z25")
        self._resolution_var = tk.StringVar(value="")
        self._viewer_var = tk.StringVar(value="xdg-open")

        # Review state: {stack_name: {step: selected_set}}
        self._review_sel: Dict[str, Dict[str, Set[str]]] = {}
        self._review_step = tk.StringVar(value="enfuse")
        self._review_stack_var = tk.StringVar(value="")
        self._tile_frames: List = []

        self._build_discover_tab(ENFUSE_VARIANTS, TMO_VARIANTS, GRADING_PRESETS, CT_PRESETS)
        self._build_review_tab()
        self._build_export_tab()

        # Status bar
        status = tk.Label(self.root, textvariable=self._progress_text, anchor="w",
                          relief="sunken", font=("mono", 9))
        status.pack(side="bottom", fill="x", padx=6, pady=(0, 4))

        self.root.after(200, self._poll_queue)

    # ------------------------------------------------------------------
    # Tab 1 — Discover
    # ------------------------------------------------------------------

    def _build_discover_tab(self, enfuse_ids, tmo_ids, grading_ids, ct_ids) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._discover_frame

        # Left pane: stacks list
        left = ttk.LabelFrame(frame, text="Stacks")
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        canvas = tk.Canvas(left)
        sb = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._stacks_inner = tk.Frame(canvas)
        self._stacks_inner_id = canvas.create_window((0, 0), window=self._stacks_inner, anchor="nw")
        self._stacks_inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(self._stacks_inner_id, width=e.width))

        self._stack_vars: Dict[str, tk.BooleanVar] = {}
        self._stacks_canvas = canvas

        btn_sel_all = ttk.Button(left, text="Select all", command=self._select_all_stacks)
        btn_sel_all.pack(side="bottom", fill="x", padx=4, pady=2)
        btn_desel_all = ttk.Button(left, text="Deselect all", command=self._deselect_all_stacks)
        btn_desel_all.pack(side="bottom", fill="x", padx=4, pady=2)

        # Right pane: chain configurator
        right = ttk.LabelFrame(frame, text="Chain configurator")
        right.pack(side="right", fill="both", padx=6, pady=6, ipadx=4, ipady=4)

        self._enfuse_vars: Dict[str, tk.BooleanVar] = {}
        self._tmo_vars: Dict[str, tk.BooleanVar] = {}
        self._grading_vars: Dict[str, tk.BooleanVar] = {}
        self._ct_vars: Dict[str, tk.BooleanVar] = {}

        def _section(label, ids_dict, var_dict, defaults):
            lf = ttk.LabelFrame(right, text=label)
            lf.pack(fill="x", padx=4, pady=4)
            for kid in ids_dict:
                var = tk.BooleanVar(value=(kid in defaults))
                var_dict[kid] = var
                wins = self.session.chain_stats.get(kid, None)
                badge = f" (×{wins.wins})" if wins and wins.wins else ""
                ttk.Checkbutton(lf, text=f"{kid}{badge}", variable=var).pack(anchor="w")

        # Default selections based on "some" preset
        _section("Enfuse", enfuse_ids, self._enfuse_vars, {"sel4"})
        _section("TMO", tmo_ids, self._tmo_vars, {"m08n", "fatn"})
        _section("Grading", grading_ids, self._grading_vars, {"neut", "dvi1"})
        _section("Color temp", ct_ids, self._ct_vars, set())

        ttk.Separator(right).pack(fill="x", pady=4)

        ctrl = ttk.Frame(right)
        ctrl.pack(fill="x", padx=4)

        ttk.Label(ctrl, text="Size:").grid(row=0, column=0, sticky="w")
        for i, (key, label) in enumerate([("z2","micro"), ("z6","quarter"), ("z25","half"), ("z100","full")]):
            ttk.Radiobutton(ctrl, text=f"{key}/{label}", variable=self._size_var, value=key).grid(
                row=0, column=i+1, sticky="w")

        ttk.Label(ctrl, text="Quality:").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(ctrl, from_=50, to=100, textvariable=self._quality_var, width=5).grid(
            row=1, column=1, sticky="w")

        ttk.Label(ctrl, text="Viewer:").grid(row=2, column=0, sticky="w")
        ttk.Entry(ctrl, textvariable=self._viewer_var, width=18).grid(
            row=2, column=1, columnspan=3, sticky="ew")

        ttk.Separator(right).pack(fill="x", pady=4)

        # Preset buttons
        preset_frame = ttk.LabelFrame(right, text="Quick presets")
        preset_frame.pack(fill="x", padx=4, pady=4)
        for preset in ("some", "many", "lots", "all"):
            ttk.Button(preset_frame, text=preset,
                       command=lambda p=preset: self._apply_preset(p)).pack(side="left", padx=2)

        # Generate button
        self._gen_btn = ttk.Button(right, text="▶  Generate", command=self._generate)
        self._gen_btn.pack(fill="x", padx=4, pady=8)

        self._progress_bar = ttk.Progressbar(right, mode="indeterminate")
        self._progress_bar.pack(fill="x", padx=4, pady=2)

        self._load_stacks()

    def _load_stacks(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        # Clear existing
        for w in self._stacks_inner.winfo_children():
            w.destroy()
        self._stack_vars.clear()

        stack_dirs = sorted(
            d for d in self.source.iterdir()
            if d.is_dir() and d.name.endswith("-stack")
        )
        cull_dir = self.source / "cull"

        for stack_dir in stack_dirs:
            sname = stack_dir.name
            var = tk.BooleanVar(value=True)
            self._stack_vars[sname] = var

            row = tk.Frame(self._stacks_inner)
            row.pack(fill="x", pady=1)

            cb = ttk.Checkbutton(row, variable=var)
            cb.pack(side="left")

            # Cull thumbnail
            thumb_path: Optional[Path] = None
            if cull_dir.exists():
                matches = list(cull_dir.glob(f"{sname}_count*.jpg"))
                if matches:
                    thumb_path = matches[0]

            if thumb_path:
                img = _load_thumb(thumb_path, (80, 55))
                if img:
                    lbl = tk.Label(row, image=img)
                    lbl.image = img
                    lbl.pack(side="left", padx=2)

            # Stack name (short: just NNNN)
            parts = sname.split("-")
            short = parts[2] if len(parts) >= 3 else sname
            # Win summary for this stack
            stack_rounds = [r for r in self.session.rounds if r.stack == sname]
            wins_label = f"  [{', '.join(stack_rounds[-1].selected[:2])}]" if stack_rounds else ""

            tk.Label(row, text=f"{short}{wins_label}", font=("mono", 9), anchor="w").pack(
                side="left", fill="x", expand=True)

    def _select_all_stacks(self) -> None:
        for v in self._stack_vars.values():
            v.set(True)

    def _deselect_all_stacks(self) -> None:
        for v in self._stack_vars.values():
            v.set(False)

    def _apply_preset(self, preset: str) -> None:
        from .variants import VARIANT_LEVELS
        e, t, g, ct = VARIANT_LEVELS[preset]
        for kid, var in self._enfuse_vars.items():
            var.set(kid in e)
        for kid, var in self._tmo_vars.items():
            var.set(kid in t)
        for kid, var in self._grading_vars.items():
            var.set(kid in g)
        for kid, var in self._ct_vars.items():
            var.set(kid in ct)

    def _build_variants_arg(self) -> str:
        enfuse = [k for k, v in self._enfuse_vars.items() if v.get()]
        tmo = [k for k, v in self._tmo_vars.items() if v.get()]
        grading = [k for k, v in self._grading_vars.items() if v.get()]
        ct = [k for k, v in self._ct_vars.items() if v.get()]
        return ",".join(enfuse + tmo + grading + ct)

    def _generate(self) -> None:
        from tkinter import messagebox
        stacks = [s for s, v in self._stack_vars.items() if v.get()]
        if not stacks:
            messagebox.showwarning("No stacks", "Select at least one stack.")
            return
        variants_arg = self._build_variants_arg()
        if not variants_arg:
            messagebox.showwarning("No variants", "Select at least one variant option.")
            return

        z_tier = self._size_var.get()
        quality = self._quality_var.get()

        self._gen_btn.state(["disabled"])
        self._progress_bar.start(10)
        self._set_status(f"Generating {len(stacks)} stacks…")

        def _run():
            from .commands import cmd_discover
            try:
                cmd_discover(
                    self.source,
                    variants_arg=variants_arg,
                    z_tier=z_tier,
                    quality=quality,
                    redo=False,
                    stacks_specs=stacks,
                )
                self._queue.put(("generate_done", len(stacks)))
            except Exception as exc:
                self._queue.put(("generate_error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Tab 2 — Review
    # ------------------------------------------------------------------

    def _build_review_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._review_frame

        # Top controls
        top = ttk.Frame(frame)
        top.pack(fill="x", padx=6, pady=4)

        ttk.Label(top, text="Stack:").pack(side="left")
        self._stack_combo = ttk.Combobox(top, textvariable=self._review_stack_var,
                                          state="readonly", width=40)
        self._stack_combo.pack(side="left", padx=4)
        self._stack_combo.bind("<<ComboboxSelected>>", lambda _: self._refresh_review())

        step_frame = ttk.LabelFrame(top, text="Step")
        step_frame.pack(side="left", padx=8)
        for step in ("enfuse", "tmo", "grading"):
            ttk.Radiobutton(step_frame, text=step.capitalize(), variable=self._review_step,
                            value=step, command=self._refresh_review_tiles).pack(side="left", padx=2)

        self._review_btn_next = ttk.Button(top, text="Next step ▶", command=self._review_next_step)
        self._review_btn_next.pack(side="left", padx=4)

        ttk.Button(top, text="Save to session", command=self._save_review_to_session).pack(side="left", padx=4)

        # Tile area
        canvas = tk.Canvas(frame)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=6, pady=4)

        self._review_canvas = canvas
        self._review_tiles_frame = tk.Frame(canvas)
        self._review_tiles_id = canvas.create_window((0, 0), window=self._review_tiles_frame, anchor="nw")
        self._review_tiles_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._review_tiles_id, width=e.width))

        # Bottom action bar
        bot = ttk.Frame(frame)
        bot.pack(fill="x", padx=6, pady=4)
        ttk.Button(bot, text="Select all", command=lambda: self._set_all_tiles(True)).pack(side="left", padx=2)
        ttk.Button(bot, text="Deselect all", command=lambda: self._set_all_tiles(False)).pack(side="left", padx=2)

        self._review_info = tk.StringVar(value="")
        ttk.Label(bot, textvariable=self._review_info).pack(side="right")

    def _on_tab_changed(self, _event=None) -> None:
        tab = self._nb.tab(self._nb.select(), "text").strip()
        if tab == "Review":
            self._refresh_review_stack_list()

    def _refresh_review_stack_list(self) -> None:
        stacks = sorted(
            d.name for d in self.source.iterdir()
            if d.is_dir() and d.name.endswith("-stack")
        )
        self._stack_combo["values"] = stacks
        if stacks and not self._review_stack_var.get():
            self._review_stack_var.set(stacks[0])
            self._refresh_review()

    def _refresh_review(self) -> None:
        sname = self._review_stack_var.get()
        if not sname:
            return
        if sname not in self._review_sel:
            self._review_sel[sname] = {"enfuse": set(), "tmo": set(), "grading": set()}
        self._review_step.set("enfuse")
        self._refresh_review_tiles()

    def _refresh_review_tiles(self) -> None:
        import tkinter as tk

        sname = self._review_stack_var.get()
        if not sname:
            return
        step = self._review_step.get()

        # Discover what variants exist for this stack
        variants_dir = self.source / "variants"
        z_tier = self._size_var.get()
        stack_dir = self.source / sname
        z_dir = stack_dir / z_tier

        # Collect all variant JPGs for this stack from variants/ or z_dir
        candidates: List[Path] = []
        stack_base = sname[:-len("-stack")]
        for d in (variants_dir, z_dir):
            if d.exists():
                for f in d.glob(f"{stack_base}-*.jpg"):
                    if "collage" not in f.name and f not in candidates:
                        candidates.append(f)

        # Parse chain info from each candidate
        from .variants import parse_variant_chain
        from .models import parse_chain
        from .variants import TMO_VARIANTS

        chain_info: Dict[str, Path] = {}  # chain_str → first matching path
        enfuse_to_chains: Dict[str, List[str]] = {}
        for fpath in sorted(candidates):
            spec = parse_chain(fpath.name, tmo_ids=list(TMO_VARIANTS.keys()))
            if spec is None:
                continue
            # Build chain string without z-tier
            parts = [spec.enfuse_id]
            if spec.tmo_id:
                parts.append(spec.tmo_id)
            parts.append(spec.grading_id)
            if spec.ct_id:
                parts.append(spec.ct_id)
            chain = "-".join(parts)
            if chain not in chain_info:
                chain_info[chain] = fpath
            enfuse_to_chains.setdefault(spec.enfuse_id, [])
            if chain not in enfuse_to_chains[spec.enfuse_id]:
                enfuse_to_chains[spec.enfuse_id].append(chain)

        sel = self._review_sel.setdefault(sname, {"enfuse": set(), "tmo": set(), "grading": set()})

        # Filter tiles based on step
        if step == "enfuse":
            # One tile per unique enfuse ID (use first chain as thumbnail)
            display: Dict[str, Path] = {}
            for chain, fpath in chain_info.items():
                eid = chain.split("-")[0]
                if eid not in display:
                    display[eid] = fpath
            tiles: List[Tuple[str, Path]] = [(eid, p) for eid, p in sorted(display.items())]
            info = "Select enfuse base(s) to keep"

        elif step == "tmo":
            selected_enfuse = sel["enfuse"] or set(e.split("-")[0] for e in chain_info)
            display = {}
            for chain, fpath in chain_info.items():
                parts = chain.split("-")
                eid = parts[0]
                if eid not in selected_enfuse:
                    continue
                # Key = enfuse-tmo (or just enfuse if no tmo)
                from .variants import TMO_VARIANTS as _T
                if len(parts) >= 3 and parts[1] in _T:
                    key = f"{parts[0]}-{parts[1]}"
                else:
                    key = parts[0]
                if key not in display:
                    display[key] = fpath
            tiles = [(k, p) for k, p in sorted(display.items())]
            info = "Select enfuse-TMO combinations to keep"

        else:  # grading
            selected_enfuse = sel["enfuse"] or set(e.split("-")[0] for e in chain_info)
            selected_combos = sel["tmo"]
            display = {}
            for chain, fpath in chain_info.items():
                parts = chain.split("-")
                eid = parts[0]
                if eid not in selected_enfuse:
                    continue
                from .variants import TMO_VARIANTS as _T
                if len(parts) >= 3 and parts[1] in _T:
                    combo = f"{parts[0]}-{parts[1]}"
                else:
                    combo = parts[0]
                if selected_combos and combo not in selected_combos:
                    continue
                if chain not in display:
                    display[chain] = fpath
            tiles = [(k, p) for k, p in sorted(display.items())]
            info = "Select final variant chains to publish"

        # Clear existing tiles
        for w in self._review_tiles_frame.winfo_children():
            w.destroy()
        self._tile_frames.clear()

        self._review_info.set(info)

        # Current selections for this step
        step_sel = sel.get(step, set())

        row_frame = None
        COLS = 4

        def _on_tile_click(chain_id: str) -> None:
            step_s = self._review_step.get()
            sn = self._review_stack_var.get()
            cur = self._review_sel.setdefault(sn, {"enfuse": set(), "tmo": set(), "grading": set()})
            if chain_id in cur[step_s]:
                cur[step_s].discard(chain_id)
            else:
                cur[step_s].add(chain_id)
            self._refresh_review_tiles()

        for idx, (chain_id, fpath) in enumerate(tiles):
            if idx % COLS == 0:
                row_frame = tk.Frame(self._review_tiles_frame)
                row_frame.pack(fill="x", pady=2)

            wins = 0
            stats = self.session.chain_stats.get(chain_id)
            if stats:
                wins = stats.wins

            selected = chain_id in step_sel
            bg = _TILE_BG_SELECTED if selected else _TILE_BG_DEFAULT

            # Load thumbnail in main thread (small files, acceptable latency)
            img = _load_thumb(fpath)

            tile = _make_tile(row_frame, chain_id, img, wins, bg, _on_tile_click)
            tile.pack(side="left", padx=4, pady=2)
            self._tile_frames.append((chain_id, tile))

        if not tiles:
            tk.Label(self._review_tiles_frame,
                     text="No variants found. Run Discover first.",
                     font=("sans-serif", 11)).pack(pady=20)

    def _review_next_step(self) -> None:
        steps = ["enfuse", "tmo", "grading"]
        cur = self._review_step.get()
        idx = steps.index(cur)
        if idx < len(steps) - 1:
            self._review_step.set(steps[idx + 1])
            self._refresh_review_tiles()

    def _set_all_tiles(self, selected: bool) -> None:
        sname = self._review_stack_var.get()
        step = self._review_step.get()
        if not sname or not step:
            return
        sel = self._review_sel.setdefault(sname, {"enfuse": set(), "tmo": set(), "grading": set()})
        if selected:
            for cid, _ in self._tile_frames:
                sel[step].add(cid)
        else:
            sel[step].clear()
        self._refresh_review_tiles()

    def _save_review_to_session(self) -> None:
        from tkinter import messagebox
        sname = self._review_stack_var.get()
        if not sname:
            return
        sel = self._review_sel.get(sname, {})
        selected_chains = list(sel.get("grading", set()))
        if not selected_chains:
            messagebox.showinfo("Nothing selected", "Select variants in the Grading step first.")
            return

        # Determine generated chains from session or z_dir scan
        from .interactive import _scan_z_dir
        z_tier = self._size_var.get()
        stack_dir = self.source / sname
        generated = _scan_z_dir(stack_dir, z_tier)

        self.session.record_round(sname, generated, selected_chains)
        from .session import save_session
        save_session(self.session, self.source)
        self._set_status(f"Session saved — {sname}: {', '.join(selected_chains)}")
        messagebox.showinfo("Saved", f"Selection saved for {sname}.\n\n{', '.join(selected_chains)}")

    # ------------------------------------------------------------------
    # Tab 3 — Export
    # ------------------------------------------------------------------

    def _build_export_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._export_frame

        opts = ttk.LabelFrame(frame, text="Output options")
        opts.pack(fill="x", padx=12, pady=8)

        ttk.Label(opts, text="Resolution (long side px, blank = full):").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(opts, textvariable=self._resolution_var, width=8).grid(row=0, column=1, sticky="w")

        ttk.Label(opts, text="JPEG quality:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        q_spin = ttk.Spinbox(opts, from_=50, to=100, textvariable=self._quality_var, width=5)
        q_spin.grid(row=1, column=1, sticky="w")

        src_frame = ttk.LabelFrame(frame, text="Variant source")
        src_frame.pack(fill="x", padx=12, pady=4)

        self._export_src_var = tk.StringVar(value="variants/")
        ttk.Radiobutton(src_frame, text="variants/ folder (surviving files after discovery review)",
                        variable=self._export_src_var, value="variants/").pack(anchor="w", padx=6)
        ttk.Radiobutton(src_frame, text="ppsp_generate.csv (marked rows)",
                        variable=self._export_src_var, value="ppsp_generate.csv").pack(anchor="w", padx=6)
        ttk.Radiobutton(src_frame, text="Session winners (active chains from Review tab)",
                        variable=self._export_src_var, value="session").pack(anchor="w", padx=6)

        out_frame = ttk.LabelFrame(frame, text="Output")
        out_frame.pack(fill="x", padx=12, pady=4)
        ttk.Label(out_frame, text="Finals go to out-{BBBB}/ (and out-{PX}/ if resolution set)").pack(anchor="w", padx=6, pady=4)

        self._export_btn = ttk.Button(frame, text="▶  Export", command=self._export)
        self._export_btn.pack(padx=12, pady=10)

        self._export_progress = ttk.Progressbar(frame, mode="indeterminate")
        self._export_progress.pack(fill="x", padx=12, pady=2)

    def _export(self) -> None:
        from tkinter import messagebox

        src = self._export_src_var.get()
        z_tier = "z100"
        quality = self._quality_var.get()
        resolution_str = self._resolution_var.get().strip()
        resolution = int(resolution_str) if resolution_str.isdigit() else None

        if src == "session":
            active = self.session.active_chains()
            if not active:
                messagebox.showwarning("No session data", "No active chains in session. Run Review first.")
                return
            variants_arg = ",".join(active)
        else:
            p = self.source / src
            if not p.exists():
                messagebox.showwarning("Not found", f"{p} does not exist.")
                return
            variants_arg = str(p)

        self._export_btn.state(["disabled"])
        self._export_progress.start(10)
        self._set_status("Exporting…")

        def _run():
            from .commands import cmd_generate
            try:
                cmd_generate(
                    self.source,
                    variants_arg=variants_arg,
                    z_tier=z_tier,
                    quality=quality,
                    resolution=resolution,
                    redo=False,
                )
                self._queue.put(("export_done", None))
            except Exception as exc:
                self._queue.put(("export_error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Background task plumbing
    # ------------------------------------------------------------------

    def _poll_queue(self) -> None:
        try:
            while True:
                msg, data = self._queue.get_nowait()
                if msg == "generate_done":
                    self._progress_bar.stop()
                    self._gen_btn.state(["!disabled"])
                    self._set_status(f"Discovery complete for {data} stacks.")
                    self._load_stacks()
                elif msg == "generate_error":
                    self._progress_bar.stop()
                    self._gen_btn.state(["!disabled"])
                    self._set_status(f"Error: {data}")
                elif msg == "export_done":
                    self._export_progress.stop()
                    self._export_btn.state(["!disabled"])
                    self._set_status("Export complete.")
                elif msg == "export_error":
                    self._export_progress.stop()
                    self._export_btn.state(["!disabled"])
                    self._set_status(f"Export error: {data}")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _set_status(self, msg: str) -> None:
        self._progress_text.set(msg)

    def run(self) -> None:
        self.root.mainloop()


def launch(source: Optional[Path] = None) -> None:
    """Entry point for ppsp-gui."""
    import sys
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("tkinter is not available. Install it via your system package manager.", file=sys.stderr)
        sys.exit(1)

    if source is None:
        source = Path(".").resolve()

    app = App(source)
    app.run()
