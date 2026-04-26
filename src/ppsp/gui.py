"""Tkinter GUI for ppsp — launched via ``ppsp --gui`` or the ``ppsp-gui`` entry point.

Three-tab interface:
  Tab 1 "Discover"  — select stacks and chains, generate discovery variants
  Tab 2 "Review"    — per-stack step-by-step pruning (enfuse → TMO → grading)
  Tab 3 "Export"    — export final variants to full-res out-BBBB/ folder

A culling grid modal appears on startup when cull/ previews are present so the
user can mark unwanted stacks before entering the main workflow.

Requires tkinter (stdlib).  Pillow is optional for native JPEG thumbnails;
falls back to ImageMagick ``convert`` if not installed.
"""

from __future__ import annotations

import copy
import logging
import os
import queue
import shutil
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from .naming import find_stack_dirs, is_stack_dir, stack_dir_to_filename_base

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
_TILE_BG_DISCARDED = "#d8d8d8"
_ROW_BG_FOCUSED = "#ddeeff"


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

def _make_tile(parent, chain_id: str, img, wins: int, bg: str, on_click, on_double_click=None):
    """Create a clickable image+label tile frame."""
    import tkinter as tk

    frame = tk.Frame(parent, bg=bg, bd=1, relief="raised",
                     width=_THUMB_SIZE[0] + 8, height=_THUMB_SIZE[1] + 36)
    frame.pack_propagate(False)

    if img:
        lbl_img = tk.Label(frame, image=img, bg=bg)
        lbl_img.image = img
        lbl_img.pack(pady=(4, 0))
        lbl_img.bind("<Button-1>", lambda _e: on_click(chain_id))
        if on_double_click:
            lbl_img.bind("<Double-Button-1>", lambda _e: on_double_click(chain_id))

    badge = f"  ×{wins}" if wins > 0 else ""
    lbl_txt = tk.Label(frame, text=f"{chain_id}{badge}", bg=bg,
                       font=("sans-serif", 9), wraplength=_THUMB_SIZE[0] + 4)
    lbl_txt.pack(pady=(2, 4))
    lbl_txt.bind("<Button-1>", lambda _e: on_click(chain_id))
    if on_double_click:
        lbl_txt.bind("<Double-Button-1>", lambda _e: on_double_click(chain_id))

    frame.bind("<Button-1>", lambda _e: on_click(chain_id))
    if on_double_click:
        frame.bind("<Double-Button-1>", lambda _e: on_double_click(chain_id))
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

        # Review state
        self._review_sel: Dict[str, Dict[str, Set[str]]] = {}
        self._review_order: List[str] = []
        self._review_step = tk.StringVar(value="enfuse")
        self._review_stack_var = tk.StringVar(value="")
        self._tile_frames: List[Tuple[str, object]] = []  # (chain_id, frame)
        self._tile_data: List[Tuple[str, Path]] = []      # (chain_id, path) for fullscreen
        self._focused_chain: Optional[str] = None
        self._focused_tile_frame = None

        # Stacks list keyboard state
        self._stack_rows: List[Tuple[str, object]] = []   # (sname, frame)
        self._focused_stack_idx: int = 0

        # Log panel state
        self._log_collapsed = False
        self._log_file_offset = 0
        self._log_text = None
        self._log_frame = None
        self._log_toggle_btn = None
        self._log_tail_started = False

        self._build_discover_tab(ENFUSE_VARIANTS, TMO_VARIANTS, GRADING_PRESETS, CT_PRESETS)
        self._build_review_tab()
        self._build_export_tab()

        # Status bar
        status = tk.Label(self.root, textvariable=self._progress_text, anchor="w",
                          relief="sunken", font=("mono", 9))
        status.pack(side="bottom", fill="x", padx=6, pady=(0, 4))

        self._bind_shortcuts()
        self.root.after(200, self._poll_queue)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _component_wins(self, component_id: str) -> int:
        """Sum wins across all chains that contain this component ID as a dash-separated token."""
        return sum(
            s.wins
            for chain, s in self.session.chain_stats.items()
            if component_id in chain.split("-")
        )

    def _stack_status_icon(self, sname: str) -> str:
        return "✓" if any(r.stack == sname for r in self.session.rounds) else "—"

    def _active_tab(self) -> str:
        return self._nb.tab(self._nb.select(), "text").strip()

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
        self._stacks_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._stacks_inner_id, width=e.width))

        self._stack_vars: Dict[str, "tk.BooleanVar"] = {}
        self._stacks_canvas = canvas

        btn_sel_all = ttk.Button(left, text="Select all", command=self._select_all_stacks)
        btn_sel_all.pack(side="bottom", fill="x", padx=4, pady=2)
        btn_desel_all = ttk.Button(left, text="Deselect all", command=self._deselect_all_stacks)
        btn_desel_all.pack(side="bottom", fill="x", padx=4, pady=2)

        # Right pane: chain configurator
        right = ttk.LabelFrame(frame, text="Chain configurator")
        right.pack(side="right", fill="both", padx=6, pady=6, ipadx=4, ipady=4)

        self._enfuse_vars: Dict[str, "tk.BooleanVar"] = {}
        self._tmo_vars: Dict[str, "tk.BooleanVar"] = {}
        self._grading_vars: Dict[str, "tk.BooleanVar"] = {}
        self._ct_vars: Dict[str, "tk.BooleanVar"] = {}

        def _section(label, ids_dict, var_dict, defaults):
            lf = ttk.LabelFrame(right, text=label)
            lf.pack(fill="x", padx=4, pady=4)
            for kid in ids_dict:
                var = tk.BooleanVar(value=(kid in defaults))
                var_dict[kid] = var
                wins = self._component_wins(kid)
                badge = f" (×{wins})" if wins else ""
                ttk.Checkbutton(lf, text=f"{kid}{badge}", variable=var).pack(anchor="w")

        _section("Enfuse", enfuse_ids, self._enfuse_vars, {"sel4"})
        _section("TMO", tmo_ids, self._tmo_vars, {"m08n", "fatn"})
        _section("Grading", grading_ids, self._grading_vars, {"neut", "dvi1"})
        _section("Color temp", ct_ids, self._ct_vars, set())

        ttk.Separator(right).pack(fill="x", pady=4)

        ctrl = ttk.Frame(right)
        ctrl.pack(fill="x", padx=4)

        ttk.Label(ctrl, text="Size:").grid(row=0, column=0, sticky="w")
        for i, (key, label) in enumerate([("z2", "micro"), ("z6", "quarter"),
                                           ("z25", "half"), ("z100", "full")]):
            ttk.Radiobutton(ctrl, text=f"{key}/{label}", variable=self._size_var,
                            value=key).grid(row=0, column=i + 1, sticky="w")

        ttk.Label(ctrl, text="Quality:").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(ctrl, from_=50, to=100, textvariable=self._quality_var,
                    width=5).grid(row=1, column=1, sticky="w")

        ttk.Label(ctrl, text="Viewer:").grid(row=2, column=0, sticky="w")
        ttk.Entry(ctrl, textvariable=self._viewer_var, width=18).grid(
            row=2, column=1, columnspan=3, sticky="ew")

        ttk.Separator(right).pack(fill="x", pady=4)

        preset_frame = ttk.LabelFrame(right, text="Quick presets")
        preset_frame.pack(fill="x", padx=4, pady=4)
        for preset in ("some", "many", "lots", "all"):
            ttk.Button(preset_frame, text=preset,
                       command=lambda p=preset: self._apply_preset(p)).pack(side="left", padx=2)

        self._gen_btn = ttk.Button(right, text="▶  Generate", command=self._generate)
        self._gen_btn.pack(fill="x", padx=4, pady=8)

        self._progress_bar = ttk.Progressbar(right, mode="indeterminate")
        self._progress_bar.pack(fill="x", padx=4, pady=2)

        self._load_stacks()

    def _load_stacks(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        for w in self._stacks_inner.winfo_children():
            w.destroy()
        self._stack_vars.clear()
        self._stack_rows.clear()
        self._focused_stack_idx = 0

        stack_dirs = find_stack_dirs(self.source)

        for idx, stack_dir in enumerate(stack_dirs):
            sname = stack_dir.name
            var = tk.BooleanVar(value=True)
            self._stack_vars[sname] = var

            row = tk.Frame(self._stacks_inner, pady=1)
            row.pack(fill="x")
            self._stack_rows.append((sname, row))

            ttk.Checkbutton(row, variable=var).pack(side="left")

            parts = sname.split("-")
            short_id = parts[2] if len(parts) >= 3 else sname
            # Include shorthand if present (named stack)
            if len(parts) >= 4 and not parts[3].startswith("z"):
                short_id = f"{parts[2]}-{parts[3]}"

            icon = self._stack_status_icon(sname)
            tk.Label(row, text=f"{short_id}  {icon}", font=("mono", 9),
                     anchor="w").pack(side="left", fill="x", expand=True)

            if idx == self._focused_stack_idx:
                row.configure(bg=_ROW_BG_FOCUSED)

    def _select_all_stacks(self) -> None:
        for v in self._stack_vars.values():
            v.set(True)

    def _deselect_all_stacks(self) -> None:
        for v in self._stack_vars.values():
            v.set(False)

    def _navigate_stacks(self, delta: int) -> None:
        if not self._stack_rows:
            return
        # Un-highlight current
        _, old_frame = self._stack_rows[self._focused_stack_idx]
        old_frame.configure(bg="SystemButtonFace")  # type: ignore[union-attr]
        self._focused_stack_idx = (self._focused_stack_idx + delta) % len(self._stack_rows)
        _, new_frame = self._stack_rows[self._focused_stack_idx]
        new_frame.configure(bg=_ROW_BG_FOCUSED)  # type: ignore[union-attr]
        self._stacks_canvas.update_idletasks()

    def _toggle_focused_stack(self) -> None:
        if not self._stack_rows:
            return
        sname, _ = self._stack_rows[self._focused_stack_idx]
        var = self._stack_vars.get(sname)
        if var:
            var.set(not var.get())

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
                cmd_discover(self.source, variants_arg=variants_arg, z_tier=z_tier,
                             quality=quality, redo=False, stacks_specs=stacks)
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

        self._review_btn_next = ttk.Button(top, text="Next step ▶",
                                            command=self._review_next_step)
        self._review_btn_next.pack(side="left", padx=4)
        ttk.Button(top, text="Save to session",
                   command=self._save_review_to_session).pack(side="left", padx=4)

        # Tile area
        canvas = tk.Canvas(frame)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=6, pady=4)

        self._review_canvas = canvas
        self._review_tiles_frame = tk.Frame(canvas)
        self._review_tiles_id = canvas.create_window(
            (0, 0), window=self._review_tiles_frame, anchor="nw")
        self._review_tiles_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._review_tiles_id, width=e.width))

        bot = ttk.Frame(frame)
        bot.pack(fill="x", padx=6, pady=4)
        ttk.Button(bot, text="Select all",
                   command=lambda: self._set_all_tiles(True)).pack(side="left", padx=2)
        ttk.Button(bot, text="Deselect all",
                   command=lambda: self._set_all_tiles(False)).pack(side="left", padx=2)

        self._review_info = tk.StringVar(value="")
        ttk.Label(bot, textvariable=self._review_info).pack(side="right")

    def _on_tab_changed(self, _event=None) -> None:
        tab = self._active_tab()
        if tab == "Review":
            self._refresh_review_stack_list()
        elif tab == "Export":
            if not self._log_tail_started:
                self._log_tail_started = True
                self._start_log_tail()

    def _refresh_review_stack_list(self) -> None:
        stacks = [d.name for d in find_stack_dirs(self.source)]
        self._stack_combo["values"] = stacks
        if stacks and not self._review_stack_var.get():
            self._review_stack_var.set(stacks[0])
            self._refresh_review()

    def _refresh_review(self) -> None:
        sname = self._review_stack_var.get()
        if not sname:
            return

        if sname not in self._review_sel:
            # Carry forward from the most recently reviewed stack (not this one).
            prev = next(
                (s for s in reversed(self._review_order) if s != sname and s in self._review_sel),
                None,
            )
            if prev and any(self._review_sel[prev].values()):
                self._review_sel[sname] = copy.deepcopy(self._review_sel[prev])
            else:
                self._review_sel[sname] = {"enfuse": set(), "tmo": set(), "grading": set()}

        if not self._review_order or self._review_order[-1] != sname:
            self._review_order.append(sname)

        self._review_step.set("enfuse")
        self._refresh_review_tiles()

    def _refresh_review_tiles(self) -> None:
        import tkinter as tk

        sname = self._review_stack_var.get()
        if not sname:
            return
        step = self._review_step.get()

        variants_dir = self.source / "variants"
        z_tier = self._size_var.get()
        stack_dir = self.source / sname
        z_dir = stack_dir / z_tier

        # filename base handles both -stack and named dirs
        stack_base = stack_dir_to_filename_base(sname)

        candidates: List[Path] = []
        for d in (variants_dir, z_dir):
            if d.exists():
                for f in d.glob(f"{stack_base}-*.jpg"):
                    if "collage" not in f.name and f not in candidates:
                        candidates.append(f)

        from .variants import parse_variant_chain, TMO_VARIANTS
        from .models import parse_chain

        chain_info: Dict[str, Path] = {}
        enfuse_to_chains: Dict[str, List[str]] = {}
        for fpath in sorted(candidates):
            spec = parse_chain(fpath.name, tmo_ids=list(TMO_VARIANTS.keys()))
            if spec is None:
                continue
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

        sel = self._review_sel.setdefault(
            sname, {"enfuse": set(), "tmo": set(), "grading": set()})

        # Separate discarded from active
        discarded_chains = {
            c for c, s in self.session.chain_stats.items() if s.discarded
        }

        if step == "enfuse":
            display: Dict[str, Path] = {}
            for chain, fpath in chain_info.items():
                eid = chain.split("-")[0]
                if eid not in display:
                    display[eid] = fpath
            tiles: List[Tuple[str, Path]] = [(eid, p) for eid, p in sorted(display.items())]
            info = "Select enfuse base(s) to keep  (D=discard, R=reintroduce, F/dbl-click=fullscreen)"

        elif step == "tmo":
            selected_enfuse = sel["enfuse"] or set(c.split("-")[0] for c in chain_info)
            display = {}
            for chain, fpath in chain_info.items():
                parts = chain.split("-")
                eid = parts[0]
                if eid not in selected_enfuse:
                    continue
                _T = TMO_VARIANTS
                if len(parts) >= 3 and parts[1] in _T:
                    key = f"{parts[0]}-{parts[1]}"
                else:
                    key = parts[0]
                if key not in display:
                    display[key] = fpath
            tiles = [(k, p) for k, p in sorted(display.items())]
            info = "Select enfuse-TMO combinations to keep"

        else:  # grading
            selected_enfuse = sel["enfuse"] or set(c.split("-")[0] for c in chain_info)
            selected_combos = sel["tmo"]
            display = {}
            for chain, fpath in chain_info.items():
                parts = chain.split("-")
                eid = parts[0]
                if eid not in selected_enfuse:
                    continue
                _T = TMO_VARIANTS
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

        for w in self._review_tiles_frame.winfo_children():
            w.destroy()
        self._tile_frames.clear()
        self._tile_data = list(tiles)

        self._review_info.set(info)
        step_sel = sel.get(step, set())

        row_frame = None
        COLS = 4

        for idx, (chain_id, fpath) in enumerate(tiles):
            if idx % COLS == 0:
                row_frame = tk.Frame(self._review_tiles_frame)
                row_frame.pack(fill="x", pady=2)

            wins = self._component_wins(chain_id)
            selected = chain_id in step_sel
            is_discarded = chain_id in discarded_chains

            if is_discarded:
                bg = _TILE_BG_DISCARDED
            elif selected:
                bg = _TILE_BG_SELECTED
            else:
                bg = _TILE_BG_DEFAULT

            img = _load_thumb(fpath)
            tile = _make_tile(
                row_frame, chain_id, img, wins, bg,
                on_click=self._handle_tile_click,
                on_double_click=self._open_fullscreen,
            )
            tile.pack(side="left", padx=4, pady=2)
            self._tile_frames.append((chain_id, tile))

        if not tiles:
            tk.Label(self._review_tiles_frame,
                     text="No variants found. Run Discover first.",
                     font=("sans-serif", 11)).pack(pady=20)

    def _handle_tile_click(self, chain_id: str) -> None:
        """Toggle selection and update focused chain."""
        self._focused_chain = chain_id
        sname = self._review_stack_var.get()
        step = self._review_step.get()
        cur = self._review_sel.setdefault(sname, {"enfuse": set(), "tmo": set(), "grading": set()})
        if chain_id in cur[step]:
            cur[step].discard(chain_id)
        else:
            cur[step].add(chain_id)
        self._refresh_review_tiles()

    def _open_fullscreen(self, start_chain_id: str) -> None:
        """Open a large-image Toplevel for the tile set, starting at start_chain_id."""
        import tkinter as tk
        if not self._tile_data:
            return

        idx = next(
            (i for i, (cid, _) in enumerate(self._tile_data) if cid == start_chain_id), 0)

        top = tk.Toplevel(self.root)
        top.title("Fullscreen — ppsp Review")
        top.geometry("1200x860")
        top.grab_set()

        info_lbl = tk.Label(top, text="", font=("mono", 10))
        info_lbl.pack(side="top", pady=4)

        img_lbl = tk.Label(top, bg="black")
        img_lbl.pack(fill="both", expand=True)

        _cur = [idx]
        _img_ref = [None]  # prevent GC

        def _show(i: int) -> None:
            _cur[0] = i % len(self._tile_data)
            cid, fpath = self._tile_data[_cur[0]]
            sname = self._review_stack_var.get()
            step = self._review_step.get()
            sel = self._review_sel.get(sname, {}).get(step, set())
            status = " [✓ SELECTED]" if cid in sel else ""
            img = _load_thumb(fpath, (1100, 800))
            _img_ref[0] = img
            img_lbl.configure(image=img)
            info_lbl.configure(
                text=f"{_cur[0] + 1}/{len(self._tile_data)}: {cid}{status}"
                     "    Space=toggle  ←/→=browse  Esc=close"
            )

        def _toggle(_e=None) -> None:
            cid, _ = self._tile_data[_cur[0]]
            self._handle_tile_click(cid)
            _show(_cur[0])

        top.bind("<Escape>", lambda _e: top.destroy())
        top.bind("<Left>", lambda _e: _show(_cur[0] - 1))
        top.bind("<Right>", lambda _e: _show(_cur[0] + 1))
        top.bind("<space>", _toggle)
        top.focus_set()
        _show(idx)

    def _discard_focused(self) -> None:
        if self._focused_chain is None:
            return
        self.session.discard(self._focused_chain)
        from .session import save_session
        save_session(self.session, self.source)
        self._set_status(f"Discarded: {self._focused_chain}")
        self._refresh_review_tiles()

    def _reactivate_focused(self) -> None:
        if self._focused_chain is None:
            return
        self.session.reactivate(self._focused_chain)
        from .session import save_session
        save_session(self.session, self.source)
        self._set_status(f"Reintroduced: {self._focused_chain}")
        self._refresh_review_tiles()

    def _review_next_step(self) -> None:
        sname = self._review_stack_var.get()
        step = self._review_step.get()
        sel = self._review_sel.get(sname, {})
        if not sel.get(step):
            self._review_info.set("⚠  Select at least one variant before advancing to the next step.")
            return
        steps = ["enfuse", "tmo", "grading"]
        idx = steps.index(step)
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
            messagebox.showinfo("Nothing selected",
                                "Select variants in the Grading step first.")
            return

        from .interactive import _scan_z_dir
        z_tier = self._size_var.get()
        stack_dir = self.source / sname
        generated = _scan_z_dir(stack_dir, z_tier)

        self.session.record_round(sname, generated, selected_chains)
        from .session import save_session
        save_session(self.session, self.source)
        self._set_status(f"Session saved — {sname}: {', '.join(selected_chains)}")
        messagebox.showinfo("Saved",
                            f"Selection saved for {sname}.\n\n{', '.join(selected_chains)}")

    def _navigate_review_stack(self, delta: int) -> None:
        """Move the Review combobox by delta steps."""
        stacks = list(self._stack_combo["values"])
        if not stacks:
            return
        cur = self._review_stack_var.get()
        try:
            idx = stacks.index(cur)
        except ValueError:
            idx = 0
        new_idx = (idx + delta) % len(stacks)
        self._review_stack_var.set(stacks[new_idx])
        self._refresh_review()

    # ------------------------------------------------------------------
    # Tab 3 — Export
    # ------------------------------------------------------------------

    def _build_export_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._export_frame

        opts = ttk.LabelFrame(frame, text="Output options")
        opts.pack(fill="x", padx=12, pady=8)

        ttk.Label(opts, text="Resolution (long side px, blank = full):").grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(opts, textvariable=self._resolution_var, width=8).grid(
            row=0, column=1, sticky="w")

        ttk.Label(opts, text="JPEG quality:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Spinbox(opts, from_=50, to=100, textvariable=self._quality_var,
                    width=5).grid(row=1, column=1, sticky="w")

        src_frame = ttk.LabelFrame(frame, text="Variant source")
        src_frame.pack(fill="x", padx=12, pady=4)

        self._export_src_var = tk.StringVar(value="variants/")
        ttk.Radiobutton(src_frame,
                        text="variants/ folder (surviving files after discovery review)",
                        variable=self._export_src_var, value="variants/").pack(anchor="w", padx=6)
        ttk.Radiobutton(src_frame, text="ppsp_generate.csv (marked rows)",
                        variable=self._export_src_var,
                        value="ppsp_generate.csv").pack(anchor="w", padx=6)
        ttk.Radiobutton(src_frame, text="ppsp_stacks.csv (per-stack GenerateSpecs)",
                        variable=self._export_src_var,
                        value="ppsp_stacks.csv").pack(anchor="w", padx=6)
        ttk.Radiobutton(src_frame,
                        text="Session winners (active chains from Review tab)",
                        variable=self._export_src_var, value="session").pack(anchor="w", padx=6)

        out_frame = ttk.LabelFrame(frame, text="Output")
        out_frame.pack(fill="x", padx=12, pady=4)
        ttk.Label(out_frame,
                  text="Finals go to out-{BBBB}/ (and out-{PX}/ if resolution set)").pack(
            anchor="w", padx=6, pady=4)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", padx=12, pady=(8, 0))
        self._export_btn = ttk.Button(btn_row, text="▶  Export", command=self._export)
        self._export_btn.pack(side="left")

        self._export_progress = ttk.Progressbar(frame, mode="indeterminate")
        self._export_progress.pack(fill="x", padx=12, pady=2)

        # Log panel
        log_hdr = ttk.Frame(frame)
        log_hdr.pack(fill="x", padx=12, pady=(6, 0))
        ttk.Label(log_hdr, text="Log  (ppsp.log)").pack(side="left")
        self._log_toggle_btn = ttk.Button(log_hdr, text="▼ Collapse",
                                           command=self._toggle_log_panel, width=12)
        self._log_toggle_btn.pack(side="right")

        self._log_frame = ttk.Frame(frame)
        self._log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self._log_text = tk.Text(self._log_frame, height=12, font=("mono", 8),
                                  state="disabled", wrap="none")
        log_vsb = ttk.Scrollbar(self._log_frame, orient="vertical",
                                  command=self._log_text.yview)
        log_hsb = ttk.Scrollbar(self._log_frame, orient="horizontal",
                                  command=self._log_text.xview)
        self._log_text.configure(yscrollcommand=log_vsb.set, xscrollcommand=log_hsb.set)
        log_vsb.pack(side="right", fill="y")
        log_hsb.pack(side="bottom", fill="x")
        self._log_text.pack(fill="both", expand=True)

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
                messagebox.showwarning("No session data",
                                       "No active chains in session. Run Review first.")
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
                cmd_generate(self.source, variants_arg=variants_arg, z_tier=z_tier,
                             quality=quality, resolution=resolution, redo=False)
                self._queue.put(("export_done", None))
            except Exception as exc:
                self._queue.put(("export_error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    def _toggle_log_panel(self) -> None:
        if self._log_frame is None:
            return
        self._log_collapsed = not self._log_collapsed
        if self._log_collapsed:
            self._log_frame.pack_forget()
            if self._log_toggle_btn:
                self._log_toggle_btn.configure(text="▶ Expand")
        else:
            self._log_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))
            if self._log_toggle_btn:
                self._log_toggle_btn.configure(text="▼ Collapse")

    def _start_log_tail(self) -> None:
        """Start a daemon thread that tails ppsp.log and puts lines on the queue."""
        log_path = self.source / "ppsp.log"

        def _tail():
            offset = 0
            while True:
                try:
                    if log_path.exists():
                        with open(log_path, "r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(offset)
                            while True:
                                line = fh.readline()
                                if line:
                                    offset = fh.tell()
                                    self._queue.put(("log_line", line))
                                else:
                                    break
                except Exception:
                    pass
                time.sleep(0.5)

        threading.Thread(target=_tail, daemon=True).start()

        # Populate with existing content
        if log_path.exists():
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace")
                self._append_log(lines)
                self._log_file_offset = log_path.stat().st_size
            except OSError:
                pass

    def _append_log(self, text: str) -> None:
        if self._log_text is None:
            return
        at_bottom = self._log_text.yview()[1] >= 0.99
        self._log_text.configure(state="normal")
        self._log_text.insert("end", text)
        self._log_text.configure(state="disabled")
        if at_bottom:
            self._log_text.see("end")

    # ------------------------------------------------------------------
    # Pre-tab culling grid
    # ------------------------------------------------------------------

    def _show_culling_grid(self) -> Optional[object]:
        """Show a modal culling grid if cull/ has previews. Returns the Toplevel or None."""
        import tkinter as tk
        from tkinter import ttk

        cull_dir = self.source / "cull"
        previews = sorted(cull_dir.glob("*.jpg")) if cull_dir.exists() else []
        if not previews:
            return None

        top = tk.Toplevel(self.root)
        top.title("Culling — keep or prune stacks")
        top.geometry("1100x700")
        top.grab_set()

        ttk.Label(top, text="Click to toggle prune (dimmed = will be pruned). "
                             "Double-click for fullscreen.",
                  font=("sans-serif", 10)).pack(pady=4)

        # State: stack_name → keep (True) / prune (False)
        cull_states: Dict[str, bool] = {}
        cull_imgs: Dict[str, object] = {}  # keep PhotoImage refs

        canvas = tk.Canvas(top)
        vsb = ttk.Scrollbar(top, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=6, pady=4)

        inner = tk.Frame(canvas)
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(inner_id, width=e.width))

        tile_frames: Dict[str, object] = {}
        COLS = 5
        row_frame = None

        def _refresh_tile(sname: str) -> None:
            f = tile_frames.get(sname)
            if f is None:
                return
            keep = cull_states.get(sname, True)
            bg = "#f0f0f0" if keep else "#b0b0b0"
            f.configure(bg=bg)  # type: ignore[union-attr]
            for child in f.winfo_children():  # type: ignore[union-attr]
                try:
                    child.configure(bg=bg)
                except Exception:
                    pass

        def _toggle(sname: str) -> None:
            cull_states[sname] = not cull_states.get(sname, True)
            _refresh_tile(sname)

        def _open_cull_fullscreen(sname: str) -> None:
            ordered = [p.name.split("_count")[0] for p in previews]
            _idx = [ordered.index(sname) if sname in ordered else 0]
            fs = tk.Toplevel(top)
            fs.title("Fullscreen Cull")
            fs.geometry("1200x860")
            fs.grab_set()
            info = tk.Label(fs, text="", font=("mono", 10))
            info.pack(side="top", pady=4)
            lbl = tk.Label(fs, bg="black")
            lbl.pack(fill="both", expand=True)
            _ref = [None]

            def _fs_show(i: int) -> None:
                _idx[0] = i % len(previews)
                pv = previews[_idx[0]]
                sn = pv.name.split("_count")[0]
                keep = cull_states.get(sn, True)
                img = _load_thumb(pv, (1100, 800))
                _ref[0] = img
                lbl.configure(image=img)
                info.configure(
                    text=f"{_idx[0] + 1}/{len(previews)}: {sn}  "
                         f"{'KEEP' if keep else 'PRUNE'}"
                         "    Space=toggle  ←/→=browse  Esc=close"
                )

            def _fs_toggle(_e=None) -> None:
                sn = previews[_idx[0]].name.split("_count")[0]
                _toggle(sn)
                _fs_show(_idx[0])

            fs.bind("<Escape>", lambda _e: fs.destroy())
            fs.bind("<Left>", lambda _e: _fs_show(_idx[0] - 1))
            fs.bind("<Right>", lambda _e: _fs_show(_idx[0] + 1))
            fs.bind("<space>", _fs_toggle)
            fs.focus_set()
            _fs_show(_idx[0])

        for pidx, pv in enumerate(previews):
            sname = pv.name.split("_count")[0]
            cull_states[sname] = True
            if pidx % COLS == 0:
                row_frame = tk.Frame(inner)
                row_frame.pack(fill="x", pady=2)

            f = tk.Frame(row_frame, bg="#f0f0f0", bd=1, relief="raised",
                         width=200, height=160)
            f.pack_propagate(False)
            f.pack(side="left", padx=3, pady=2)
            tile_frames[sname] = f

            img = _load_thumb(pv, (190, 130))
            cull_imgs[sname] = img
            if img:
                il = tk.Label(f, image=img, bg="#f0f0f0")
                il.image = img
                il.pack(pady=(3, 0))
                il.bind("<Button-1>", lambda _e, s=sname: _toggle(s))
                il.bind("<Double-Button-1>", lambda _e, s=sname: _open_cull_fullscreen(s))

            parts = sname.split("-")
            short = parts[2] if len(parts) >= 3 else sname
            tl = tk.Label(f, text=short, bg="#f0f0f0", font=("mono", 9))
            tl.pack(pady=(1, 3))
            tl.bind("<Button-1>", lambda _e, s=sname: _toggle(s))
            f.bind("<Button-1>", lambda _e, s=sname: _toggle(s))

        # Confirm / Cancel
        bot = ttk.Frame(top)
        bot.pack(fill="x", padx=12, pady=8)
        ttk.Button(bot, text="Cancel", command=top.destroy).pack(side="right", padx=4)

        def _confirm() -> None:
            prune_names = [s for s, keep in cull_states.items() if not keep]
            if prune_names:
                cull_d = self.source / "cull"
                for sname in prune_names:
                    for f in cull_d.glob(f"{sname}_count*.jpg"):
                        try:
                            f.unlink()
                        except OSError:
                            pass
                from .commands import cmd_prune
                cmd_prune(self.source)
            top.destroy()

        ttk.Button(bot, text="✓ Confirm culling", command=_confirm).pack(side="right", padx=4)
        ttk.Label(bot, text="Dimmed stacks will be pruned.").pack(side="left")

        return top

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        r = self.root
        r.bind("<Control-e>", lambda _e: self._export())
        r.bind("<Control-l>", lambda _e: self._toggle_log_panel())
        r.bind("<Left>", self._on_left_key)
        r.bind("<Right>", self._on_right_key)
        r.bind("<Return>", self._on_enter_key)
        r.bind("<Tab>", self._on_tab_key)
        r.bind("d", self._on_d_key)
        r.bind("D", self._on_d_key)
        r.bind("r", self._on_r_key)
        r.bind("R", self._on_r_key)
        r.bind("f", self._on_f_key)
        r.bind("F", self._on_f_key)
        r.bind("<space>", self._on_space_key)

    def _on_left_key(self, _event=None) -> str:
        tab = self._active_tab()
        if tab == "Discover":
            self._navigate_stacks(-1)
        elif tab == "Review":
            self._navigate_review_stack(-1)
        return "break"

    def _on_right_key(self, _event=None) -> str:
        tab = self._active_tab()
        if tab == "Discover":
            self._navigate_stacks(1)
        elif tab == "Review":
            self._navigate_review_stack(1)
        return "break"

    def _on_enter_key(self, _event=None) -> None:
        tab = self._active_tab()
        if tab == "Discover":
            self._toggle_focused_stack()

    def _on_tab_key(self, _event=None) -> Optional[str]:
        if self._active_tab() == "Review":
            self._review_next_step()
            return "break"
        return None

    def _on_d_key(self, _event=None) -> None:
        if self._active_tab() == "Review":
            self._discard_focused()

    def _on_r_key(self, _event=None) -> None:
        if self._active_tab() == "Review":
            self._reactivate_focused()

    def _on_f_key(self, _event=None) -> None:
        if self._active_tab() == "Review" and self._focused_chain:
            self._open_fullscreen(self._focused_chain)

    def _on_space_key(self, _event=None) -> Optional[str]:
        tab = self._active_tab()
        if tab == "Review" and self._focused_chain:
            self._handle_tile_click(self._focused_chain)
            return "break"
        return None

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
                elif msg == "log_line":
                    self._append_log(str(data))
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _set_status(self, msg: str) -> None:
        self._progress_text.set(msg)

    def _show_name_dialog(self) -> Optional[object]:
        """Pre-tab modal for the optional stack naming step. Returns Toplevel or None."""
        if not find_stack_dirs(self._source):
            return None

        top = tk.Toplevel(self.root)
        top.title("Name Stacks (optional)")
        top.geometry("500x190")
        top.grab_set()

        tk.Label(top, text="Name your stacks before discovery?",
                 font=("TkDefaultFont", 11)).pack(pady=10)
        tk.Label(top,
                 text="ppsp_stacks.csv will be written and opened for editing.\n"
                      "Fill in titles (and optionally tags/rating), save, then click Done.",
                 justify="center", foreground="#555").pack()

        btn_frame = tk.Frame(top)
        btn_frame.pack(pady=14)

        done_btn: tk.Button

        def _open_csv() -> None:
            from .naming import build_stacks_csv_rows, load_stacks_csv, save_stacks_csv
            existing = load_stacks_csv(self._source)
            save_stacks_csv(self._source, build_stacks_csv_rows(self._source, existing))
            csv_p = self._source / "ppsp_stacks.csv"
            try:
                import subprocess as _sp
                _sp.Popen(["xdg-open", str(csv_p)])
            except OSError:
                pass
            done_btn.config(state="normal")

        def _done() -> None:
            from .commands import _name_from_csv
            from .naming import build_stacks_csv_rows, load_stacks_csv, save_stacks_csv
            existing = load_stacks_csv(self._source)
            rows = build_stacks_csv_rows(self._source, existing)
            csv_p = self._source / "ppsp_stacks.csv"
            if csv_p.exists():
                _name_from_csv(self._source, csv_p, rows, redo=False)
                save_stacks_csv(self._source, rows)
            top.destroy()

        tk.Button(btn_frame, text="Open CSV", command=_open_csv).pack(side="left", padx=6)
        done_btn = tk.Button(btn_frame, text="Done", command=_done, state="disabled")
        done_btn.pack(side="left", padx=6)
        tk.Button(btn_frame, text="Skip", command=top.destroy).pack(side="left", padx=6)

        return top

    def run(self) -> None:
        cull_top = self._show_culling_grid()
        if cull_top is not None:
            self.root.wait_window(cull_top)
            self._load_stacks()
        name_top = self._show_name_dialog()
        if name_top is not None:
            self.root.wait_window(name_top)
            self._load_stacks()
        self.root.mainloop()


def launch(source: Optional[Path] = None) -> None:
    """Entry point for ppsp-gui."""
    import sys
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("tkinter is not available. Install it via your system package manager.",
              file=sys.stderr)
        sys.exit(1)

    if source is None:
        source = Path(".").resolve()

    app = App(source)
    app.run()
