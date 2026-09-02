#!/usr/bin/env python3
"""Plot Y-factor versus time for every hot/cold dump pair in all .spec files.

Unlike noise_temperature_average_over_time.py (one point per file pair), this
script loops over all individual spectra (dumps) inside each hot/cold .spec
file, pairs them by timestamp, and plots one Y-factor point per dump pair.

Files must start with a YYYYMMDDHHMMSS timestamp and end in hot.spec or
cold.spec. Each hot file is paired with the nearest unused cold file, then
all spectra within those files are paired by index.

No temperature input is required; the plotted quantity is Y = P_hot / P_cold.

Examples:
    python3 y_factor_all_dumps_over_time.py /path/to/measurement
    python3 y_factor_all_dumps_over_time.py /path/to/measurement \\
        --if-frequency 270 --n-points 5 --output y_factor_all_dumps.png
"""
from __future__ import annotations

import argparse
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog

import matplotlib.pyplot as plt
import numpy as np

import spec_analysis_utils as sau

TIMESTAMP_RE = re.compile(r"^(\d{14})")
LOAD_RE = re.compile(r"(hot|cold)$", re.IGNORECASE)


@dataclass(frozen=True)
class SpectrumFile:
    timestamp: datetime
    load: str
    path: Path


@dataclass(frozen=True)
class HotColdPair:
    hot: SpectrumFile
    cold: SpectrumFile


def choose_folder() -> Path | None:
    root = tk.Tk()
    root.withdraw()
    try:
        selected = filedialog.askdirectory(title="Select measurement folder")
    finally:
        root.destroy()
    return Path(selected).expanduser().resolve() if selected else None


def parse_spectrum_file(path: Path) -> SpectrumFile | None:
    timestamp_match = TIMESTAMP_RE.match(path.stem)
    load_match = LOAD_RE.search(path.stem)
    if timestamp_match is None or load_match is None:
        return None
    try:
        timestamp = datetime.strptime(timestamp_match.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return SpectrumFile(timestamp, load_match.group(1).lower(), path)


def find_pairs(directory: Path, recursive: bool, tolerance_s: float) -> list[HotColdPair]:
    pattern = "**/*.spec" if recursive else "*.spec"
    parsed = [
        parsed_file
        for path in directory.glob(pattern)
        if (parsed_file := parse_spectrum_file(path)) is not None
    ]

    hot = sorted((item for item in parsed if item.load == "hot"), key=lambda x: x.timestamp)
    cold = sorted((item for item in parsed if item.load == "cold"), key=lambda x: x.timestamp)

    unused_cold = set(range(len(cold)))
    pairs: list[HotColdPair] = []
    for hot_file in hot:
        if not unused_cold:
            break
        candidates = [
            (abs((cold[index].timestamp - hot_file.timestamp).total_seconds()), index)
            for index in unused_cold
        ]
        separation_s, cold_index = min(candidates)
        if separation_s <= tolerance_s:
            unused_cold.remove(cold_index)
            pairs.append(HotColdPair(hot_file, cold[cold_index]))
    return pairs


def frequency_to_bin(if_frequency_mhz: float, bandwidth_ghz: float | None, n_bins: int) -> int:
    """Map IF frequency to a bin for a 0..bandwidth FFT frequency axis."""
    if bandwidth_ghz is None or bandwidth_ghz <= 0:
        raise ValueError(
            "Could not determine the measurement bandwidth from the header. "
            "Use --bin to select a bin explicitly."
        )
    frequency_ghz = if_frequency_mhz / 1000.0
    index = round(frequency_ghz / bandwidth_ghz * n_bins)
    return max(0, min(n_bins - 1, index))


def y_factor_at_bin_window(
    hot_spectrum: np.ndarray,
    cold_spectrum: np.ndarray,
    center_bin: int,
    n_points: int,
) -> float:
    """Compute Y = P_hot / P_cold after averaging adjacent spectral bins."""
    if hot_spectrum.size != cold_spectrum.size:
        raise ValueError("Hot and cold spectra must have the same length.")
    if n_points < 1:
        raise ValueError("--n-points must be at least 1.")

    half = n_points // 2
    start = max(0, center_bin - half)
    stop = min(hot_spectrum.size, center_bin + half + 1)
    hot_window = hot_spectrum[start:stop]
    cold_window = cold_spectrum[start:stop]

    if hot_window.size == 0 or cold_window.size == 0:
        return float("nan")

    cold_power = float(np.mean(cold_window))
    if cold_power <= 0:
        return float("nan")
    return float(np.mean(hot_window)) / cold_power


def calculate_y_factors_all_dumps(
    pairs: list[HotColdPair], center_bin: int, n_points: int
) -> tuple[np.ndarray, np.ndarray, list[datetime]]:
    """Return times, Y-factors, and timestamps for every hot/cold dump pair."""
    times_h: list[float] = []
    y_factors: list[float] = []
    timestamps: list[datetime] = []

    first_timestamp = min(
        min(pair.hot.timestamp, pair.cold.timestamp) for pair in pairs
    )

    for pair in pairs:
        _, hot_spectra, _ = sau.load_spec_file(pair.hot.path)
        _, cold_spectra, _ = sau.load_spec_file(pair.cold.path)

        if hot_spectra.shape != cold_spectra.shape:
            raise ValueError(
                f"Spectra shape mismatch for {pair.hot.path.name} and "
                f"{pair.cold.path.name}: {hot_spectra.shape} vs {cold_spectra.shape}."
            )

        n_dumps, n_bins = hot_spectra.shape
        if not 0 <= center_bin < n_bins:
            raise ValueError(f"Center bin {center_bin} is outside 0..{n_bins - 1}.")

        # Use squared counts for power
        hot_power = hot_spectra.astype(float) ** 2
        cold_power = cold_spectra.astype(float) ** 2

        for i in range(n_dumps):
            y = y_factor_at_bin_window(hot_power[i], cold_power[i], center_bin, n_points)
            y_factors.append(y)

            # Approximate dump time: file timestamp + i * nominal integration
            # If integration time is unknown, just use file timestamp for all dumps.
            dump_time = pair.hot.timestamp
            elapsed_hours = (dump_time - first_timestamp).total_seconds() / 3600.0
            times_h.append(elapsed_hours)
            timestamps.append(dump_time)

    return np.asarray(times_h), np.asarray(y_factors), timestamps


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", help="Folder containing hot/cold .spec files.")
    parser.add_argument(
        "--if-frequency", type=float, default=270.0,
        help="IF frequency in MHz (default: 270).",
    )
    parser.add_argument(
        "--bin", type=int, default=None,
        help="Use this spectral bin instead of converting --if-frequency.",
    )
    parser.add_argument(
        "--n-points", type=int, default=5,
        help="Number of adjacent bins to average around the center bin (default: 5).",
    )
    parser.add_argument(
        "--pair-tolerance", type=float, default=60.0,
        help="Maximum hot/cold file separation in seconds (default: 60).",
    )
    parser.add_argument("--recursive", action="store_true", help="Search subdirectories too.")
    parser.add_argument("--output", type=Path, default=None, help="Optional PNG output path.")
    args = parser.parse_args()

    directory = (
        choose_folder() if args.directory is None
        else Path(args.directory).expanduser().resolve()
    )
    if directory is None:
        return
    if not directory.is_dir():
        parser.error(f"Not a directory: {directory}")

    pairs = find_pairs(directory, args.recursive, args.pair_tolerance)
    if not pairs:
        parser.error("No timestamped hot/cold pairs found within the requested tolerance.")

    header = sau.parse_header_csv(directory)
    first_hot = pairs[0].hot.path
    _, first_spectrum, first_meta = sau.load_spec_file(first_hot)
    n_bins = first_spectrum.shape[1]
    bandwidth_ghz = sau._get_bw_ghz(header)
    if bandwidth_ghz is None:
        bandwidth_ghz = sau._parse_frequency_ghz(first_meta.get("bandwidth"))

    if args.bin is None:
        try:
            center_bin = frequency_to_bin(args.if_frequency, bandwidth_ghz, n_bins)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        center_bin = args.bin

    times_h, y_factors, timestamps = calculate_y_factors_all_dumps(
        pairs, center_bin, args.n_points
    )
    output_path = args.output or directory / f"{directory.name}_y_factor_all_dumps_over_time.png"

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(times_h, y_factors, ".", color="tab:blue", markersize=4, alpha=0.7)
    ax.set_xlabel("Time [h since first spectrum]")
    ax.set_ylabel("Y-factor, $Y = P_{hot}/P_{cold}$")
    ax.set_title(
        f"Y-factor at IF={args.if_frequency:g} MHz "
        f"(bin {center_bin}, avg {args.n_points} pts) | "
        f"{len(pairs)} file pairs, {len(y_factors)} dump pairs"
    )
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    print(f"Found {len(pairs)} hot/cold file pairs.")
    print(f"Using spectral bin {center_bin}, averaging over {args.n_points} points.")
    print(f"Plotted {len(y_factors)} dump-level Y-factor points.")
    print(f"Saved plot: {output_path}")
    plt.show()


if __name__ == "__main__":
    main()