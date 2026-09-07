#!/usr/bin/env python3
"""
spec_viewer.py — Interactive viewer for .spec spectrometer files.

Scans a folder for .spec files and lets you browse through them one by one,
plotting the (mean) spectrum of each file together with its filename and
basic header metadata. Designed to stay responsive even in directories
containing thousands of .spec files: files are listed via a single lazy
glob (no bulk reading), and spectra are loaded on demand with a small
LRU cache so that repeated Prev/Next navigation near the current position
does not re-read disk every time.

Usage:
    python3 spec_viewer.py                     # opens a folder-picker dialog
    python3 spec_viewer.py /path/to/measdir     # scans the given directory
    python3 spec_viewer.py /path/to/measdir --x-axis bins
    python3 spec_viewer.py /path/to/measdir --start 42
    python3 spec_viewer.py /path/to/measdir --recursive


    - Press "r" to reload the file list from disk (e.g. if new files
      appeared while the viewer is open).
"""

from __future__ import annotations

import argparse
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Button, TextBox

import spec_analysis_utils as sau


_NUM_RE = re.compile(r"(\d+)")


def _natural_sort_key(path: Path) -> Tuple:
    """Sort filenames so embedded numbers (e.g. timestamps) order correctly."""
    parts = _NUM_RE.split(path.name)
    return tuple(int(p) if p.isdigit() else p for p in parts)


def scan_spec_files(directory: Path, recursive: bool = False) -> List[Path]:
    """Return a sorted list of .spec files in `directory` without reading them."""
    pattern = "**/*.spec" if recursive else "*.spec"
    files = list(directory.glob(pattern))
    files.sort(key=_natural_sort_key)
    return files


class SpecViewer:
    """Interactive, lazy-loading browser for a list of .spec files."""

    def __init__(self, spec_files: List[Path], x_axis_mode: str = "frequency",
                 header_meta: Optional[dict] = None, cache_size: int = 64):
        if not spec_files:
            raise ValueError("No .spec files provided to SpecViewer.")
        self.spec_files = spec_files
        self.x_axis_mode = x_axis_mode
        self.header_meta = header_meta or {}
        self.index = 0

        # Bounded LRU cache for loaded (mean) spectra, keyed by absolute path.
        self._load_mean_cached = lru_cache(maxsize=cache_size)(self._load_mean_uncached)

        self.fig, self.ax = plt.subplots(figsize=(11, 6))
        self.fig.subplots_adjust(bottom=0.22)
        (self.line,) = self.ax.plot([], [], color="tab:blue", linewidth=1.0)
        self.ax.set_ylabel("Mean counts$^2$ [arb.]")
        self.ax.grid(True, alpha=0.3)

        self._build_widgets()
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.draw()

    # ---- data loading -------------------------------------------------
    def _load_mean_uncached(self, path_str: str):
        path = Path(path_str)
        _, spectra, meta = sau.load_spec_file(path)
        mean_spec = (spectra.astype(float) ** 2).mean(axis=0)
        return mean_spec, meta

    def load_current(self):
        path = self.spec_files[self.index]
        try:
            mean_spec, meta = self._load_mean_cached(str(path))
            return mean_spec, meta, None
        except Exception as exc:  # corrupt/unreadable file: report, don't crash
            return None, None, str(exc)

    # ---- widgets --------------------------------------------------------
    def _build_widgets(self):
        ax_first = self.fig.add_axes([0.10, 0.05, 0.08, 0.06])
        ax_prev = self.fig.add_axes([0.19, 0.05, 0.12, 0.06])
        ax_next = self.fig.add_axes([0.32, 0.05, 0.12, 0.06])
        ax_last = self.fig.add_axes([0.45, 0.05, 0.08, 0.06])
        ax_goto_label_box = self.fig.add_axes([0.66, 0.05, 0.12, 0.06])

        self.btn_first = Button(ax_first, "|<")
        self.btn_prev = Button(ax_prev, "Previous")
        self.btn_next = Button(ax_next, "Next")
        self.btn_last = Button(ax_last, ">|")
        self.box_goto = TextBox(ax_goto_label_box, "Go to # ", initial="")

        self.btn_first.on_clicked(lambda _e: self.jump(0))
        self.btn_prev.on_clicked(lambda _e: self.step(-1))
        self.btn_next.on_clicked(lambda _e: self.step(1))
        self.btn_last.on_clicked(lambda _e: self.jump(len(self.spec_files) - 1))
        self.box_goto.on_submit(self._on_goto_submit)

    def _on_goto_submit(self, text: str):
        text = text.strip()
        if not text:
            return
        try:
            target = int(text) - 1  # 1-based input for user friendliness
        except ValueError:
            return
        self.jump(target)

    # ---- navigation -----------------------------------------------------
    def step(self, delta: int):
        self.jump((self.index + delta) % len(self.spec_files))

    def jump(self, target: int):
        target = max(0, min(len(self.spec_files) - 1, target))
        if target != self.index:
            self.index = target
        self.draw()

    def reload_file_list(self, directory: Path, recursive: bool):
        current_path = self.spec_files[self.index]
        new_files = scan_spec_files(directory, recursive=recursive)
        if not new_files:
            print("Reload found no .spec files; keeping previous list.")
            return
        self.spec_files = new_files
        try:
            self.index = self.spec_files.index(current_path)
        except ValueError:
            self.index = min(self.index, len(self.spec_files) - 1)
        self._load_mean_cached.cache_clear()
        self.draw()
        print(f"Reloaded: {len(self.spec_files)} .spec files found.")

    def _on_key(self, event):
        if event.key in ("left", "up"):
            self.step(-1)
        elif event.key in ("right", "down"):
            self.step(1)
        elif event.key == "home":
            self.jump(0)
        elif event.key == "end":
            self.jump(len(self.spec_files) - 1)

    # ---- drawing ----------------------------------------------------------
    def draw(self):
        path = self.spec_files[self.index]
        mean_spec, meta, error = self.load_current()
        total = len(self.spec_files)
        pos = self.index + 1

        if error is not None:
            self.line.set_data([], [])
            self.ax.set_title(f"[{pos}/{total}] {path.name} — ERROR: {error}", color="tab:red")
            self.ax.set_xlabel("")
            self.fig.canvas.draw_idle()
            return

        x, x_label = sau.build_x_axis(mean_spec.size, self.header_meta, self.x_axis_mode)
        self.line.set_data(x, mean_spec)
        if x.size > 1:
            self.ax.set_xlim(float(x[0]), float(x[-1]))
        self.ax.relim()
        self.ax.autoscale_view(scalex=False, scaley=True)
        sau._apply_x_axis_format(self.ax, self.header_meta, self.x_axis_mode, x_label)

        n_spectra = meta.get("n_spectra") if meta else None
        int_time = meta.get("int_time_ms") if meta else None
        bw = meta.get("bandwidth") if meta else None
        info_bits = []
        if n_spectra is not None:
            info_bits.append(f"n_spectra={n_spectra}")
        if int_time is not None:
            info_bits.append(f"int_time={int_time} ms")
        if bw is not None:
            info_bits.append(f"bandwidth={bw}")
        info_str = (" | " + ", ".join(info_bits)) if info_bits else ""

        self.ax.set_title(f"[{pos}/{total}] {path.name}{info_str}")
        self.fig.canvas.draw_idle()

    def show(self):
        plt.show()


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Interactively browse .spec spectrometer files.")
    parser.add_argument("directory", nargs="?", default=None,
                         help="Folder containing .spec files. If omitted, a folder-picker dialog opens.")
    parser.add_argument("--x-axis", dest="x_axis", choices=["frequency", "bins", "sidebands"],
                         default="frequency", help="X-axis mode (default: frequency).")
    parser.add_argument("--recursive", action="store_true",
                         help="Also search .spec files in subdirectories.")
    parser.add_argument("--start", type=int, default=1,
                         help="1-based index of the file to display first (default: 1).")
    parser.add_argument("--cache-size", type=int, default=64,
                         help="Number of recently viewed spectra kept in memory (default: 64).")
    args = parser.parse_args(argv)

    if args.directory is None:
        chosen = sau.choose_directory(Path.cwd())
        if chosen is None:
            print("No directory selected. Exiting.")
            return
        meas_dir = chosen
    else:
        meas_dir = Path(args.directory).expanduser().resolve()

    if not meas_dir.is_dir():
        print(f"Not a directory: {meas_dir}")
        return

    meas_dir = sau._resolve_measurement_dir_with_specs(meas_dir)
    spec_files = scan_spec_files(meas_dir, recursive=args.recursive)
    if not spec_files:
        print(f"No .spec files found in {meas_dir}" + (" (recursively)" if args.recursive else ""))
        return

    print(f"Found {len(spec_files)} .spec files in {meas_dir}.")
    header_meta = sau.parse_header_csv(meas_dir)

    viewer = SpecViewer(spec_files, x_axis_mode=args.x_axis, header_meta=header_meta,
                         cache_size=max(4, args.cache_size))
    start_idx = max(0, min(len(spec_files) - 1, args.start - 1))
    viewer.jump(start_idx)

    def _reload_on_r(event):
        if event.key == "r":
            viewer.reload_file_list(meas_dir, recursive=args.recursive)

    viewer.fig.canvas.mpl_connect("key_press_event", _reload_on_r)
    viewer.show()


if __name__ == "__main__":
    main()
