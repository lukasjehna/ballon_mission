#!/usr/bin/env python3
"""Interactive Y-factor noise-temperature browser for paired hot/cold .spec files.

This version supports averaging over a user-defined number of pairs and
spectral binning of the x-axis via spec_analysis_utils.spectral_bin_average().

Examples
--------
python3 noise_temperature_folder_viewer.py /data/run
python3 noise_temperature_folder_viewer.py /data/run --thot 295 --tcold 77
python3 noise_temperature_folder_viewer.py /data/run --pair-tolerance 60 --x-axis bins
python3 noise_temperature_folder_viewer.py /data/run --pairs-per-average 4 --x-bin-size 8

Files are recognised case-insensitively when their stem ends in ``hot`` or
``cold``. Each hot file is paired with the closest unused cold file in time;
the timestamp must occur at the beginning of the filename as YYYYMMDDHHMMSS,
e.g. 20260713160551hot.spec and 20260713160605cold.spec.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, TextBox

import spec_analysis_utils as sau

STAMP_RE = re.compile(r"^(\d{14})")
LOAD_RE = re.compile(r"(hot|cold)$", re.IGNORECASE)


def parse_file(path: Path) -> Optional[tuple[datetime, str, Path]]:
    match = STAMP_RE.match(path.stem)
    load = LOAD_RE.search(path.stem)
    if match is None or load is None:
        return None
    try:
        stamp = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return stamp, load.group(1).lower(), path


def find_pairs(directory: Path, recursive: bool, tolerance_s: float) -> list[tuple[Path, Path, float]]:
    pattern = "**/*.spec" if recursive else "*.spec"
    parsed = [item for p in directory.glob(pattern) if (item := parse_file(p))]
    hot = sorted((x for x in parsed if x[1] == "hot"), key=lambda x: x[0])
    cold = sorted((x for x in parsed if x[1] == "cold"), key=lambda x: x[0])
    unused = set(range(len(cold)))
    pairs = []
    for hot_time, _, hot_path in hot:
        candidates = [(abs((cold[i][0] - hot_time).total_seconds()), i) for i in unused]
        if not candidates:
            break
        delta_s, index = min(candidates)
        if delta_s <= tolerance_s:
            unused.remove(index)
            pairs.append((hot_path, cold[index][2], delta_s))
    return pairs


class NoiseTemperatureViewer:
    def __init__(self, pairs, header_meta, thot, tcold, x_axis, cache_size, pairs_per_average, x_bin_size):
        if not pairs:
            raise ValueError("No valid hot/cold pairs.")
        self.pairs = pairs
        self.header_meta = header_meta
        self.thot = thot
        self.tcold = tcold
        self.x_axis = x_axis
        self.pairs_per_average = max(1, int(pairs_per_average))
        self.x_bin_size = max(1, int(x_bin_size))
        self.xmin = 0.24
        self.xmax = 0.3
        self.y1min = 2000
        self.y1max = 10000
        self.y2min = 1e8
        self.y2max = 1e9
        self.y3min = 0.95
        self.y3max = 1.05
        self.index = 0
        self._load_cached = lru_cache(maxsize=cache_size)(self._load_uncached)

        self.fig, self.axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
        self.fig.subplots_adjust(bottom=0.20, hspace=0.28)
        self.ax_nt, self.ax_hotcold, self.ax_diff = self.axes
        self.line_nt, = self.ax_nt.plot([], [], color="tab:green", lw=1.0)
        self.line_hot, = self.ax_hotcold.plot([], [], color="tab:red", lw=1.0, label="Hot")
        self.line_cold, = self.ax_hotcold.plot([], [], color="tab:blue", lw=1.0, label="Cold")
        self.y_factor, = self.ax_diff.plot([], [], color="tab:purple", lw=1.0)
        self.ax_nt.set_ylabel("Noise temperature [K]")
        self.ax_hotcold.set_ylabel("Counts [arb.]")
        self.ax_diff.set_ylabel("y-factor")
        self.ax_diff.set_xlabel("Bin index")
        for ax in self.axes:
            ax.grid(True, alpha=0.3)
        self.ax_hotcold.legend(loc="best")
        self._widgets()
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.draw()

    def _load_uncached(self, hot_name, cold_name):
        hot = sau.file_mean_spectrum(Path(hot_name))
        cold = sau.file_mean_spectrum(Path(cold_name))
        if hot.size != cold.size:
            raise ValueError(f"Bin-count mismatch: hot={hot.size}, cold={cold.size}")
        tnoise = sau.compute_noise_temperature(hot, cold, self.thot, self.tcold)
        return hot, cold, tnoise

    def _widgets(self):
        positions = ([0.10, 0.05, 0.08, 0.06], [0.19, 0.05, 0.12, 0.06],
                     [0.32, 0.05, 0.12, 0.06], [0.45, 0.05, 0.08, 0.06])
        self.first, self.prev, self.next, self.last = [Button(self.fig.add_axes(p), label)
                                                       for p, label in zip(positions, ("|<", "Previous", "Next", ">|"))]
        self.goto = TextBox(self.fig.add_axes([0.66, 0.05, 0.12, 0.06]), "Go to # ")
        self.first.on_clicked(lambda _e: self.jump(0))
        self.prev.on_clicked(lambda _e: self.step(-1))
        self.next.on_clicked(lambda _e: self.step(1))
        self.last.on_clicked(lambda _e: self.jump(len(self.pairs) - 1))
        self.goto.on_submit(self._goto)

    def _goto(self, text):
        try:
            self.jump(int(text.strip()) - 1)
        except ValueError:
            pass

    def step(self, amount):
        self.jump((self.index + amount) % len(self.pairs))

    def jump(self, index):
        self.index = max(0, min(len(self.pairs) - 1, index))
        self.draw()

    def _on_key(self, event):
        if event.key in ("left", "up"):
            self.step(-1)
        elif event.key in ("right", "down"):
            self.step(1)
        elif event.key == "home":
            self.jump(0)
        elif event.key == "end":
            self.jump(len(self.pairs) - 1)

    def _average_window(self, start_index: int) -> tuple[list[tuple[Path, Path, float]], np.ndarray, np.ndarray, np.ndarray]:
        group = self.pairs[start_index:start_index + self.pairs_per_average]
        hot_sum = None
        cold_sum = None
        noise_sum = None
        count = 0
        for hot, cold, _sep in group:
            hot_arr, cold_arr, tnoise = self._load_cached(str(hot), str(cold))
            if hot_sum is None:
                hot_sum = np.zeros_like(hot_arr, dtype=float)
                cold_sum = np.zeros_like(cold_arr, dtype=float)
                noise_sum = np.zeros_like(tnoise, dtype=float)
            if hot_arr.size != hot_sum.size or cold_arr.size != cold_sum.size:
                raise ValueError("Bin-count mismatch within averaging window.")
            hot_sum += hot_arr
            cold_sum += cold_arr
            noise_sum += tnoise
            count += 1
        if count == 0:
            raise ValueError("No pairs to average.")
        return group, hot_sum / count, cold_sum / count, noise_sum / count

    def draw(self):
        try:
            group, hot_arr, cold_arr, tnoise = self._average_window(self.index)
            separation = float(np.mean([sep for _h, _c, sep in group]))
            x, xlabel = sau.build_x_axis(tnoise.size, self.header_meta, self.x_axis, bin_size=self.x_bin_size)
            if self.x_bin_size > 1:
                hot_arr, _ = sau.spectral_bin_average(np.arange(hot_arr.size, dtype=float),self.x_bin_size)
                cold_arr, _ = sau.spectral_bin_average(np.arange(cold_arr.size, dtype=float), self.x_bin_size)
                tnoise, _ = sau.spectral_bin_average(np.arange(tnoise.size, dtype=float), self.x_bin_size)
            self.line_nt.set_data(x, tnoise)
            self.line_hot.set_data(x, hot_arr)
            self.line_cold.set_data(x, cold_arr)
            self.y_factor.set_data(x, hot_arr / np.maximum(cold_arr, np.finfo(float).eps))

            for ax in self.axes:
                if self.xmin is not None and self.xmax is not None:
                    ax.set_xlim(self.xmin, self.xmax)
                elif x.size > 1:
                    ax.set_xlim(float(x[0]), float(x[-1]))

            if self.y1min is not None and self.y1max is not None:
                self.ax_nt.set_ylim(self.y1min, self.y1max)
            if self.y2min is not None and self.y2max is not None:
                self.ax_hotcold.set_ylim(self.y2min, self.y2max)
            if self.y3min is not None and self.y3max is not None:
                self.ax_diff.set_ylim(self.y3min, self.y3max)

            sau._apply_x_axis_format(self.ax_diff, self.header_meta, self.x_axis, xlabel)
            self.ax_nt.set_title(
                f"[{self.index + 1}/{len(self.pairs)}] averaging {len(group)} pair(s) starting at "
                f"{group[0][0].name} | mean Δt={separation:.1f} s | "
                f"T_hot={self.thot:.2f} K | T_cold={self.tcold:.2f} K | x-bin={self.x_bin_size}"
            )
        except Exception as exc:
            self.line_nt.set_data([], [])
            self.line_hot.set_data([], [])
            self.line_cold.set_data([], [])
            self.y_factor.set_data([], [])
            self.ax_nt.set_title(f"[{self.index + 1}/{len(self.pairs)}] ERROR: {exc}", color="tab:red")
        finally:
            self.fig.canvas.draw_idle()


def main():
    parser = argparse.ArgumentParser(description="Browse Y-factor noise temperatures from hot/cold .spec pairs.")
    parser.add_argument("directory", nargs="?", help="Measurement folder; omit to choose it graphically.")
    parser.add_argument("--thot", type=float, default=320.0, help="Hot-load temperature in K (default: 320).")
    parser.add_argument("--tcold", type=float, default=230.0, help="Cold-load temperature in K (default: 230).")
    parser.add_argument("--pair-tolerance", type=float, default=60.0, help="Maximum hot/cold time separation in s (default: 60).")
    parser.add_argument("--x-axis", choices=("frequency", "bins", "sidebands"), default="frequency")
    parser.add_argument("--recursive", action="store_true", help="Search subdirectories too.")
    parser.add_argument("--cache-size", type=int, default=32)
    parser.add_argument("--pairs-per-average", type=int, default=1,
                        help="Average over this many consecutive hot/cold pairs before plotting (default: 1).")
    parser.add_argument("--x-bin-size", type=int, default=1,
                        help="Average over this many spectral points on the x-axis (default: 1).")
    args = parser.parse_args()

    directory = sau.choose_directory(Path.cwd()) if args.directory is None else Path(args.directory).expanduser().resolve()
    if directory is None:
        return
    if not directory.is_dir():
        parser.error(f"Not a directory: {directory}")

    pairs = find_pairs(directory, args.recursive, args.pair_tolerance)
    if not pairs:
        parser.error("No timestamped hot/cold pairs found within the requested tolerance.")

    print(f"Found {len(pairs)} hot/cold pairs in {directory}")
    if args.pairs_per_average > 1:
        print(f"Averaging over {args.pairs_per_average} pair(s) per view.")
    if args.x_bin_size > 1:
        print(f"Applying spectral binning with x-bin size {args.x_bin_size}.")

    viewer = NoiseTemperatureViewer(
        pairs,
        sau.parse_header_csv(directory),
        args.thot,
        args.tcold,
        args.x_axis,
        max(4, args.cache_size),
        args.pairs_per_average,
        args.x_bin_size,
    )
    plt.show()


if __name__ == "__main__":
    main()
