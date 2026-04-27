"""Tkinter GUI for ppsp — Work in Progress.

Eight-tab interface matching the ppsp workflow:
  Tab 1 "Rename"   — normalize filenames (ppsp -r)
  Tab 2 "Organize" — group into per-stack folders (ppsp -o)
  Tab 3 "Cull"     — review/prune stacks via cull grid
  Tab 4 "Metadata" — name, tag, and rate stacks (ppsp -n)
  Tab 5 "Variants" — configure chains and generate discovery variants (ppsp -D)
  Tab 6 "Select"   — step-by-step variant selection (enfuse → TMO → grading → CT)
  Tab 7 "Generate" — export final variants (ppsp -g)
  Tab 8 "Cleanup"  — remove working folders (ppsp -C)

Log panel always visible at the bottom, resizeable by dragging the sash; Ctrl+L toggles.
Single click moves keyboard focus; double-click or F opens fullscreen; Space selects/unselects.
Arrow keys navigate the tile grid. 'c' in fullscreen compares with previous image.

Requires tkinter (stdlib). Pillow optional for thumbnails; falls back to ImageMagick.
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

_THUMB_SIZE = (384, 256)  # doubled from (192, 128)
_CULL_THUMB_SIZE = (380, 260)  # for the culling grid

_TILE_BG_DEFAULT = "#f0f0f0"
_TILE_BG_SELECTED = "#b8d8f8"
_TILE_BG_FOCUSED = "#fffacd"
_TILE_BG_FOCUSED_SELECTED = "#80c0f0"
_TILE_BG_DISCARDED = "#d8d8d8"
_ROW_BG_FOCUSED = "#ddeeff"

_META_THUMB_SIZE = (96, 64)    # small thumbnail in Metadata tab
_DISCOVER_COLS = 3  # tiles per row in Select tab (3 × 392px ≈ fits 1200px)
_CULL_GRID_COLS = 3  # tiles per row in culling grid


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

def _make_tile(parent, chain_id: str, img, wins: int, bg: str,
               on_click, on_double_click=None, focused: bool = False):
    """Create a clickable image+label tile frame."""
    import tkinter as tk

    bd = 3 if focused else 1
    relief = "solid" if focused else "raised"
    frame = tk.Frame(parent, bg=bg, bd=bd, relief=relief,
                     width=_THUMB_SIZE[0] + 8, height=_THUMB_SIZE[1] + 44)
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


def _shortcuts_label(parent, text: str):
    """Add a compact keyboard shortcuts hint at the bottom of a tab frame."""
    import tkinter as tk
    from tkinter import ttk
    f = ttk.Frame(parent)
    f.pack(side="bottom", fill="x", padx=6, pady=(0, 2))
    tk.Label(f, text=text, font=("sans-serif", 8), foreground="#666",
             anchor="w").pack(side="left")
    return f


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------

class App:
    """ppsp tkinter application — Work in Progress."""

    def __init__(self, source: Path) -> None:
        import tkinter as tk
        from tkinter import ttk

        from .session import load_session
        from .variants import ENFUSE_VARIANTS, TMO_VARIANTS, GRADING_PRESETS, CT_PRESETS

        self.source = source
        self.session = load_session(source)

        self.root = tk.Tk()
        self.root.title(f"ppsp — {source.name}  [Work in Progress]")
        self.root.minsize(960, 640)

        self._queue: "queue.Queue[Tuple[str, object]]" = queue.Queue()
        self._progress_text = tk.StringVar(value="")

        # Shared controls state
        self._quality_var = tk.IntVar(value=80)
        self._cull_size_var = tk.StringVar(value="z25")   # discovery size in Cull tab
        self._gen_size_var = tk.StringVar(value="z100")   # export size in Generate tab
        self._resolution_var = tk.StringVar(value="")
        self._viewer_var = tk.StringVar(value="xdg-open")

        # Discover (step-by-step selection) state
        self._review_sel: Dict[str, Dict[str, Set[str]]] = {}
        self._review_order: List[str] = []
        self._review_step = tk.StringVar(value="enfuse")
        self._review_stack_var = tk.StringVar(value="")
        self._tile_frames: List[Tuple[str, object]] = []   # (chain_id, frame)
        self._tile_data: List[Tuple[str, Path]] = []       # (chain_id, path) for fullscreen
        self._focused_chain: Optional[str] = None
        self._tile_idx: int = 0                             # index in _tile_frames
        self._compare_chain: Optional[str] = None          # for 'c' compare in fullscreen

        # Cull-tab stacks list state
        self._stack_rows: List[Tuple[str, object]] = []
        self._focused_stack_idx: int = 0
        self._stack_vars: Dict[str, "tk.BooleanVar"] = {}
        self._stacks_canvas = None
        self._stacks_inner = None
        self._stacks_inner_id = None

        # Generate tab
        self._export_src_var = tk.StringVar(value="session")

        # Log panel state
        self._log_collapsed = False
        self._log_tail_started = False
        self._log_text = None
        self._log_frame = None
        self._log_toggle_btn = None
        self._paned: Optional[object] = None
        self._log_sash_pos: Optional[int] = None

        # Metadata tab state
        self._meta_entries: List[Dict] = []   # [{sname, title_var, tags_var, rating_var}]
        self._meta_thumb_refs: List[object] = []  # keep thumbnail references alive

        # Status bar (packed first so it's always at very bottom)
        status = tk.Label(self.root, textvariable=self._progress_text, anchor="w",
                          relief="sunken", font=("mono", 9))
        status.pack(side="bottom", fill="x", padx=6, pady=(0, 2))

        # PanedWindow: notebook (top) + log panel (bottom, resizeable by dragging)
        paned = tk.PanedWindow(self.root, orient="vertical",
                               sashwidth=6, sashrelief="raised", bg="#aaa")
        paned.pack(fill="both", expand=True, padx=6, pady=6)
        self._paned = paned

        # Notebook in top pane
        nb_outer = ttk.Frame(paned)
        paned.add(nb_outer, stretch="always")
        nb = ttk.Notebook(nb_outer)
        nb.pack(fill="both", expand=True)
        self._nb = nb
        nb.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Log frame in bottom pane
        self._log_frame = ttk.Frame(paned)
        paned.add(self._log_frame, stretch="never", minsize=24)

        # Build all tabs (8 tabs)
        self._rename_frame = ttk.Frame(nb)
        self._organize_frame = ttk.Frame(nb)
        self._cull_frame = ttk.Frame(nb)
        self._metadata_frame = ttk.Frame(nb)
        self._variants_frame = ttk.Frame(nb)
        self._select_frame = ttk.Frame(nb)
        self._generate_frame = ttk.Frame(nb)
        self._cleanup_frame = ttk.Frame(nb)

        nb.add(self._rename_frame, text=" Rename ")
        nb.add(self._organize_frame, text=" Organize ")
        nb.add(self._cull_frame, text=" Cull ")
        nb.add(self._metadata_frame, text=" Metadata ")
        nb.add(self._variants_frame, text=" Variants ")
        nb.add(self._select_frame, text=" Select ")
        nb.add(self._generate_frame, text=" Generate ")
        nb.add(self._cleanup_frame, text=" Cleanup ")

        self._build_rename_tab()
        self._build_organize_tab()
        self._build_cull_tab()
        self._build_metadata_tab()
        self._build_variants_tab(ENFUSE_VARIANTS, TMO_VARIANTS, GRADING_PRESETS, CT_PRESETS)
        self._build_select_tab()
        self._build_generate_tab()
        self._build_cleanup_tab()

        # Build log panel contents (inside self._log_frame already in paned)
        self._build_log_panel()

        # Set initial sash position to ~80% after the window has been laid out
        self.root.after(150, self._set_initial_sash)

        self._bind_shortcuts()
        self.root.after(200, self._poll_queue)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _component_wins(self, component_id: str) -> int:
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
    # Tab 1 — Rename
    # ------------------------------------------------------------------

    def _build_rename_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._rename_frame
        tk.Label(frame, text="Normalize RAW filenames and write ppsp_photos.csv",
                 font=("TkDefaultFont", 10)).pack(pady=(12, 6))

        opts = ttk.LabelFrame(frame, text="Options")
        opts.pack(fill="x", padx=16, pady=4)
        ttk.Label(opts, text="Default camera model:").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self._rename_model_var = tk.StringVar(value="")
        ttk.Entry(opts, textvariable=self._rename_model_var, width=24).grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text="Default lens:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self._rename_lens_var = tk.StringVar(value="")
        ttk.Entry(opts, textvariable=self._rename_lens_var, width=24).grid(row=1, column=1, sticky="w")

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", padx=16, pady=8)
        self._rename_btn = ttk.Button(btn_row, text="▶  Run Rename", command=self._run_rename_cmd)
        self._rename_btn.pack(side="left")
        self._rename_progress = ttk.Progressbar(btn_row, mode="indeterminate", length=120)
        self._rename_progress.pack(side="left", padx=8)

        self._rename_status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._rename_status, foreground="#444").pack(
            anchor="w", padx=16)

    def _run_rename_cmd(self) -> None:
        self._rename_btn.state(["disabled"])
        self._rename_progress.start(10)
        self._rename_status.set("Running rename…")

        def _run():
            from .commands import cmd_rename
            try:
                cmd_rename([], self.source,
                           default_model=self._rename_model_var.get(),
                           default_lens=self._rename_lens_var.get(),
                           redo=False)
                self._queue.put(("rename_done", None))
            except Exception as exc:
                self._queue.put(("rename_error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Tab 2 — Organize
    # ------------------------------------------------------------------

    def _build_organize_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._organize_frame
        tk.Label(frame, text="Group files into per-stack folders",
                 font=("TkDefaultFont", 10)).pack(pady=(12, 6))

        opts = ttk.LabelFrame(frame, text="Options")
        opts.pack(fill="x", padx=16, pady=4)
        ttk.Label(opts, text="Time gap (s) to split stacks:").grid(
            row=0, column=0, sticky="w", padx=6, pady=3)
        self._organize_gap_var = tk.DoubleVar(value=30.0)
        ttk.Spinbox(opts, from_=1, to=300, textvariable=self._organize_gap_var,
                    width=8).grid(row=0, column=1, sticky="w")

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill="x", padx=16, pady=8)
        self._organize_btn = ttk.Button(btn_row, text="▶  Run Organize",
                                        command=self._run_organize_cmd)
        self._organize_btn.pack(side="left")
        self._organize_progress = ttk.Progressbar(btn_row, mode="indeterminate", length=120)
        self._organize_progress.pack(side="left", padx=8)

        self._organize_status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._organize_status, foreground="#444").pack(
            anchor="w", padx=16)

    def _run_organize_cmd(self) -> None:
        self._organize_btn.state(["disabled"])
        self._organize_progress.start(10)
        self._organize_status.set("Running organize…")

        def _run():
            from .commands import cmd_organize
            try:
                cmd_organize([], self.source, gap=float(self._organize_gap_var.get()), redo=False)
                self._queue.put(("organize_done", None))
            except Exception as exc:
                self._queue.put(("organize_error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Tab 3 — Cull (review/prune via cull grid only)
    # ------------------------------------------------------------------

    def _build_cull_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._cull_frame

        tk.Label(frame,
                 text="Review culling previews and prune unwanted stacks.",
                 font=("TkDefaultFont", 10)).pack(pady=(20, 8))
        tk.Label(frame,
                 text="Generate culling previews first via 'ppsp -c', then review below.",
                 foreground="#555").pack(pady=(0, 16))

        ttk.Button(frame, text="Open cull grid…",
                   command=self._open_cull_review).pack(ipadx=16, ipady=6)

        self._cull_status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._cull_status,
                  foreground="#555").pack(pady=8)

    # ------------------------------------------------------------------
    # Tab 5 — Variants (chain configurator + stacks list + generate)
    # ------------------------------------------------------------------

    def _build_variants_tab(self, enfuse_ids, tmo_ids, grading_ids, ct_ids) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._variants_frame

        # Left pane: stacks list
        left = ttk.LabelFrame(frame, text="Stacks")
        left.pack(side="left", fill="both", expand=True, padx=6, pady=6)

        canvas = tk.Canvas(left)
        sb = ttk.Scrollbar(left, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._stacks_inner = tk.Frame(canvas)
        self._stacks_inner_id = canvas.create_window(
            (0, 0), window=self._stacks_inner, anchor="nw")
        self._stacks_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._stacks_inner_id, width=e.width))
        self._stacks_canvas = canvas

        self._stack_vars = {}

        ttk.Button(left, text="Select all",
                   command=self._select_all_stacks).pack(side="bottom", fill="x", padx=4, pady=2)
        ttk.Button(left, text="Deselect all",
                   command=self._deselect_all_stacks).pack(side="bottom", fill="x", padx=4, pady=2)

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
            ttk.Radiobutton(ctrl, text=f"{key}/{label}", variable=self._cull_size_var,
                            value=key).grid(row=0, column=i + 1, sticky="w")

        ttk.Label(ctrl, text="Quality:").grid(row=1, column=0, sticky="w")
        ttk.Spinbox(ctrl, from_=50, to=100, textvariable=self._quality_var,
                    width=5).grid(row=1, column=1, sticky="w")

        ttk.Label(ctrl, text="Viewer:").grid(row=2, column=0, sticky="w")
        ttk.Entry(ctrl, textvariable=self._viewer_var, width=18).grid(
            row=2, column=1, columnspan=4, sticky="ew")

        ttk.Separator(right).pack(fill="x", pady=4)

        preset_frame = ttk.LabelFrame(right, text="Quick presets")
        preset_frame.pack(fill="x", padx=4, pady=4)
        for preset in ("some", "many", "lots", "all"):
            ttk.Button(preset_frame, text=preset,
                       command=lambda p=preset: self._apply_preset(p)).pack(side="left", padx=2)

        self._gen_btn = ttk.Button(right, text="▶  Generate variants", command=self._generate)
        self._gen_btn.pack(fill="x", padx=4, pady=4)

        self._progress_bar = ttk.Progressbar(right, mode="indeterminate")
        self._progress_bar.pack(fill="x", padx=4, pady=2)

        _shortcuts_label(frame,
            "← → move stack  ·  Enter toggle  ·  Select all/Deselect all for batch")
        self._load_stacks()

    # ------------------------------------------------------------------
    # Stacks list helpers (shared by Cull tab)
    # ------------------------------------------------------------------

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
        _, old_frame = self._stack_rows[self._focused_stack_idx]
        old_frame.configure(bg="SystemButtonFace")  # type: ignore[union-attr]
        self._focused_stack_idx = (self._focused_stack_idx + delta) % len(self._stack_rows)
        _, new_frame = self._stack_rows[self._focused_stack_idx]
        new_frame.configure(bg=_ROW_BG_FOCUSED)  # type: ignore[union-attr]
        if self._stacks_canvas:
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

        z_tier = self._cull_size_var.get()
        quality = self._quality_var.get()

        self._gen_btn.state(["disabled"])
        self._progress_bar.start(10)
        self._set_status(f"Generating {len(stacks)} stacks…")
        self._uncollapse_log()

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
    # Culling grid (review cull/ previews, mark stacks to prune)
    # ------------------------------------------------------------------

    def _open_cull_review(self) -> None:
        """Open the culling grid modal so the user can mark stacks for pruning."""
        import tkinter as tk
        from tkinter import ttk

        cull_dir = self.source / "cull"
        previews = sorted(cull_dir.glob("*.jpg")) if cull_dir.exists() else []
        if not previews:
            from tkinter import messagebox
            messagebox.showinfo("No cull previews",
                                "Run 'ppsp -c' first to generate culling previews.")
            return

        top = tk.Toplevel(self.root)
        top.title("Cull — keep or prune stacks")
        top.geometry("1200x760")
        top.grab_set()

        # Load title/tags/rating from CSV for display in fullscreen
        from .naming import load_stacks_csv
        stacks_meta: Dict[str, Dict] = {}
        for row in load_stacks_csv(self.source):
            stacks_meta[row.get("StackFolder", "")] = row

        help_text = ("Click for focus  ·  Space toggle prune  ·  "
                     "Double-click / F fullscreen  ·  Esc close")
        ttk.Label(top, text=help_text,
                  font=("sans-serif", 9), foreground="#555").pack(pady=4)

        cull_states: Dict[str, bool] = {}
        cull_imgs: Dict[str, object] = {}

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
        _focused_cull = [None]  # currently focused stack name
        COLS = _CULL_GRID_COLS
        row_frame = None

        def _cull_bg(sname: str) -> str:
            keep = cull_states.get(sname, True)
            focused = _focused_cull[0] == sname
            if not keep:
                return "#b0b0b0"
            if focused:
                return _ROW_BG_FOCUSED
            return "#f0f0f0"

        def _refresh_tile(sname: str) -> None:
            f = tile_frames.get(sname)
            if f is None:
                return
            bg = _cull_bg(sname)
            f.configure(bg=bg)  # type: ignore[union-attr]
            for child in f.winfo_children():  # type: ignore[union-attr]
                try:
                    child.configure(bg=bg)
                except Exception:
                    pass

        def _set_focus(sname: str) -> None:
            old = _focused_cull[0]
            _focused_cull[0] = sname
            if old and old != sname:
                _refresh_tile(old)
            _refresh_tile(sname)

        def _toggle(sname: str) -> None:
            cull_states[sname] = not cull_states.get(sname, True)
            _refresh_tile(sname)

        def _open_fullscreen(sname: str) -> None:
            ordered_names = [p.name.split("_count")[0] for p in previews]
            start_idx = ordered_names.index(sname) if sname in ordered_names else 0
            _idx = [start_idx]
            _prev_idx = [start_idx]

            fs = tk.Toplevel(top)
            fs.title("Fullscreen Cull")
            fs.geometry("1280x900")
            fs.grab_set()

            meta_lbl = tk.Label(fs, text="", font=("mono", 10), anchor="w")
            meta_lbl.pack(side="top", fill="x", padx=8, pady=4)

            info_lbl = tk.Label(fs, text="", font=("mono", 9), foreground="#555")
            info_lbl.pack(side="top")

            img_lbl = tk.Label(fs, bg="black")
            img_lbl.pack(fill="both", expand=True)
            _ref = [None]

            def _fs_show(i: int) -> None:
                _prev_idx[0] = _idx[0]
                _idx[0] = i % len(previews)
                pv = previews[_idx[0]]
                sn = pv.name.split("_count")[0]
                keep = cull_states.get(sn, True)
                img = _load_thumb(pv, (1180, 820))
                _ref[0] = img
                img_lbl.configure(image=img)

                # Show title/tags/rating if available
                meta = stacks_meta.get(sn, {})
                title = meta.get("Title", "")
                tags = meta.get("Tags", "")
                rating = meta.get("Rating", "")
                meta_parts = []
                if title:
                    meta_parts.append(f"Title: {title}")
                if tags:
                    meta_parts.append(f"Tags: {tags}")
                if rating:
                    meta_parts.append(f"Rating: {rating}")
                meta_lbl.configure(text="  ·  ".join(meta_parts) if meta_parts else sn)

                info_lbl.configure(
                    text=f"{_idx[0] + 1}/{len(previews)}: {sn}  "
                         f"{'KEEP' if keep else 'PRUNE'}"
                         "    Space=toggle  ←/→=browse  c=compare  Esc=close"
                )

            def _fs_toggle(_e=None) -> None:
                sn = previews[_idx[0]].name.split("_count")[0]
                _toggle(sn)
                _fs_show(_idx[0])

            def _fs_compare(_e=None) -> None:
                if _prev_idx[0] != _idx[0]:
                    cur = _idx[0]
                    _fs_show(_prev_idx[0])
                    _prev_idx[0] = cur  # swap so pressing c again goes back

            def _fs_fullscreen_key(_e=None) -> None:
                pass  # already fullscreen

            fs.bind("<Escape>", lambda _e: fs.destroy())
            fs.bind("<Left>", lambda _e: _fs_show(_idx[0] - 1))
            fs.bind("<Right>", lambda _e: _fs_show(_idx[0] + 1))
            fs.bind("<space>", _fs_toggle)
            fs.bind("c", _fs_compare)
            fs.bind("C", _fs_compare)
            fs.focus_set()
            _fs_show(_idx[0])

        for pidx, pv in enumerate(previews):
            sname = pv.name.split("_count")[0]
            cull_states[sname] = True
            if pidx % COLS == 0:
                row_frame = tk.Frame(inner)
                row_frame.pack(fill="x", pady=2)

            f = tk.Frame(row_frame, bg="#f0f0f0", bd=1, relief="raised",
                         width=_CULL_THUMB_SIZE[0] + 10, height=_CULL_THUMB_SIZE[1] + 44)
            f.pack_propagate(False)
            f.pack(side="left", padx=3, pady=2)
            tile_frames[sname] = f

            img = _load_thumb(pv, _CULL_THUMB_SIZE)
            cull_imgs[sname] = img
            if img:
                il = tk.Label(f, image=img, bg="#f0f0f0")
                il.image = img
                il.pack(pady=(3, 0))
                il.bind("<Button-1>", lambda _e, s=sname: _set_focus(s))
                il.bind("<Double-Button-1>", lambda _e, s=sname: _open_fullscreen(s))

            parts = sname.split("-")
            short = parts[2] if len(parts) >= 3 else sname
            tl = tk.Label(f, text=short, bg="#f0f0f0", font=("mono", 9))
            tl.pack(pady=(1, 3))
            tl.bind("<Button-1>", lambda _e, s=sname: _set_focus(s))
            f.bind("<Button-1>", lambda _e, s=sname: _set_focus(s))

        # Space key toggles focused stack; F opens fullscreen
        def _on_space(_e=None) -> None:
            sn = _focused_cull[0]
            if sn:
                _toggle(sn)

        def _on_f(_e=None) -> None:
            sn = _focused_cull[0]
            if sn:
                _open_fullscreen(sn)

        top.bind("<space>", _on_space)
        top.bind("f", _on_f)
        top.bind("F", _on_f)

        # Bottom bar
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
                self._load_stacks()
            top.destroy()

        ttk.Button(bot, text="✓ Confirm culling", command=_confirm).pack(side="right", padx=4)
        ttk.Label(bot, text="Dimmed stacks will be pruned.",
                  foreground="#555").pack(side="left")

    # ------------------------------------------------------------------
    # Tab 4 — Metadata (name, tag, rate stacks)
    # ------------------------------------------------------------------

    def _build_metadata_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._metadata_frame

        hdr = ttk.Frame(frame)
        hdr.pack(fill="x", padx=8, pady=4)
        tk.Label(hdr, text="Name, tag and rate stacks",
                 font=("TkDefaultFont", 10)).pack(side="left")
        ttk.Button(hdr, text="↺ Reload",
                   command=self._load_metadata).pack(side="right", padx=4)
        ttk.Button(hdr, text="✓ Save All",
                   command=self._save_metadata).pack(side="right", padx=4)
        ttk.Button(hdr, text="Rename stack dirs",
                   command=self._rename_stack_dirs).pack(side="right", padx=4)

        col_hdr = tk.Frame(frame, bg="#ddd")
        col_hdr.pack(fill="x", padx=8, pady=(0, 2))
        # Thumb placeholder column (width matches _META_THUMB_SIZE[0])
        tk.Label(col_hdr, text="", bg="#ddd",
                 width=_META_THUMB_SIZE[0] // 8).pack(side="left", padx=2)
        for text, w in [("Folder / RAW count", 36), ("Title", 28), ("Tags", 22), ("Rating", 8), ("Comment", 28)]:
            tk.Label(col_hdr, text=text, bg="#ddd", font=("mono", 9, "bold"),
                     width=w, anchor="w").pack(side="left", padx=2)

        canvas = tk.Canvas(frame)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=8)

        self._meta_inner = tk.Frame(canvas)
        meta_id = canvas.create_window((0, 0), window=self._meta_inner, anchor="nw")
        self._meta_inner.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(meta_id, width=e.width))

        self._meta_status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._meta_status, foreground="#555").pack(
            anchor="w", padx=8, pady=2)

        _shortcuts_label(frame, "Edit fields inline  ·  Save All writes ppsp_stacks.csv + sidecars  ·  Rename stack dirs applies shorthands")
        self._load_metadata()

    def _load_metadata(self) -> None:
        import tkinter as tk
        from tkinter import ttk
        from .naming import load_stacks_csv, build_stacks_csv_rows, _RAW_EXTS

        for w in self._meta_inner.winfo_children():
            w.destroy()
        self._meta_entries.clear()
        self._meta_thumb_refs.clear()

        existing = load_stacks_csv(self.source)
        rows = build_stacks_csv_rows(self.source, existing)

        for row in rows:
            sname = row.get("StackFolder", "")
            title = row.get("Title", "")
            tags = row.get("Tags", "")
            rating = row.get("Rating", "")
            comment = row.get("Comment", "")

            stack_dir = self.source / sname
            raw_count = sum(
                1 for f in stack_dir.iterdir()
                if f.is_file() and f.suffix.lower() in _RAW_EXTS
            ) if stack_dir.exists() else 0

            r = tk.Frame(self._meta_inner, pady=1)
            r.pack(fill="x")

            # Thumbnail: try cull preview, z2, z6 dirs; show gray box on failure
            thumb_img = self._find_meta_thumb(sname)
            if thumb_img:
                self._meta_thumb_refs.append(thumb_img)
                tk.Label(r, image=thumb_img, anchor="w").pack(side="left", padx=2)
            else:
                tk.Label(r, text="", bg="#ccc",
                         width=_META_THUMB_SIZE[0] // 8,
                         height=_META_THUMB_SIZE[1] // 16).pack(side="left", padx=2)

            # Full folder name + raw count
            folder_label = f"{sname}  [{raw_count} RAW]" if raw_count else sname
            tk.Label(r, text=folder_label, font=("mono", 8), width=36,
                     anchor="w").pack(side="left", padx=2)

            title_var = tk.StringVar(value=title)
            ttk.Entry(r, textvariable=title_var, width=28).pack(side="left", padx=2)

            tags_var = tk.StringVar(value=tags)
            ttk.Entry(r, textvariable=tags_var, width=22).pack(side="left", padx=2)

            rating_var = tk.StringVar(value=rating)
            ttk.Spinbox(r, from_=0, to=5, textvariable=rating_var, width=5).pack(
                side="left", padx=2)

            comment_var = tk.StringVar(value=comment)
            ttk.Entry(r, textvariable=comment_var, width=28).pack(side="left", padx=2)

            self._meta_entries.append({
                "sname": sname,
                "title_var": title_var,
                "tags_var": tags_var,
                "rating_var": rating_var,
                "comment_var": comment_var,
            })

        self._meta_status.set(f"Loaded {len(rows)} stacks.")

    def _find_meta_thumb(self, sname: str) -> Optional[object]:
        """Return a small PhotoImage for the metadata row, or None."""
        stack_dir = self.source / sname
        candidates: List[Path] = []
        # Try cull preview first (smallest dedicated preview)
        cull_dir = self.source / "cull"
        base = stack_dir_to_filename_base(sname)
        if cull_dir.exists():
            candidates.extend(sorted(cull_dir.glob(f"{base}_count*.jpg"))[:1])
        # Fallback: smallest z-tier dirs
        for zt in ("z2", "z6", "z25"):
            zd = stack_dir / zt
            if zd.exists():
                jpgs = sorted(zd.glob("*.jpg"))
                if jpgs:
                    candidates.append(jpgs[0])
                    break
        for path in candidates:
            img = _load_thumb(path, _META_THUMB_SIZE)
            if img:
                return img
        return None

    def _save_metadata(self) -> None:
        from .naming import (build_stacks_csv_rows, load_stacks_csv, save_stacks_csv,
                              write_sidecar)

        existing = load_stacks_csv(self.source)
        rows = build_stacks_csv_rows(self.source, existing)
        row_by_name = {r["StackFolder"]: r for r in rows}

        for entry in self._meta_entries:
            sname = entry["sname"]
            title = entry["title_var"].get().strip()
            tags = entry["tags_var"].get().strip()
            rating = entry["rating_var"].get().strip()
            comment = entry["comment_var"].get().strip()

            if sname in row_by_name:
                row_by_name[sname]["Title"] = title
                row_by_name[sname]["Tags"] = tags
                row_by_name[sname]["Rating"] = rating
                row_by_name[sname]["Comment"] = comment

            stack_dir = self.source / sname
            if stack_dir.exists():
                write_sidecar(stack_dir, title, tags=tags, rating=rating, comment=comment)

        save_stacks_csv(self.source, list(row_by_name.values()))
        self._meta_status.set("Saved ppsp_stacks.csv and sidecars.")

    def _rename_stack_dirs(self) -> None:
        from .naming import load_stacks_csv, rename_stack
        rows = load_stacks_csv(self.source)
        renamed = 0
        for row in rows:
            title = row.get("Title", "").strip()
            if not title:
                continue
            sname = row.get("StackFolder", "")
            stack_dir = self.source / sname
            if stack_dir.exists():
                result = rename_stack(stack_dir, title, self.source)
                if result and result != stack_dir:
                    renamed += 1
        self._meta_status.set(f"Renamed {renamed} stack director{'y' if renamed == 1 else 'ies'}.")
        self._load_stacks()
        self._load_metadata()

    # ------------------------------------------------------------------
    # Tab 6 — Select (step-by-step variant selection)
    # ------------------------------------------------------------------

    def _build_select_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._select_frame

        top = ttk.Frame(frame)
        top.pack(fill="x", padx=6, pady=4)

        ttk.Label(top, text="Stack:").pack(side="left")
        self._stack_combo = ttk.Combobox(top, textvariable=self._review_stack_var,
                                          state="readonly", width=40)
        self._stack_combo.pack(side="left", padx=4)
        self._stack_combo.bind("<<ComboboxSelected>>", lambda _: self._refresh_select())

        step_frame = ttk.LabelFrame(top, text="Step")
        step_frame.pack(side="left", padx=8)
        for step, label in [("enfuse", "1 Enfuse"), ("tmo", "2 TMO"),
                             ("grading", "3 Grading"), ("ct", "4 CT")]:
            ttk.Radiobutton(step_frame, text=label, variable=self._review_step,
                            value=step,
                            command=self._refresh_select_tiles).pack(side="left", padx=2)

        self._select_btn_next = ttk.Button(top, text="Next step ▶",
                                            command=self._discover_next_step)
        self._select_btn_next.pack(side="left", padx=4)
        ttk.Button(top, text="Save to session",
                   command=self._save_discover_to_session).pack(side="left", padx=4)

        # Tile area
        canvas = tk.Canvas(frame)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True, padx=6, pady=4)

        self._select_canvas = canvas
        self._select_tiles_frame = tk.Frame(canvas)
        self._select_tiles_id = canvas.create_window(
            (0, 0), window=self._select_tiles_frame, anchor="nw")
        self._select_tiles_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
            lambda e: canvas.itemconfig(self._select_tiles_id, width=e.width))

        bot = ttk.Frame(frame)
        bot.pack(fill="x", padx=6, pady=4)
        ttk.Button(bot, text="Select all",
                   command=lambda: self._set_all_tiles(True)).pack(side="left", padx=2)
        ttk.Button(bot, text="Deselect all",
                   command=lambda: self._set_all_tiles(False)).pack(side="left", padx=2)
        ttk.Button(bot, text="← Prev stack",
                   command=lambda: self._navigate_select_stack(-1)).pack(side="left", padx=2)
        ttk.Button(bot, text="Next stack →",
                   command=lambda: self._navigate_select_stack(1)).pack(side="left", padx=2)

        self._review_info = tk.StringVar(value="")
        ttk.Label(bot, textvariable=self._review_info).pack(side="right")

        _shortcuts_label(frame,
            "← → ↑ ↓ move focus  ·  Space select/unselect  ·  D discard  ·  R restore  ·  "
            "F / dbl-click fullscreen  ·  Tab next step  ·  (fullscreen: c compare)")

    def _on_tab_changed(self, _event=None) -> None:
        tab = self._active_tab()
        if tab == "Select":
            self._refresh_select_stack_list()
        elif tab == "Generate":
            if not self._log_tail_started:
                self._log_tail_started = True
                self._start_log_tail()

    def _refresh_select_stack_list(self) -> None:
        stacks = [d.name for d in find_stack_dirs(self.source)]
        self._stack_combo["values"] = stacks
        if stacks and not self._review_stack_var.get():
            self._review_stack_var.set(stacks[0])
            self._refresh_select()

    def _refresh_select(self) -> None:
        sname = self._review_stack_var.get()
        if not sname:
            return

        if sname not in self._review_sel:
            prev = next(
                (s for s in reversed(self._review_order) if s != sname and s in self._review_sel),
                None,
            )
            if prev and any(self._review_sel[prev].values()):
                self._review_sel[sname] = copy.deepcopy(self._review_sel[prev])
            else:
                self._review_sel[sname] = {"enfuse": set(), "tmo": set(), "grading": set(), "ct": set()}

        if not self._review_order or self._review_order[-1] != sname:
            self._review_order.append(sname)

        self._review_step.set("enfuse")
        self._refresh_select_tiles()

    def _refresh_select_tiles(self) -> None:
        import tkinter as tk
        from .variants import ENFUSE_VARIANTS, TMO_VARIANTS, GRADING_PRESETS, CT_PRESETS, Z_TIERS

        sname = self._review_stack_var.get()
        if not sname:
            return
        step = self._review_step.get()

        z_tier = self._cull_size_var.get()
        stack_dir = self.source / sname
        z_dir = stack_dir / z_tier
        variants_dir = self.source / "variants"
        stack_base = stack_dir_to_filename_base(sname)

        known_enfuse = frozenset(ENFUSE_VARIANTS.keys()) | {"focu"}
        known_tmos = frozenset(TMO_VARIANTS.keys())
        known_gradings = frozenset(GRADING_PRESETS.keys())
        known_cts = frozenset(CT_PRESETS.keys())

        candidates: List[Path] = []
        for d in (variants_dir, z_dir):
            if d.exists():
                for f in d.glob(f"{stack_base}-*.jpg"):
                    if "collage" not in f.name and f not in candidates:
                        candidates.append(f)

        sel = self._review_sel.setdefault(
            sname, {"enfuse": set(), "tmo": set(), "grading": set(), "ct": set()})
        discarded_chains = {c for c, s in self.session.chain_stats.items() if s.discarded}

        def _chain_tokens(fpath: Path) -> Optional[List[str]]:
            stem = fpath.stem
            prefix = stack_base + "-"
            if not stem.startswith(prefix):
                return None
            parts = stem[len(prefix):].split("-")
            for i, p in enumerate(parts):
                if p in Z_TIERS:
                    return parts[i + 1:]
            return None

        display: Dict[str, Path] = {}

        if step == "enfuse":
            # Show only enfuse-only stubs: 1 token, known enfuse id
            for fpath in sorted(candidates):
                toks = _chain_tokens(fpath)
                if toks and len(toks) == 1 and toks[0] in known_enfuse:
                    display.setdefault(toks[0], fpath)
            info = "1/4 — Select enfuse base(s)  (educational: raw fusion output, no TMO, no grading)"

        elif step == "tmo":
            # Show only TMO stubs: 2 tokens, enfuse+TMO (no grading)
            enfuse_sel = sel["enfuse"]
            for fpath in sorted(candidates):
                toks = _chain_tokens(fpath)
                if not toks or len(toks) != 2:
                    continue
                if toks[0] not in known_enfuse or toks[1] not in known_tmos:
                    continue
                if enfuse_sel and toks[0] not in enfuse_sel:
                    continue
                key = f"{toks[0]}-{toks[1]}"
                display.setdefault(key, fpath)
            info = "2/4 — Select TMO combination(s)  (educational: enfuse+TMO output before grading)"

        elif step == "grading":
            # Show full grading chains: {e}-{g} (no TMO) or {e}-{t}-{g} (with TMO), no CT
            enfuse_sel = sel["enfuse"]
            tmo_sel = sel["tmo"]
            for fpath in sorted(candidates):
                toks = _chain_tokens(fpath)
                if not toks:
                    continue
                if (len(toks) == 2 and toks[0] in known_enfuse
                        and toks[1] in known_gradings):
                    # No-TMO path: enfuse + grading
                    if enfuse_sel and toks[0] not in enfuse_sel:
                        continue
                    key = f"{toks[0]}-{toks[1]}"
                    display.setdefault(key, fpath)
                elif (len(toks) == 3 and toks[0] in known_enfuse
                      and toks[1] in known_tmos and toks[2] in known_gradings):
                    # TMO path: enfuse + TMO + grading
                    if enfuse_sel and toks[0] not in enfuse_sel:
                        continue
                    tmo_key = f"{toks[0]}-{toks[1]}"
                    if tmo_sel and tmo_key not in tmo_sel:
                        continue
                    key = f"{toks[0]}-{toks[1]}-{toks[2]}"
                    display.setdefault(key, fpath)
            info = "3/4 — Select grading chain(s) to publish"

        else:  # ct
            # Show CT variants: last token is a CT id
            enfuse_sel = sel["enfuse"]
            tmo_sel = sel["tmo"]
            grading_sel = sel["grading"]
            for fpath in sorted(candidates):
                toks = _chain_tokens(fpath)
                if not toks or toks[-1] not in known_cts:
                    continue
                if (len(toks) == 3 and toks[0] in known_enfuse
                        and toks[1] in known_gradings):
                    # No-TMO+CT: enfuse+grading+ct
                    if enfuse_sel and toks[0] not in enfuse_sel:
                        continue
                    grading_key = f"{toks[0]}-{toks[1]}"
                    if grading_sel and grading_key not in grading_sel:
                        continue
                    display.setdefault("-".join(toks), fpath)
                elif (len(toks) == 4 and toks[0] in known_enfuse
                      and toks[1] in known_tmos and toks[2] in known_gradings):
                    # TMO+CT: enfuse+TMO+grading+ct
                    if enfuse_sel and toks[0] not in enfuse_sel:
                        continue
                    tmo_key = f"{toks[0]}-{toks[1]}"
                    if tmo_sel and tmo_key not in tmo_sel:
                        continue
                    grading_key = f"{toks[0]}-{toks[1]}-{toks[2]}"
                    if grading_sel and grading_key not in grading_sel:
                        continue
                    display.setdefault("-".join(toks), fpath)
            info = "4/4 — Select color-temperature variant(s)"

        tiles: List[Tuple[str, Path]] = list(sorted(display.items()))

        # Full rebuild of tile widgets
        for w in self._select_tiles_frame.winfo_children():
            w.destroy()
        self._tile_frames.clear()
        self._tile_data = list(tiles)
        self._review_info.set(info)

        step_sel = sel.get(step, set())
        row_frame = None
        COLS = _DISCOVER_COLS

        tile_ids = {cid for cid, _ in tiles}
        if self._focused_chain not in tile_ids:
            self._focused_chain = tiles[0][0] if tiles else None
            self._tile_idx = 0

        for idx, (chain_id, fpath) in enumerate(tiles):
            if idx % COLS == 0:
                row_frame = tk.Frame(self._select_tiles_frame)
                row_frame.pack(fill="x", pady=2)

            wins = self._component_wins(chain_id)
            focused = chain_id == self._focused_chain
            bg = self._tile_bg(chain_id, step_sel, discarded_chains)
            img = _load_thumb(fpath)
            tile = _make_tile(
                row_frame, chain_id, img, wins, bg,
                on_click=self._move_focus_to_tile,
                on_double_click=self._open_fullscreen,
                focused=focused,
            )
            tile.pack(side="left", padx=4, pady=2)
            self._tile_frames.append((chain_id, tile))
            if chain_id == self._focused_chain:
                self._tile_idx = idx

        if not tiles:
            tk.Label(self._select_tiles_frame,
                     text="No variants found for this step. Run Variants → Generate variants first.",
                     font=("sans-serif", 11)).pack(pady=20)

    def _tile_bg(self, chain_id: str, step_sel: Set[str],
                 discarded_chains: Set[str]) -> str:
        selected = chain_id in step_sel
        is_discarded = chain_id in discarded_chains
        focused = chain_id == self._focused_chain
        if is_discarded:
            return _TILE_BG_DISCARDED
        if focused and selected:
            return _TILE_BG_FOCUSED_SELECTED
        if selected:
            return _TILE_BG_SELECTED
        if focused:
            return _TILE_BG_FOCUSED
        return _TILE_BG_DEFAULT

    def _update_tile_appearances(self) -> None:
        """Update tile backgrounds in-place — no widget rebuild, no flicker."""
        sname = self._review_stack_var.get()
        step = self._review_step.get()
        sel = self._review_sel.get(sname, {}).get(step, set())
        discarded = {c for c, s in self.session.chain_stats.items() if s.discarded}

        for i, (chain_id, frame) in enumerate(self._tile_frames):
            focused = chain_id == self._focused_chain
            bg = self._tile_bg(chain_id, sel, discarded)
            bd = 3 if focused else 1
            relief = "solid" if focused else "raised"
            frame.configure(bg=bg, bd=bd, relief=relief)  # type: ignore[union-attr]
            for child in frame.winfo_children():  # type: ignore[union-attr]
                try:
                    child.configure(bg=bg)
                except Exception:
                    pass

    def _move_focus_to_tile(self, chain_id: str) -> None:
        """Move keyboard focus to a tile without toggling its selection."""
        old = self._focused_chain
        self._focused_chain = chain_id
        for i, (cid, _) in enumerate(self._tile_frames):
            if cid == chain_id:
                self._tile_idx = i
                break
        self._update_tile_appearances()

    def _toggle_tile_select(self) -> None:
        """Toggle selection of the currently focused tile (Space key)."""
        if self._focused_chain is None:
            return
        sname = self._review_stack_var.get()
        step = self._review_step.get()
        cur = self._review_sel.setdefault(
            sname, {"enfuse": set(), "tmo": set(), "grading": set()})
        chain_id = self._focused_chain
        if chain_id in cur[step]:
            cur[step].discard(chain_id)
        else:
            cur[step].add(chain_id)
        self._compare_chain = chain_id
        self._update_tile_appearances()

    def _navigate_tile_grid(self, dx: int, dy: int) -> None:
        """Move tile focus by (dx, dy) in the grid (dx=col delta, dy=row delta)."""
        if not self._tile_frames:
            return
        COLS = _DISCOVER_COLS
        total = len(self._tile_frames)
        old = self._tile_idx
        old_row = old // COLS
        old_col = old % COLS

        new_col = old_col + dx
        new_row = old_row + dy

        # Wrap column left/right to prev/next row
        if new_col < 0:
            new_row -= 1
            new_col = COLS - 1
        elif new_col >= COLS:
            new_row += 1
            new_col = 0

        new_idx = new_row * COLS + new_col
        new_idx = max(0, min(new_idx, total - 1))

        self._tile_idx = new_idx
        chain_id, _ = self._tile_frames[new_idx]
        self._focused_chain = chain_id
        self._update_tile_appearances()

    def _open_fullscreen(self, start_chain_id: str) -> None:
        """Open large-image viewer starting at start_chain_id; 'c' compares with previous."""
        import tkinter as tk
        if not self._tile_data:
            return

        idx = next(
            (i for i, (cid, _) in enumerate(self._tile_data) if cid == start_chain_id), 0)

        top = tk.Toplevel(self.root)
        top.title("Fullscreen — ppsp Discover")
        top.geometry("1280x900")
        top.grab_set()

        info_lbl = tk.Label(top, text="", font=("mono", 10))
        info_lbl.pack(side="top", pady=4)

        img_lbl = tk.Label(top, bg="black")
        img_lbl.pack(fill="both", expand=True)

        _cur = [idx]
        _prev = [idx]  # for compare mode
        _img_ref = [None]

        def _show(i: int) -> None:
            _prev[0] = _cur[0]
            _cur[0] = i % len(self._tile_data)
            cid, fpath = self._tile_data[_cur[0]]
            sname = self._review_stack_var.get()
            step = self._review_step.get()
            sel = self._review_sel.get(sname, {}).get(step, set())
            status = " [✓ SELECTED]" if cid in sel else ""
            img = _load_thumb(fpath, (1180, 820))
            _img_ref[0] = img
            img_lbl.configure(image=img)
            info_lbl.configure(
                text=(f"{_cur[0] + 1}/{len(self._tile_data)}: {cid}{status}"
                      "    Space=toggle  ←/→=browse  c=compare  Esc=close")
            )
            # Update focused chain in main view
            self._focused_chain = cid

        def _toggle(_e=None) -> None:
            cid, _ = self._tile_data[_cur[0]]
            self._toggle_tile_select()
            _show(_cur[0])

        def _compare(_e=None) -> None:
            """Toggle between current and previous image."""
            if _prev[0] != _cur[0]:
                dest = _prev[0]
                _prev[0] = _cur[0]
                _cur[0] = dest
                cid, fpath = self._tile_data[_cur[0]]
                sname = self._review_stack_var.get()
                step = self._review_step.get()
                sel = self._review_sel.get(sname, {}).get(step, set())
                status = " [✓ SELECTED]" if cid in sel else ""
                img = _load_thumb(fpath, (1180, 820))
                _img_ref[0] = img
                img_lbl.configure(image=img)
                info_lbl.configure(
                    text=(f"{_cur[0] + 1}/{len(self._tile_data)}: {cid}{status}"
                          "    Space=toggle  ←/→=browse  c=compare  Esc=close  [comparing]")
                )
                self._focused_chain = cid

        top.bind("<Escape>", lambda _e: top.destroy())
        top.bind("<Left>", lambda _e: _show(_cur[0] - 1))
        top.bind("<Right>", lambda _e: _show(_cur[0] + 1))
        top.bind("<space>", _toggle)
        top.bind("c", _compare)
        top.bind("C", _compare)
        top.focus_set()
        _show(idx)

    def _discard_focused(self) -> None:
        if self._focused_chain is None:
            return
        self.session.discard(self._focused_chain)
        from .session import save_session
        save_session(self.session, self.source)
        self._set_status(f"Discarded: {self._focused_chain}")
        self._update_tile_appearances()

    def _reactivate_focused(self) -> None:
        if self._focused_chain is None:
            return
        self.session.reactivate(self._focused_chain)
        from .session import save_session
        save_session(self.session, self.source)
        self._set_status(f"Reintroduced: {self._focused_chain}")
        self._update_tile_appearances()

    def _discover_next_step(self) -> None:
        sname = self._review_stack_var.get()
        step = self._review_step.get()
        sel = self._review_sel.get(sname, {})
        if not sel.get(step):
            self._review_info.set("⚠  Select at least one variant before advancing.")
            return
        steps = ["enfuse", "tmo", "grading", "ct"]
        idx = steps.index(step)
        if idx < len(steps) - 1:
            self._review_step.set(steps[idx + 1])
            self._refresh_select_tiles()

    def _set_all_tiles(self, selected: bool) -> None:
        sname = self._review_stack_var.get()
        step = self._review_step.get()
        if not sname or not step:
            return
        sel = self._review_sel.setdefault(
            sname, {"enfuse": set(), "tmo": set(), "grading": set(), "ct": set()})
        if selected:
            for cid, _ in self._tile_frames:
                sel[step].add(cid)
        else:
            sel[step].clear()
        self._update_tile_appearances()

    def _save_discover_to_session(self) -> None:
        from tkinter import messagebox
        sname = self._review_stack_var.get()
        if not sname:
            return
        sel = self._review_sel.get(sname, {})
        # Prefer CT selections if any; otherwise use grading chains
        ct_chains = list(sel.get("ct", set()))
        grading_chains = list(sel.get("grading", set()))
        selected_chains = ct_chains if ct_chains else grading_chains
        if not selected_chains:
            messagebox.showinfo("Nothing selected",
                                "Select variants in the Grading (or CT) step first.")
            return

        from .interactive import _scan_z_dir
        z_tier = self._cull_size_var.get()
        stack_dir = self.source / sname
        generated = _scan_z_dir(stack_dir, z_tier)

        self.session.record_round(sname, generated, selected_chains)
        from .session import save_session
        save_session(self.session, self.source)
        self._set_status(f"Session saved — {sname}: {', '.join(selected_chains)}")
        messagebox.showinfo("Saved",
                            f"Selection saved for {sname}.\n\n{', '.join(selected_chains)}")

    def _navigate_select_stack(self, delta: int) -> None:
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
        self._refresh_select()

    # ------------------------------------------------------------------
    # Tab 6 — Generate (export finals)
    # ------------------------------------------------------------------

    def _build_generate_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._generate_frame

        # Z-tier at top
        ztier_frame = ttk.LabelFrame(frame, text="Output size")
        ztier_frame.pack(fill="x", padx=12, pady=8)
        for key, label in [("z100", "full / z100"), ("z25", "half / z25"),
                            ("z6", "quarter / z6"), ("z2", "micro / z2")]:
            ttk.Radiobutton(ztier_frame, text=label, variable=self._gen_size_var,
                            value=key).pack(side="left", padx=8)

        # Variant source (session winners at top)
        src_frame = ttk.LabelFrame(frame, text="Variant source")
        src_frame.pack(fill="x", padx=12, pady=4)
        ttk.Radiobutton(src_frame,
                        text="Session winners (active chains from Discover tab)",
                        variable=self._export_src_var, value="session").pack(anchor="w", padx=6)
        ttk.Radiobutton(src_frame,
                        text="variants/ folder (surviving files after discovery review)",
                        variable=self._export_src_var, value="variants/").pack(anchor="w", padx=6)
        ttk.Radiobutton(src_frame, text="ppsp_generate.csv (marked rows)",
                        variable=self._export_src_var,
                        value="ppsp_generate.csv").pack(anchor="w", padx=6)
        ttk.Radiobutton(src_frame, text="ppsp_stacks.csv (per-stack GenerateSpecs)",
                        variable=self._export_src_var,
                        value="ppsp_stacks.csv").pack(anchor="w", padx=6)

        opts = ttk.LabelFrame(frame, text="Output options")
        opts.pack(fill="x", padx=12, pady=4)

        ttk.Label(opts, text="Resolution (long side px, blank = full):").grid(
            row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(opts, textvariable=self._resolution_var, width=8).grid(
            row=0, column=1, sticky="w")

        ttk.Label(opts, text="JPEG quality:").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Spinbox(opts, from_=50, to=100, textvariable=self._quality_var,
                    width=5).grid(row=1, column=1, sticky="w")

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

        _shortcuts_label(frame, "Ctrl+E export")

    def _export(self) -> None:
        from tkinter import messagebox

        src = self._export_src_var.get()
        z_tier = self._gen_size_var.get()
        quality = self._quality_var.get()
        resolution_str = self._resolution_var.get().strip()
        resolution = int(resolution_str) if resolution_str.isdigit() else None

        if src == "session":
            active = self.session.active_chains()
            if not active:
                messagebox.showwarning("No session data",
                                       "No active chains in session. Run Discover first.")
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
        self._uncollapse_log()

        def _run():
            from .commands import cmd_generate
            try:
                cmd_generate(self.source, variants_arg=variants_arg, z_tier=z_tier,
                             quality=quality, resolution=resolution, redo=False)
                self._queue.put(("export_done", None))
            except Exception as exc:
                self._queue.put(("export_error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Tab 7 — Cleanup
    # ------------------------------------------------------------------

    def _build_cleanup_tab(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        frame = self._cleanup_frame
        tk.Label(frame,
                 text="Remove z-tier discovery folders and variants/ (destructive).",
                 font=("TkDefaultFont", 10), foreground="#a00").pack(pady=(16, 4))
        tk.Label(frame,
                 text="ppsp.log and ppsp_stacks.csv are kept. This cannot be undone.",
                 foreground="#555").pack(pady=(0, 12))

        self._cleanup_confirm_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="I understand this is a destructive operation",
                        variable=self._cleanup_confirm_var).pack()

        btn_row = ttk.Frame(frame)
        btn_row.pack(pady=8)
        self._cleanup_btn = ttk.Button(btn_row, text="▶  Run Cleanup",
                                       command=self._run_cleanup_cmd)
        self._cleanup_btn.pack(side="left")
        self._cleanup_progress = ttk.Progressbar(btn_row, mode="indeterminate", length=120)
        self._cleanup_progress.pack(side="left", padx=8)

        self._cleanup_status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self._cleanup_status, foreground="#444").pack()

    def _run_cleanup_cmd(self) -> None:
        from tkinter import messagebox
        if not self._cleanup_confirm_var.get():
            messagebox.showwarning("Confirm required",
                                   "Check the confirmation box first.")
            return
        self._cleanup_btn.state(["disabled"])
        self._cleanup_progress.start(10)
        self._cleanup_status.set("Running cleanup…")

        def _run():
            from .commands import cmd_cleanup
            try:
                cmd_cleanup(self.source)
                self._queue.put(("cleanup_done", None))
            except Exception as exc:
                self._queue.put(("cleanup_error", str(exc)))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Log panel (always visible at bottom, collapsible)
    # ------------------------------------------------------------------

    def _build_log_panel(self) -> None:
        """Populate self._log_frame (already placed in PanedWindow) with header + text widget."""
        import tkinter as tk
        from tkinter import ttk

        # Header row inside the log frame
        log_hdr = ttk.Frame(self._log_frame)
        log_hdr.pack(fill="x", pady=(2, 0))
        ttk.Label(log_hdr, text="Log  (ppsp.log)").pack(side="left", padx=4)
        self._log_toggle_btn = ttk.Button(log_hdr, text="▼ Collapse",
                                           command=self._toggle_log_panel, width=12)
        self._log_toggle_btn.pack(side="right", padx=2)

        self._log_text = tk.Text(self._log_frame, height=6, font=("mono", 8),
                                  state="disabled", wrap="none")
        log_vsb = ttk.Scrollbar(self._log_frame, orient="vertical",
                                  command=self._log_text.yview)
        log_hsb = ttk.Scrollbar(self._log_frame, orient="horizontal",
                                  command=self._log_text.xview)
        self._log_text.configure(yscrollcommand=log_vsb.set, xscrollcommand=log_hsb.set)
        log_vsb.pack(side="right", fill="y")
        log_hsb.pack(side="bottom", fill="x")
        self._log_text.pack(fill="both", expand=True)

    def _set_initial_sash(self) -> None:
        """Set the PanedWindow sash to ~80% of total height after the window is rendered."""
        if self._paned is None:
            return
        h = self._paned.winfo_height()  # type: ignore[union-attr]
        if h <= 1:
            self.root.after(100, self._set_initial_sash)
            return
        sash_y = int(h * 0.80)
        self._paned.sash_place(0, 0, sash_y)  # type: ignore[union-attr]

    def _toggle_log_panel(self) -> None:
        if self._paned is None:
            return
        if self._log_collapsed:
            # Restore to saved sash position
            sash_y = self._log_sash_pos or int(self._paned.winfo_height() * 0.80)  # type: ignore[union-attr]
            self._paned.sash_place(0, 0, sash_y)  # type: ignore[union-attr]
            self._log_collapsed = False
            if self._log_toggle_btn:
                self._log_toggle_btn.configure(text="▼ Collapse")
        else:
            # Save position and push sash to near-bottom to "collapse" the log
            self._log_sash_pos = self._paned.sash_coord(0)[1]  # type: ignore[union-attr]
            total_h = self._paned.winfo_height()  # type: ignore[union-attr]
            self._paned.sash_place(0, 0, total_h - 28)  # type: ignore[union-attr]
            self._log_collapsed = True
            if self._log_toggle_btn:
                self._log_toggle_btn.configure(text="▶ Expand")

    def _uncollapse_log(self) -> None:
        if self._log_collapsed:
            self._toggle_log_panel()
        if not self._log_tail_started:
            self._log_tail_started = True
            self._start_log_tail()

    def _start_log_tail(self) -> None:
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

        if log_path.exists():
            try:
                lines = log_path.read_text(encoding="utf-8", errors="replace")
                self._append_log(lines)
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
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def _bind_shortcuts(self) -> None:
        r = self.root
        r.bind("<Control-e>", lambda _e: self._export())
        r.bind("<Control-l>", lambda _e: self._toggle_log_panel())
        r.bind("<Left>", self._on_left_key)
        r.bind("<Right>", self._on_right_key)
        r.bind("<Up>", self._on_up_key)
        r.bind("<Down>", self._on_down_key)
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
        if tab == "Variants":
            self._navigate_stacks(-1)
        elif tab == "Select":
            self._navigate_tile_grid(-1, 0)
        return "break"

    def _on_right_key(self, _event=None) -> str:
        tab = self._active_tab()
        if tab == "Variants":
            self._navigate_stacks(1)
        elif tab == "Select":
            self._navigate_tile_grid(1, 0)
        return "break"

    def _on_up_key(self, _event=None) -> Optional[str]:
        if self._active_tab() == "Select":
            self._navigate_tile_grid(0, -1)
            return "break"
        return None

    def _on_down_key(self, _event=None) -> Optional[str]:
        if self._active_tab() == "Select":
            self._navigate_tile_grid(0, 1)
            return "break"
        return None

    def _on_enter_key(self, _event=None) -> None:
        tab = self._active_tab()
        if tab == "Variants":
            self._toggle_focused_stack()

    def _on_tab_key(self, _event=None) -> Optional[str]:
        if self._active_tab() == "Select":
            self._discover_next_step()
            return "break"
        return None

    def _on_d_key(self, _event=None) -> None:
        if self._active_tab() == "Select":
            self._discard_focused()

    def _on_r_key(self, _event=None) -> None:
        if self._active_tab() == "Select":
            self._reactivate_focused()

    def _on_f_key(self, _event=None) -> None:
        if self._active_tab() == "Select" and self._focused_chain:
            self._open_fullscreen(self._focused_chain)

    def _on_space_key(self, _event=None) -> Optional[str]:
        tab = self._active_tab()
        if tab == "Select" and self._focused_chain:
            self._toggle_tile_select()
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
                elif msg == "rename_done":
                    self._rename_progress.stop()
                    self._rename_btn.state(["!disabled"])
                    self._rename_status.set("Rename complete.")
                    self._load_stacks()
                elif msg == "rename_error":
                    self._rename_progress.stop()
                    self._rename_btn.state(["!disabled"])
                    self._rename_status.set(f"Error: {data}")
                elif msg == "organize_done":
                    self._organize_progress.stop()
                    self._organize_btn.state(["!disabled"])
                    self._organize_status.set("Organize complete.")
                    self._load_stacks()
                elif msg == "organize_error":
                    self._organize_progress.stop()
                    self._organize_btn.state(["!disabled"])
                    self._organize_status.set(f"Error: {data}")
                elif msg == "cleanup_done":
                    self._cleanup_progress.stop()
                    self._cleanup_btn.state(["!disabled"])
                    self._cleanup_status.set("Cleanup complete.")
                    self._cleanup_confirm_var.set(False)
                elif msg == "cleanup_error":
                    self._cleanup_progress.stop()
                    self._cleanup_btn.state(["!disabled"])
                    self._cleanup_status.set(f"Error: {data}")
                elif msg == "log_line":
                    self._append_log(str(data))
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _set_status(self, msg: str) -> None:
        self._progress_text.set(msg)

    def run(self) -> None:
        self.root.mainloop()


def launch(source: Optional[Path] = None) -> None:
    """Entry point for ppsp --gui."""
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
