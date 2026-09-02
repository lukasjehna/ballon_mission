#!/usr/bin/env python3
"""Something is wrong here. Is gives negative cold load temperatures.
Plot calculated cold-load temperature versus time for hot/cold .spec pairs.

The script uses a known receiver noise temperature and hot-load temperature to
invert the Y-factor equation and calculate the cold-load temperature for every
hot/cold spectrum pair:

    T_cold = (T_hot - Y * T_noise) / (Y - 1)

where Y is the ratio of the averaged hot and cold powers. The x-axis is hours
since the first spectrum.
Hm, this does not make sense

Examples:
    python3 cold_load_temperature_over_time.py /path/to/measurement
    python3 src/analysis/cold_load_temperature_over_time.py --noise-temperature 15000 --thot 300 --if-frequency 270 --n-points 5
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


def mean_squared_spectrum(path: Path) -> np.ndarray:
    return sau.file_mean_spectrum(path)


def cold_temperature_at_bin_window(
    hot_spectrum: np.ndarray,
    cold_spectrum: np.ndarray,
    center_bin: int,
    n_points: int,
    noise_temperature_k: float,
    hot_temperature_k: float,
) -> float:
    """Calculate cold-load temperature from the Y-factor over a bin window."""
    n_bins = hot_spectrum.size
    if cold_spectrum.size != n_bins:
        raise ValueError("Hot and cold spectra must have the same length.")

    if n_points < 1:
        raise ValueError("n_points must be at least 1.")

    half = n_points // 2
    start = max(0, center_bin - half)
    stop = min(n_bins, center_bin + half + 1)

    hot_window = hot_spectrum[start:stop]
    cold_window = cold_spectrum[start:stop]
    if hot_window.size == 0 or cold_window.size == 0:
        return float("nan")

    hot_power = float(np.mean(hot_window))
    cold_power = float(np.mean(cold_window))
    if cold_power <= 0:
        return float("nan")

    y_factor = hot_power / cold_power
    if y_factor <= 1.0:
        return float("nan")

    return (hot_temperature_k - y_factor * noise_temperature_k) / (y_factor - 1.0)


def calculate_cold_temperatures(
    pairs: list[HotColdPair],
    center_bin: int,
    n_points: int,
    noise_temperature_k: float,
    hot_temperature_k: float,
) -> tuple[np.ndarray, np.ndarray]:
    times_h: list[float] = []
    temperatures_k: list[float] = []
    first_timestamp = min(
        min(pair.hot.timestamp, pair.cold.timestamp) for pair in pairs
    )

    for pair in pairs:
        hot = mean_squared_spectrum(pair.hot.path)
        cold = mean_squared_spectrum(pair.cold.path)
        if hot.size != cold.size:
            raise ValueError(
                f"Bin-count mismatch for {pair.hot.path.name} and "
                f"{pair.cold.path.name}: {hot.size} versus {cold.size}."
            )
        if not 0 <= center_bin < hot.size:
            raise ValueError(f"Center bin {center_bin} is outside 0..{hot.size - 1}.")

        pair_timestamp = min(pair.hot.timestamp, pair.cold.timestamp)
        elapsed_hours = (pair_timestamp - first_timestamp).total_seconds() / 3600.0
        cold_temperature = cold_temperature_at_bin_window(
            hot,
            cold,
            center_bin,
            n_points,
            noise_temperature_k,
            hot_temperature_k,
        )
        times_h.append(elapsed_hours)
        temperatures_k.append(cold_temperature)

    return np.asarray(times_h), np.asarray(temperatures_k)


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
        "--noise-temperature", "--tnoise", dest="noise_temperature",
        type=float, default=15000.0,
        help="Receiver noise temperature in K (default: 15000).",
    )
    parser.add_argument(
        "--thot", type=float, default=300.0,
        help="Hot-load temperature in K (default: 300).",
    )
    parser.add_argument(
        "--pair-tolerance", type=float, default=60.0,
        help="Maximum hot/cold separation in seconds (default: 60).",
    )
    parser.add_argument("--recursive", action="store_true", help="Search subdirectories too.")
    parser.add_argument("--output", type=Path, default=None, help="Optional PNG output path.")
    args = parser.parse_args()

    if args.noise_temperature <= 0:
        parser.error("--noise-temperature must be positive.")
    if args.thot <= 0:
        parser.error("--thot must be positive.")

    directory = choose_folder() if args.directory is None else Path(args.directory).expanduser().resolve()
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
        except ValueError as error:
            parser.error(str(error))
    else:
        center_bin = args.bin

    times_h, temperatures_k = calculate_cold_temperatures(
        pairs,
        center_bin,
        args.n_points,
        args.noise_temperature,
        args.thot,
    )

    output_path = args.output or directory / f"{directory.name}_cold_load_temperature_over_time.png"
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(times_h, temperatures_k, "o-", color="tab:blue", markersize=4)
    ax.set_xlabel("Time [h]")
    ax.set_ylabel("Cold-load temperature [K]")
    ax.set_title(
        f"Cold-load temperature at IF={args.if_frequency:g} MHz "
        f"(bin {center_bin}, avg {args.n_points} pts) | "
        f"T_noise={args.noise_temperature:g} K, T_hot={args.thot:g} K"
    )
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    print(f"Found {len(pairs)} hot/cold pairs.")
    print(f"Using spectral bin {center_bin}, averaging over {args.n_points} points.")
    print(f"Saved plot: {output_path}")
    plt.show()


if __name__ == "__main__":
    main()
