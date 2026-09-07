#!/usr/bin/env python3
"""Plot Y-factor noise temperature for corresponding dumps in hot/cold .spec pairs.

Each dump in a hot file is paired with the dump at the same index in its
corresponding cold file. For example, hot dump 0 is combined with cold dump 0,
hot dump 1 with cold dump 1, and so on.
python3 src/analysis/noise_temperature_all_dumbs_over_time.py --if-frequency 270 --n-points 9 --thot 300 --tcold 5
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
    if bandwidth_ghz is None or bandwidth_ghz <= 0:
        raise ValueError(
            "Could not determine the measurement bandwidth from the header. "
            "Use --bin to select a bin explicitly."
        )
    frequency_ghz = if_frequency_mhz / 1000.0
    index = round(frequency_ghz / bandwidth_ghz * n_bins)
    return max(0, min(n_bins - 1, index))


def noise_temperature_at_bin_window(
    hot_spectrum: np.ndarray,
    cold_spectrum: np.ndarray,
    center_bin: int,
    n_points: int,
    hot_temperature_k: float,
    cold_temperature_k: float,
) -> float:
    if hot_spectrum.size != cold_spectrum.size:
        raise ValueError("Hot and cold spectra must have the same length.")
    if n_points < 1:
        raise ValueError("--n-points must be at least 1.")

    half = n_points // 2
    start = max(0, center_bin - half)
    stop = min(hot_spectrum.size, center_bin + half + 1)
    hot_power = float(np.mean(hot_spectrum[start:stop]))
    cold_power = float(np.mean(cold_spectrum[start:stop]))

    if cold_power <= 0:
        return float("nan")
    y_factor = hot_power / cold_power
    if y_factor <= 1.0:
        return float("nan")
    return (hot_temperature_k - y_factor * cold_temperature_k) / (y_factor - 1.0)


def calculate_noise_temperatures(
    pairs: list[HotColdPair],
    center_bin: int,
    n_points: int,
    hot_temperature_k: float,
    cold_temperature_k: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return elapsed time, dump index, and one noise temperature per dump."""
    times_h: list[float] = []
    dump_indices: list[int] = []
    temperatures_k: list[float] = []

    first_timestamp = min(
        min(pair.hot.timestamp, pair.cold.timestamp) for pair in pairs
    )

    for pair in pairs:
        hot_times, hot_spectra, hot_meta = sau.load_spec_file(pair.hot.path)
        cold_times, cold_spectra, cold_meta = sau.load_spec_file(pair.cold.path)

        if hot_spectra.shape != cold_spectra.shape:
            raise ValueError(
                f"Shape mismatch for {pair.hot.path.name} and {pair.cold.path.name}: "
                f"{hot_spectra.shape} versus {cold_spectra.shape}."
            )

        n_dumps, n_bins = hot_spectra.shape
        if not 0 <= center_bin < n_bins:
            raise ValueError(f"Center bin {center_bin} is outside 0..{n_bins - 1}.")

        # Use the timestamp belonging to each dump when available. The file
        # timestamp is used as a fallback if the timestamp arrays are absent.
        pair_timestamp = min(pair.hot.timestamp, pair.cold.timestamp)
        for dump_index in range(n_dumps):
            hot_dump = hot_spectra[dump_index].astype(float) ** 2
            cold_dump = cold_spectra[dump_index].astype(float) ** 2
            temperature = noise_temperature_at_bin_window(
                hot_dump,
                cold_dump,
                center_bin,
                n_points,
                hot_temperature_k,
                cold_temperature_k,
            )

            timestamp_seconds = None
            if dump_index < len(hot_times):
                timestamp_seconds = float(hot_times[dump_index])
            elif dump_index < len(cold_times):
                timestamp_seconds = float(cold_times[dump_index])

            if timestamp_seconds is None:
                elapsed_hours = (
                    pair_timestamp - first_timestamp
                ).total_seconds() / 3600.0
            else:
                # .spec timestamps are interpreted as Unix seconds when they
                # are absolute; otherwise they are treated as relative dump
                # times within the file.
                if timestamp_seconds > 1e8:
                    elapsed_hours = (
                        datetime.fromtimestamp(timestamp_seconds) - first_timestamp
                    ).total_seconds() / 3600.0
                else:
                    elapsed_hours = (
                        pair_timestamp - first_timestamp
                    ).total_seconds() / 3600.0 + timestamp_seconds / 3600.0

            times_h.append(elapsed_hours)
            dump_indices.append(dump_index)
            temperatures_k.append(temperature)

    return (
        np.asarray(times_h),
        np.asarray(dump_indices),
        np.asarray(temperatures_k),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", help="Folder containing hot/cold .spec files.")
    parser.add_argument("--if-frequency", type=float, default=270.0)
    parser.add_argument("--bin", type=int, default=None)
    parser.add_argument("--n-points", type=int, default=5)
    parser.add_argument("--thot", type=float, default=None)
    parser.add_argument("--tcold", type=float, default=None)
    parser.add_argument("--pair-tolerance", type=float, default=60.0)
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    directory = (
        choose_folder()
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

    header = sau.parse_header_csv(directory)
    hot_from_header, cold_from_header = sau._extract_hot_cold_kelvin(header)
    thot = args.thot if args.thot is not None else hot_from_header
    tcold = args.tcold if args.tcold is not None else cold_from_header
    if thot is None or tcold is None:
        parser.error("Hot/cold temperatures are missing. Supply --thot and --tcold.")

    _, first_spectrum, first_meta = sau.load_spec_file(pairs[0].hot.path)
    n_bins = first_spectrum.shape[1]
    bandwidth_ghz = sau._get_bw_ghz(header)
    if bandwidth_ghz is None:
        bandwidth_ghz = sau._parse_frequency_ghz(first_meta.get("bandwidth"))

    center_bin = (
        args.bin
        if args.bin is not None
        else frequency_to_bin(args.if_frequency, bandwidth_ghz, n_bins)
    )

    times_h, dump_indices, temperatures_k = calculate_noise_temperatures(
        pairs, center_bin, args.n_points, float(thot), float(tcold)
    )

    output_path = args.output or directory / f"{directory.name}_noise_temperature_over_time.png"
    fig, ax = plt.subplots(figsize=(10, 5.5))
    ax.plot(times_h, temperatures_k, "o", color="tab:green", markersize=3, linewidth=0.8)
    ax.set_xlabel("Time [h]")
    ax.set_ylabel("Noise temperature [K]")
    ax.set_title(
        f"Noise temperature at IF={args.if_frequency:g} MHz "
        f"(bin {center_bin}, avg {args.n_points} bins) | "
        f"T_hot={thot:g} K, T_cold={tcold:g} K | "
        f"{len(temperatures_k)} dumps"
    )
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)

    print(f"Found {len(pairs)} hot/cold file pairs.")
    print(f"Calculated {len(temperatures_k)} dump-level noise temperatures.")
    print(f"Saved plot: {output_path}")
    plt.show()


if __name__ == "__main__":
    main()
