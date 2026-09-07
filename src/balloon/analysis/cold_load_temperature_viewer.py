#!/usr/bin/env python3
"""Interactive cold-load temperature browser for paired hot/cold .spec files.

The program accepts the receiver noise temperature and hot-load temperature,
then calculates and plots the cold-load temperature for each spectrum pair.

Expected filenames start with YYYYMMDDHHMMSS and end in ``hot`` or ``cold``,
for example ``20260713160551hot.spec`` and ``20260713160605cold.spec``.
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
    """Return timestamp, load type, and path for a recognised spectrum file."""
    match = STAMP_RE.match(path.stem)
    load = LOAD_RE.search(path.stem)
    if match is None or load is None:
        return None
    try:
        stamp = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return stamp, load.group(1).lower(), path


def find_pairs(
    directory: Path, recursive: bool, tolerance_s: float
) -> list[tuple[Path, Path, float]]:
    """Pair each hot file with the closest unused cold file."""
    pattern = "**/*.spec" if recursive else "*.spec"
    parsed = [item for p in directory.glob(pattern) if (item := parse_file(p))]
    hot = sorted((x for x in parsed if x[1] == "hot"), key=lambda x: x[0])
    cold = sorted((x for x in parsed if x[1] == "cold"), key=lambda x: x[0])

    unused = set(range(len(cold)))
    pairs = []
    for hot_time, _, hot_path in hot:
        candidates = [
            (abs((cold[i][0] - hot_time).total_seconds()), i) for i in unused
        ]
        if not candidates:
            break
        separation_s, index = min(candidates)
        if separation_s > tolerance_s:
            continue
        unused.remove(index)
        pairs.append((hot_path, cold[index][2], separation_s))
    return pairs


def compute_cold_temperature(
    hot_spectrum: np.ndarray,
    cold_spectrum: np.ndarray,
    noise_temperature: float,
    hot_temperature: float,
) -> np.ndarray:
    """Calculate cold-load temperature from hot/cold spectra.

    With receiver output P = G (T_load + T_noise),

        T_cold = (P_cold / P_hot) * (T_hot + T_noise) - T_noise.
    """
    if hot_spectrum.size != cold_spectrum.size:
        raise ValueError(
            f"Bin-count mismatch: hot={hot_spectrum.size}, cold={cold_spectrum.size}"
        )
    if noise_temperature < 0:
        raise ValueError("Noise temperature must be non-negative.")
    if hot_temperature <= 0:
        raise ValueError("Hot temperature must be greater than zero.")

    with np.errstate(divide="ignore", invalid="ignore"):
        return (
            cold_spectrum / hot_spectrum * (hot_temperature + noise_temperature)
            - noise_temperature
        )


class ColdLoadTemperatureViewer:
    def __init__(
        self,
        pairs,
        header_meta,
        noise_temperature,
        hot_temperature,
        x_axis,
        cache_size,
    ):
        if not pairs:
            raise ValueError("No valid hot/cold pairs.")
        self.pairs = pairs
        self.header_meta = header_meta
        self.noise_temperature = noise_temperature
        self.hot_temperature = hot_temperature
        self.x_axis = x_axis
        self.index = 0
        self._load_cached = lru_cache(maxsize=cache_size)(self._load_uncached)

        self.fig, self.ax = plt.subplots(figsize=(11, 6))
        self.fig.subplots_adjust(bottom=0.22)
        (self.line,) = self.ax.plot([], [], color="tab:blue", lw=1.0)
        self.ax.set_ylabel("Cold-load temperature [K]")
        self.ax.grid(True, alpha=0.3)
        self._widgets()
        self.fig.canvas.mpl_connect("key_press_event", self._on_key)
        self.draw()

    def _load_uncached(self, hot_name, cold_name):
        hot = sau.file_mean_spectrum(Path(hot_name))
        cold = sau.file_mean_spectrum(Path(cold_name))
        return compute_cold_temperature(
            hot, cold, self.noise_temperature, self.hot_temperature
        )

    def _widgets(self):
        positions = (
            [0.10, 0.05, 0.08, 0.06],
            [0.19, 0.05, 0.12, 0.06],
            [0.32, 0.05, 0.12, 0.06],
            [0.45, 0.05, 0.08, 0.06],
        )
        labels = ("|<", "Previous", "Next", ">|")
        self.first, self.prev, self.next, self.last = [
            Button(self.fig.add_axes(position), label)
            for position, label in zip(positions, labels)
        ]
        self.goto = TextBox(self.fig.add_axes([0.66, 0.05, 0.12, 0.06]), "Go to # ")
        self.first.on_clicked(lambda _event: self.jump(0))
        self.prev.on_clicked(lambda _event: self.step(-1))
        self.next.on_clicked(lambda _event: self.step(1))
        self.last.on_clicked(lambda _event: self.jump(len(self.pairs) - 1))
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

    def draw(self):
        hot, cold, separation = self.pairs[self.index]
        try:
            tcold = self._load_cached(str(hot), str(cold))
            x, xlabel = sau.build_x_axis(tcold.size, self.header_meta, self.x_axis)
            self.line.set_data(x, tcold)
            if x.size > 1:
                self.ax.set_xlim(float(x[0]), float(x[-1]))
            self.ax.relim()
            self.ax.autoscale_view(scalex=False, scaley=True)
            sau._apply_x_axis_format(self.ax, self.header_meta, self.x_axis, xlabel)

            finite = tcold[np.isfinite(tcold)]
            median = np.median(finite) if finite.size else float("nan")
            self.ax.set_title(
                f"[{self.index + 1}/{len(self.pairs)}] hot: {hot.name} | cold: {cold.name}\n"
                f"Δt={separation:.1f} s | T_noise={self.noise_temperature:.2f} K | "
                f"T_hot={self.hot_temperature:.2f} K | median T_cold={median:.2f} K"
            )
        except Exception as exc:
            self.line.set_data([], [])
            self.ax.set_title(
                f"[{self.index + 1}/{len(self.pairs)}] ERROR: {exc}", color="tab:red"
            )
        self.fig.canvas.draw_idle()


def main():
    parser = argparse.ArgumentParser(
        description="Plot cold-load temperatures from paired hot/cold .spec spectra."
    )
    parser.add_argument("directory", nargs="?", help="Measurement folder; omit to choose graphically.")
    parser.add_argument(
        "--tnoise", "--noise-temperature", dest="tnoise", default=10000.0, type=float,
        help="Receiver noise temperature in K."
    )
    parser.add_argument(
        "--thot", type=float, default=300.0,
        help="Hot-load temperature in K."
    )
    parser.add_argument(
        "--pair-tolerance", type=float, default=60.0,
        help="Maximum hot/cold time separation in seconds (default: 60)."
    )
    parser.add_argument(
        "--x-axis", choices=("frequency", "bins", "sidebands"), default="frequency"
    )
    parser.add_argument("--recursive", action="store_true", help="Search subdirectories too.")
    parser.add_argument("--cache-size", type=int, default=32)
    args = parser.parse_args()

    directory = (
        sau.choose_directory(Path.cwd())
        if args.directory is None
        else Path(args.directory).expanduser().resolve()
    )
    if directory is None:
        return
    if not directory.is_dir():
        parser.error(f"Not a directory: {directory}")

    pairs = find_pairs(directory, args.recursive, args.pair_tolerance)
    if not pairs:
        parser.error("No timestamped hot/cold pairs found within the requested tolerance.")

    print(f"Found {len(pairs)} hot/cold pairs in {directory}")
    ColdLoadTemperatureViewer(
        pairs,
        sau.parse_header_csv(directory),
        args.tnoise,
        args.thot,
        args.x_axis,
        max(4, args.cache_size),
    )
    plt.show()


if __name__ == "__main__":
    main()
