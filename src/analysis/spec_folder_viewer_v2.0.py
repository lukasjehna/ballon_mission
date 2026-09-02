#!/usr/bin/env python3
#move toggle log into the spectrometer_analysis_utils.py file and import it into this file

from __future__ import annotations
import argparse
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, TextBox, CheckButton

import spec_analysis_utils as sau

NUM_RE = re.compile(r"(\d+)")


def natural_sort_key(path: Path) -> Tuple:
    parts = NUM_RE.split(path.name)
    return tuple(int(p) if p.isdigit() else p.lower() for p in parts)


def scan_spec_files(directory: Path, recursive: bool = False) -> List[Path]:
    pattern = "**/*.spec" if recursive else "*.spec"
    files = list(directory.glob(pattern))
    files.sort(key=natural_sort_key)
    return files


class SpecViewer:
    def __init__(
        self,
        spec_files: List[Path],
        x_axis_mode: str = "frequency",
        headermeta: Optional[dict] = None,
        cache_size: int = 64,
    ):
        if not spec_files:
            raise ValueError("No .spec files provided to SpecViewer.")

        self.spec_files = spec_files
        self.x_axis_mode = x_axis_mode
        self.headermeta = headermeta or {}
        self.index = 0
        self.load_cached = lru_cache(maxsize=cache_size)(self.load_uncached)

        self.fig, (self.ax_all, self.ax_stats) = plt.subplots(2, 1, figsize=(12, 8), sharex=False)
        self.fig.subplots_adjust(bottom=0.28, hspace=0.35)

        self.all_line = None
        self.mean_line = None
        self.std_upper_line = None
        self.std_lower_line = None
        self.fill_between = None

        self.ax_all.grid(True, alpha=0.3, which="both")
        self.ax_stats.grid(True, alpha=0.3, which="both")
        self.ax_all.set_ylabel("Counts")
        self.ax_stats.set_ylabel("Counts")
        self.ax_stats.set_xlabel("Frequency / bin")

        self.y_log = False

        self.build_widgets()
        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.draw()

    def load_uncached(self, path_str: str):
        path = Path(path_str)
        spectra_data = sau.load_spec_file(path)
        return spectra_data

    def load_current(self):
        path = self.spec_files[self.index]
        try:
            return self.load_cached(str(path)), None
        except Exception as exc:
            return None, str(exc)

    def build_widgets(self) -> None:
        ax_first = self.fig.add_axes([0.06, 0.05, 0.08, 0.06])
        ax_prev = self.fig.add_axes([0.15, 0.05, 0.10, 0.06])
        ax_next = self.fig.add_axes([0.26, 0.05, 0.10, 0.06])
        ax_last = self.fig.add_axes([0.37, 0.05, 0.08, 0.06])
        ax_goto = self.fig.add_axes([0.58, 0.05, 0.12, 0.06])
        ax_log = self.fig.add_axes([0.78, 0.05, 0.12, 0.06])

        self.btn_first = Button(ax_first, "First")
        self.btn_prev = Button(ax_prev, "Previous")
        self.btn_next = Button(ax_next, "Next")
        self.btn_last = Button(ax_last, "Last")
        self.box_goto = TextBox(ax_goto, "Go to ", initial="1")
        self.check_log = CheckButton(ax_log, "Log Y", useblit=False)

        self.btn_first.on_clicked(lambda _event: self.jump(0))
        self.btn_prev.on_clicked(lambda _event: self.step(-1))
        self.btn_next.on_clicked(lambda _event: self.step(1))
        self.btn_last.on_clicked(lambda _event: self.jump(len(self.spec_files) - 1))
        self.box_goto.on_submit(self.on_goto_submit)
        self.check_log.on_clicked(self.toggle_log_y)

    def toggle_log_y(self, _value) -> None:
        self.y_log = not self.y_log
        self.ax_all.set_yscale("log" if self.y_log else "linear")
        self.ax_stats.set_yscale("log" if self.y_log else "linear")
        self.draw()

    def on_goto_submit(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        try:
            self.jump(int(text) - 1)
        except ValueError:
            return

    def step(self, delta: int) -> None:
        self.jump(self.index + delta)

    def jump(self, target: int) -> None:
        target = max(0, min(len(self.spec_files) - 1, target))
        if target != self.index:
            self.index = target
            self.draw()

    def on_key(self, event) -> None:
        if event.key in ("left", "up"):
            self.step(-1)
        elif event.key in ("right", "down"):
            self.step(1)
        elif event.key == "home":
            self.jump(0)
        elif event.key == "end":
            self.jump(len(self.spec_files) - 1)
        elif event.key == "l":
            self.toggle_log_y(None)

    def _clear_axes(self) -> None:
        self.ax_all.cla()
        self.ax_stats.cla()
        self.ax_all.grid(True, alpha=0.3, which="both")
        self.ax_stats.grid(True, alpha=0.3, which="both")
        self.ax_all.set_ylabel("Counts")
        self.ax_stats.set_ylabel("Counts")
        self.ax_stats.set_xlabel("Frequency / bin")

        self.ax_all.set_yscale("log" if self.y_log else "linear")
        self.ax_stats.set_yscale("log" if self.y_log else "linear")

    def draw(self) -> None:
        path = self.spec_files[self.index]
        loaded, error = self.load_current()
        total = len(self.spec_files)
        pos = self.index + 1

        self._clear_axes()

        if error is not None or loaded is None:
            self.ax_all.set_title(f"{pos}/{total}  {path.name}  ERROR: {error}", color="tab:red")
            self.ax_stats.set_title("Failed to load file")
            self.fig.canvas.draw_idle()
            return

        times, spectra, meta = loaded
        x, xlabel = sau._build_x_axis(spectra.shape[1], meta, self.x_axis_mode)

        for spectrum in spectra:
            self.ax_all.plot(x, spectrum, color="tab:blue", alpha=0.12, linewidth=0.8)
        self.ax_all.set_title(f"{pos}/{total}  {path.name}")
        self.ax_all.set_xlabel(xlabel)
        self.ax_all.set_ylabel("Counts")

        mean_spec = np.mean(spectra.astype(float), axis=0)
        std_spec = np.std(spectra.astype(float), axis=0)
        lower = mean_spec - std_spec
        upper = mean_spec + std_spec

        self.mean_line, = self.ax_stats.plot(x, mean_spec, color="tab:blue", linewidth=1.5, label="Mean")
        self.std_upper_line, = self.ax_stats.plot(x, upper, color="tab:orange", linewidth=1.0, linestyle="--", label="Mean + 1 std")
        self.std_lower_line, = self.ax_stats.plot(x, lower, color="tab:orange", linewidth=1.0, linestyle="--", label="Mean - 1 std")
        self.fill_between = self.ax_stats.fill_between(x, lower, upper, color="tab:orange", alpha=0.2)

        self.ax_stats.set_title("Mean and standard deviation")
        self.ax_stats.set_xlabel(xlabel)
        self.ax_stats.set_ylabel("Counts")
        self.ax_stats.legend(loc="best")

        nspectra = meta.get("n_spectra") if isinstance(meta, dict) else None
        inttime = meta.get("inttimems") if isinstance(meta, dict) else None
        bandwidth = meta.get("bandwidth") if isinstance(meta, dict) else None
        info_bits = []
        if nspectra is not None:
            info_bits.append(f"N={nspectra}")
        if inttime is not None:
            info_bits.append(f"t={inttime} ms")
        if bandwidth is not None:
            info_bits.append(f"BW={bandwidth}")
        if info_bits:
            self.ax_stats.text(
                0.01,
                0.98,
                ", ".join(info_bits),
                transform=self.ax_stats.transAxes,
                va="top",
                ha="left",
                fontsize=9,
                bbox=dict(facecolor="white", alpha=0.75, edgecolor="none"),
            )

        self.fig.canvas.draw_idle()

    def show(self) -> None:
        plt.show()


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Interactively browse .spec spectrometer files with two subplots.")
    parser.add_argument("directory", nargs="?", default=None, help="Folder containing .spec files. If omitted, a folder-picker dialog opens.")
    parser.add_argument("--x-axis", dest="xaxis", choices=["frequency", "bins", "sidebands"], default="frequency")
    parser.add_argument("--recursive", action="store_true", help="Also search .spec files in subdirectories.")
    parser.add_argument("--start", type=int, default=1, help="1-based index of the file to display first.")
    parser.add_argument("--cache-size", type=int, default=64, help="Number of recently viewed files kept in memory.")
    args = parser.parse_args(argv)

    if args.directory is None:
        chosen = sau.choose_directory(Path.cwd())
        if chosen is None:
            print("No directory selected. Exiting.")
            return
        measdir = chosen
    else:
        measdir = Path(args.directory).expanduser().resolve()

    if not measdir.is_dir():
        print(f"Not a directory: {measdir}")
        return

    spec_files = scan_spec_files(measdir, recursive=args.recursive)
    if not spec_files:
        print(f"No .spec files found in {measdir}")
        return

    headermeta = sau.parse_header_csv(measdir)
    viewer = SpecViewer(spec_files, x_axis_mode=args.xaxis, headermeta=headermeta, cache_size=max(4, args.cache_size))
    viewer.jump(max(0, min(len(spec_files) - 1, args.start - 1)))
    viewer.show()


if __name__ == "__main__":
    main(sys.argv[1:])