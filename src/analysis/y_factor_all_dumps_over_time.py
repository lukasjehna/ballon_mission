#!/usr/bin/env python3
"""Plot Y-factor versus time using individual spectra from hot/cold .spec files.

For each hot/cold file pair, this script:
  - Loads all spectra in the hot file and all spectra in the cold file.
  - Pairs them by index: spectrum 0 in hot with spectrum 0 in cold, etc.
  - Computes Y = P_hot / P_cold at a chosen IF frequency (averaged over
    adjacent bins if desired).
  - Plots Y-factor versus time, where time is derived from the timestamps
    inside the .spec files (first spectrum of each file pair).

Unlike noise_temperature_average_over_time.py, this script:
  - Does not require hot/cold temperature input.
  - Uses per-spectrum data instead of file-averaged spectra.
  - Uses timestamps from the first spectrum in each .spec file rather than
    the filename timestamp.

The .spec files are expected to have an inline header line and then rows like:
  timestamp_s,f_IF [GHz],spectrum_index,count
from which the per-spectrum timestamp (first column) is read.

Example:
    python3 y_factor_per_measurement_over_time.py /path/to/measurement  --output y_factor_per_spec.png
    python3 src/analysis/y_factor_all_dumps_over_time.py --if-frequency 270 --n-points 5
"""
from __future__ import annotations

import argparse
import csv
import re
import tkinter as tk
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import List, Tuple, Optional

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


def load_spec_timestamps(spec_path: Path) -> List[float]:
    """
    Load per-spectrum timestamps from a .spec file.

    The file is expected to have a first header line, then CSV-like rows:
      timestamp_s,f_IF [GHz],spectrum_index,count

    This function returns a list of timestamps (float, seconds) for each
    spectrum_index, using the first occurrence of each index.
    """
    timestamps_by_index: dict[int, float] = {}

    with spec_path.open("r", encoding="utf-8", errors="replace") as f:
        # Skip header line
        header_line = f.readline()
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 4:
                continue
            try:
                ts = float(row[0])
                idx = int(row[2])
            except ValueError:
                continue
            if idx not in timestamps_by_index:
                timestamps_by_index[idx] = ts

    if not timestamps_by_index:
        return []

    max_idx = max(timestamps_by_index.keys())
    timestamps = [timestamps_by_index.get(i, float("nan")) for i in range(max_idx + 1)]
    return timestamps


def calculate_y_factors_per_spectrum(
    pairs: list[HotColdPair], center_bin: int, n_points: int
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute Y-factor for each individual spectrum pair using timestamps from .spec files.

    For each hot/cold file pair:
      - Load per-spectrum timestamps from both files.
      - Use the timestamp of spectrum index 0 from the hot file as the pair time.
      - Compute Y-factor for each spectrum index using squared counts.

    Returns:
        times_h: elapsed hours since the first pair for each Y sample
        y_factors: Y-factor values
        pair_indices: sequential index over all spectra (0,1,2,...)
    """
    times_h: list[float] = []
    y_factors: list[float] = []
    pair_indices: list[int] = []

    # First pass: determine the global first timestamp (from spectrum 0 of first pair)
    first_timestamp: Optional[float] = None
    for pair in pairs:
        ts_hot = load_spec_timestamps(pair.hot.path)
        ts_cold = load_spec_timestamps(pair.cold.path)
        if not ts_hot or not ts_cold:
            continue
        t0 = ts_hot[0]
        if not np.isfinite(t0):
            continue
        if first_timestamp is None or t0 < first_timestamp:
            first_timestamp = t0

    if first_timestamp is None:
        return np.array([]), np.array([]), np.array([])

    global_idx = 0
    for pair in pairs:
        ts_hot = load_spec_timestamps(pair.hot.path)
        ts_cold = load_spec_timestamps(pair.cold.path)

        if not ts_hot or not ts_cold:
            continue

        # Use timestamp of first spectrum (index 0) from hot file as pair time
        pair_time = ts_hot[0]
        if not np.isfinite(pair_time):
            continue

        # Load spectra using existing helper (returns squared-mean spectrum)
        # Here we need all individual spectra, so load the raw file again.
        _, hot_spectra, _ = sau.load_spec_file(pair.hot.path)
        _, cold_spectra, _ = sau.load_spec_file(pair.cold.path)
        n_hot = hot_spectra.shape[0]
        n_cold = cold_spectra.shape[0]
        n_used = min(n_hot, n_cold, len(ts_hot), len(ts_cold))

        if n_used == 0:
            continue

        for i in range(n_used):
            hot_spec = hot_spectra[i, :].astype(float) ** 2
            cold_spec = cold_spectra[i, :].astype(float) ** 2

            if not 0 <= center_bin < hot_spec.size:
                raise ValueError(f"Center bin {center_bin} is outside 0..{hot_spec.size - 1}.")

            y = y_factor_at_bin_window(hot_spec, cold_spec, center_bin, n_points)
            elapsed_hours = (pair_time - first_timestamp) / 3600.0

            times_h.append(elapsed_hours)
            y_factors.append(y)
            pair_indices.append(global_idx)
            global_idx += 1

    return np.asarray(times_h), np.asarray(y_factors), np.asarray(pair_indices)


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
        help="Maximum hot/cold separation in seconds (default: 60).",
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

    times_h, y_factors, pair_indices = calculate_y_factors_per_spectrum(
        pairs, center_bin, args.n_points
    )

    if y_factors.size == 0:
        parser.error("No valid Y-factor measurements computed.")

    output_path = args.output or directory / f"{directory.name}_y_factor_per_measurement.png"

    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(times_h, y_factors, ".", color="tab:blue", markersize=4, alpha=0.7)
    ax.set_xlabel("Time [h since first spectrum]")
    ax.set_ylabel("Y-factor, $Y = P_{hot}/P_{cold}$")
    ax.set_title(
        f"Per-spectrum Y-factor at IF={args.if_frequency:g} MHz "
        f"(bin {center_bin}, avg {args.n_points} pts) | "
        f"{y_factors.size} measurements"
    )
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    print(f"Found {len(pairs)} hot/cold file pairs.")
    print(f"Computed {y_factors.size} per-spectrum Y-factor measurements.")
    print(f"Using spectral bin {center_bin}, averaging over {args.n_points} points.")
    print(f"Saved plot: {output_path}")
    plt.show()


if __name__ == "__main__":
    main()