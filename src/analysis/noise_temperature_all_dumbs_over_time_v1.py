#!/usr/bin/env python3
"""Plot noise temperature for every dump in each hot/cold .spec pair.
    python3 src/analysis/noise_temperature_all_dumbs_over_time.py --if-frequency 270 --n-points 5 --thot 300 --tcold 5
    python3 src/analysis/noise_temperature_all_dumbs_over_time.py \
    /path/to/measurement \
    --if-frequency 270 \
    --n-points 5 \
    --output noise_temperature_all_dumps.png
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
    hot = sorted((x for x in parsed if x.load == "hot"), key=lambda x: x.timestamp)
    cold = sorted((x for x in parsed if x.load == "cold"), key=lambda x: x.timestamp)

    unused_cold = set(range(len(cold)))
    pairs = []
    for hot_file in hot:
        if not unused_cold:
            break
        separation_s, cold_index = min(
            (abs((cold[i].timestamp - hot_file.timestamp).total_seconds()), i)
            for i in unused_cold
        )
        if separation_s <= tolerance_s:
            unused_cold.remove(cold_index)
            pairs.append(HotColdPair(hot_file, cold[cold_index]))
    return pairs


def frequency_to_bin(if_frequency_mhz: float, bandwidth_ghz: float | None, n_bins: int) -> int:
    if bandwidth_ghz is None or bandwidth_ghz <= 0:
        raise ValueError("Could not determine bandwidth; use --bin.")
    return max(0, min(n_bins - 1, round(if_frequency_mhz / 1000 / bandwidth_ghz * n_bins)))


def noise_temperature_per_dump(
    hot_spectra: np.ndarray,
    cold_spectra: np.ndarray,
    center_bin: int,
    n_points: int,
    hot_temperature_k: float,
    cold_temperature_k: float,
) -> np.ndarray:
    """Return one Y-factor noise temperature for every dump."""
    if hot_spectra.ndim != 2 or cold_spectra.ndim != 2:
        raise ValueError("Expected spectra with shape (dumps, bins).")
    if hot_spectra.shape != cold_spectra.shape:
        raise ValueError(
            f"Hot/cold shape mismatch: {hot_spectra.shape} versus {cold_spectra.shape}."
        )

    half = n_points // 2
    start = max(0, center_bin - half)
    stop = min(hot_spectra.shape[1], center_bin + half + 1)
    hot_power = np.mean(hot_spectra[:, start:stop], axis=1)
    cold_power = np.mean(cold_spectra[:, start:stop], axis=1)

    result = np.full(hot_power.shape, np.nan, dtype=float)
    valid = (cold_power > 0) & (hot_power / cold_power > 1)
    y_factor = hot_power[valid] / cold_power[valid]
    result[valid] = (hot_temperature_k - y_factor * cold_temperature_k) / (y_factor - 1)
    return result


def calculate_noise_temperatures(
    pairs: list[HotColdPair],
    center_bin: int,
    n_points: int,
    hot_temperature_k: float,
    cold_temperature_k: float,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    times_h = []
    temperatures = []
    labels = []
    first_timestamp = min(min(p.hot.timestamp, p.cold.timestamp) for p in pairs)

    for pair in pairs:
        _, hot, _ = sau.load_spec_file(pair.hot.path)
        _, cold, _ = sau.load_spec_file(pair.cold.path)
        if hot.shape != cold.shape:
            raise ValueError(f"Shape mismatch for {pair.hot.path.name} and {pair.cold.path.name}.")
        values = noise_temperature_per_dump(
            hot, cold, center_bin, n_points, hot_temperature_k, cold_temperature_k
        )
        pair_time_h = (min(pair.hot.timestamp, pair.cold.timestamp) - first_timestamp).total_seconds() / 3600
        dump_spacing_h = 0.0
        if values.size > 1:
            dump_spacing_h = (pair.hot.timestamp - pair.cold.timestamp).total_seconds() / 3600 / values.size
        dump_times = pair_time_h + np.arange(values.size) * dump_spacing_h
        times_h.extend(dump_times)
        temperatures.extend(values)
        labels.extend([f"{pair.hot.path.name} / {pair.cold.path.name}"] * values.size)

    return np.asarray(times_h), np.asarray(temperatures), labels


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

    directory = choose_folder() if args.directory is None else Path(args.directory).expanduser().resolve()
    if directory is None:
        return
    pairs = find_pairs(directory, args.recursive, args.pair_tolerance)
    if not pairs:
        parser.error("No timestamped hot/cold pairs found within tolerance.")

    header = sau.parse_header_csv(directory)
    thot_header, tcold_header = sau._extract_hot_cold_kelvin(header)
    thot = args.thot if args.thot is not None else thot_header
    tcold = args.tcold if args.tcold is not None else tcold_header
    if thot is None or tcold is None:
        parser.error("Hot/cold temperatures are missing; supply --thot and --tcold.")

    _, first_spectrum, first_meta = sau.load_spec_file(pairs[0].hot.path)
    bandwidth = sau._get_bw_ghz(header) or sau._parse_frequency_ghz(first_meta.get("bandwidth"))
    center_bin = args.bin if args.bin is not None else frequency_to_bin(args.if_frequency, bandwidth, first_spectrum.shape[1])

    times_h, temperatures, labels = calculate_noise_temperatures(
        pairs, center_bin, args.n_points, float(thot), float(tcold)
    )
    output_path = args.output or directory / f"{directory.name}_noise_temperature_all_dumps.png"

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for label in dict.fromkeys(labels):
        mask = np.asarray([x == label for x in labels])
        ax.plot(times_h[mask], temperatures[mask], ".", markersize=3, label=label)
    ax.set_xlabel("Time [h]")
    ax.set_ylabel("Noise temperature [K]")
    ax.set_title(f"Noise temperature for IF={args.if_frequency:g} MHz (bin {center_bin})")
    ax.grid(True, alpha=0.3)
    if len(set(labels)) <= 12:
        ax.legend(fontsize="small")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    print(f"Found {len(pairs)} hot/cold pairs and {len(temperatures)} dumps.")
    print(f"Saved plot: {output_path}")
    plt.show()


if __name__ == "__main__":
    main()
