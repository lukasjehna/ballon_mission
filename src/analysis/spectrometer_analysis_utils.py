#!/usr/bin/env python3

from pathlib import Path
import csv
import re
import tkinter as tk
from tkinter import filedialog
from typing import Optional, List, Dict, Tuple

import numpy as np
import matplotlib.pyplot as plt
from file_parser_utils import resolve_measurement_dir_with_specs, get_header_value, parse_frequency_ghz, extract_hot_cold_kelvin, choose_directory, parse_header_csv, load_spec_file


def despike_1d(y: np.ndarray, window: int = 5, sigma_thresh: float = 6.0) -> Tuple[np.ndarray, int]:
    """Replace impulse-like outliers in finite samples using a median/MAD rule.
    smaller sigma_thresh  is more aggressive; window is the size of the median filter (odd integer >= 3)."""
    arr = np.asarray(y, dtype=float)
    out = arr.copy()

    finite = np.isfinite(arr)
    if np.count_nonzero(finite) < 3:
        return out, 0

    vals = arr[finite]
    w = max(3, int(window) | 1)  # odd window >= 3
    pad = w // 2
    padded = np.pad(vals, (pad, pad), mode="edge")
    med = np.array([np.median(padded[i:i + w]) for i in range(vals.size)], dtype=float)

    resid = vals - med
    mad = float(np.median(np.abs(resid)))
    sigma = max(1.4826 * mad, np.finfo(float).eps)
    spikes = np.abs(resid) > (sigma_thresh * sigma)

    idx = np.where(finite)[0]
    out[idx[spikes]] = med[spikes]
    return out, int(np.count_nonzero(spikes))


def despike_1d_in_window(
    y: np.ndarray,
    bin_start: int,
    bin_stop: int,
    window: int = 5,
    sigma_thresh: float = 6.0,
) -> Tuple[np.ndarray, int]:
    """Apply despike only inside [bin_start, bin_stop] (inclusive)."""
    arr = np.asarray(y, dtype=float)
    out = arr.copy()
    if out.size == 0:
        return out, 0

    i0 = max(0, int(bin_start))
    i1 = min(out.size - 1, int(bin_stop))
    if i0 > i1:
        return out, 0

    # Call despike_1d on the slice and write back the filtered data.
    filtered, removed = despike_1d(out[i0:i1 + 1], window=window, sigma_thresh=sigma_thresh)
    out[i0:i1 + 1] = filtered
    return out, removed





def get_lo_ghz(header_meta: Dict[str, str]) -> Optional[float]:
    """Return LO (GHz) from header metadata, or None."""
    if not header_meta:
        return None
    for key in ("f_LO", "f_RX"):
        raw = None
        try:
            raw = get_header_value(header_meta, key)
        except Exception:
            raw = header_meta.get(key) if isinstance(header_meta, dict) else None
        if raw is None:
            continue
        try:
            return parse_frequency_ghz(raw)
        except Exception:
            try:
                return float(raw)
            except Exception:
                # try to extract a number from string
                m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(raw))
                if m:
                    return float(m.group(0))
    return None


def _get_bw_ghz(header_meta: Dict[str, str]) -> Optional[float]:
    """Return bandwidth (GHz) from header metadata, or None."""
    if not header_meta:
        return None
    for key in ("BW", "bandwidth"):
        raw = None
        try:
            raw = get_header_value(header_meta, key)
        except Exception:
            raw = header_meta.get(key) if isinstance(header_meta, dict) else None
        if raw is None:
            continue
        # try parse_frequency_ghz if it understands units, otherwise parse number
        try:
            return parse_frequency_ghz(raw)
        except Exception:
            try:
                return float(raw)
            except Exception:
                m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", str(raw))
                if m:
                    return float(m.group(0))
    return None


def _frequency_offset_to_bin_index(
    freq_offset_ghz: float,
    bandwidth_ghz: float,
    n_bins: int = 8192,
) -> int:
    """Convert frequency offset (in GHz) to bin index.

    Assumes linear mapping: bin i corresponds to freq_offset = (i / n_bins) * bandwidth_ghz
    """
    if bandwidth_ghz <= 0 or n_bins <= 0:
        return 0
    bin_idx = int(round((freq_offset_ghz / bandwidth_ghz) * n_bins))
    return max(0, min(n_bins - 1, bin_idx))


def _compute_bin_window_from_center_freq(
    center_freq_ghz: float,
    f_rx_ghz: Optional[float],
    bandwidth_ghz: Optional[float],
    bin_offset: int = 615,
    n_bins: int = 8192,
) -> Tuple[int, int]:
    """Compute bin_start and bin_stop centered on center_freq_ghz.

    If f_rx_ghz and bandwidth_ghz are available, compute the absolute offset frequency
    and convert to bin index. Then apply ±bin_offset. Clamp to [0, n_bins-1].
    """
    if f_rx_ghz is None or bandwidth_ghz is None or bandwidth_ghz <= 0:
        # Fallback: use fixed defaults
        return 200, 1850

    # Frequency offset from f_RX to center_freq (use absolute value for symmetric bin window)
    freq_offset_ghz = abs(center_freq_ghz - f_rx_ghz)
    center_bin = _frequency_offset_to_bin_index(freq_offset_ghz, bandwidth_ghz, n_bins)

    bin_start = max(0, center_bin - bin_offset)
    bin_stop = min(n_bins - 1, center_bin + bin_offset)

    return bin_start, bin_stop


def spectroscopy_convert(
    f_if: Optional[float] = None,
    f_lo: Optional[float] = None,
    f_sig: Optional[float] = None,
    sideband: str = "USB",
) -> Dict[str, float]:
    """
    Given any two of (f_if, f_lo, f_sig) in GHz and the sideband ("USB" or "LSB"),
    compute the third and return a dict {'f_if':..., 'f_lo':..., 'f_sig':...}.

    Conventions:
      USB: f_sig = f_lo + f_if
      LSB: f_sig = f_lo - f_if

    Raises ValueError if fewer than two inputs are provided or if all three are
    provided but inconsistent (within 1e-6 GHz).
    """
    sb = (sideband or "").strip().lower()
    if sb in ("usb", "upper", "u"):
        sign = +1
    elif sb in ("lsb", "lower", "l"):
        sign = -1
    else:
        raise ValueError(f"Unknown sideband: {sideband!r} (expected 'USB' or 'LSB')")

    provided = {"f_if": f_if, "f_lo": f_lo, "f_sig": f_sig}
    n_provided = sum(1 for v in provided.values() if v is not None)
    if n_provided < 2:
        raise ValueError("Need at least two of f_if, f_lo, f_sig to compute the third.")

    # Helper to compare floats
    def _close(a: float, b: float, tol: float = 1e-6) -> bool:
        return abs(a - b) <= tol

    # Compute missing value
    if f_if is None:
        # f_sig = f_lo + sign * f_if  => f_if = sign * (f_sig - f_lo)
        if f_lo is None or f_sig is None:
            raise ValueError("Unexpected missing values while computing f_if.")
        f_if = sign * (f_sig - f_lo)
    elif f_lo is None:
        # f_lo = f_sig - sign * f_if
        if f_if is None or f_sig is None:
            raise ValueError("Unexpected missing values while computing f_lo.")
        f_lo = f_sig - sign * f_if
    elif f_sig is None:
        # f_sig = f_lo + sign * f_if
        if f_if is None or f_lo is None:
            raise ValueError("Unexpected missing values while computing f_sig.")
        f_sig = f_lo + sign * f_if

    # If all three were provided originally, verify consistency
    if sum(1 for v in provided.values() if v is not None) == 3:
        expected_sig = f_lo + sign * f_if
        if not _close(expected_sig, f_sig):
            raise ValueError(
                f"Inconsistent frequencies for sideband {sideband!r}: "
                f"expected f_sig={expected_sig:.9f} GHz but got f_sig={f_sig:.9f} GHz"
            )

    return {"f_if": float(f_if), "f_lo": float(f_lo), "f_sig": float(f_sig)}


def compute_noise_temperature(avg_hot: np.ndarray, avg_cold: np.ndarray, t_hot_k: float, t_cold_k: float) -> np.ndarray:
    """Return per‑bin noise temperature [K] using hot/cold averages."""
    eps = np.finfo(float).eps
    y = avg_hot / np.maximum(avg_cold, eps)
    t_noise = np.full_like(avg_hot, np.nan, dtype=float)
    valid = (avg_cold > 0) & (y > 1.0)
    t_noise[valid] = (float(t_hot_k) - y[valid] * float(t_cold_k)) / (y[valid] - 1.0)
    return t_noise

def compute_cold_minus_hot(avg_cold: np.ndarray, avg_hot: np.ndarray) -> np.ndarray:
    """Return per-bin difference (cold - hot) of average loads."""
    cold = np.asarray(avg_cold, dtype=float)
    hot = np.asarray(avg_hot, dtype=float)
    if cold.shape != hot.shape:
        raise ValueError("avg_cold and avg_hot must have the same shape")
    return cold - hot

def compute_median_hot_cold_distance(
    avg_hot: np.ndarray,
    avg_cold: np.ndarray,
    bin_start: int = 614,
    bin_stop: int = 1843,
) -> float:
    """Return the median absolute distance between avg_hot and avg_cold in the given bin range."""
    hot = np.asarray(avg_hot, dtype=float)
    cold = np.asarray(avg_cold, dtype=float)
    if hot.shape != cold.shape:
        raise ValueError("avg_hot and avg_cold must have the same shape")

    i0 = max(0, int(bin_start))
    i1 = min(hot.size - 1, int(bin_stop))
    if i0 > i1:
        raise ValueError("Invalid bin range")

    diff = np.abs(hot[i0:i1 + 1] - cold[i0:i1 + 1])
    return float(np.nanmedian(diff))

def calibrate_spectrum_to_temperature(
    counts: np.ndarray,
    avg_cold: np.ndarray,
    avg_hot: np.ndarray,
    t_hot_k: float,
    t_cold_k: float,
) -> np.ndarray:
    """
    Calibrate a spectrum to brightness temperature using hot/cold load references.
    
    Formula: T_brightness = T_cold + (counts - cold_counts) / (hot_counts - cold_counts) * (T_hot - T_cold)
    
    Args:
        counts: spectrum to calibrate (per-bin counts)
        avg_cold: averaged cold load spectrum
        avg_hot: averaged hot load spectrum
        t_hot_k: hot load temperature in Kelvin
        t_cold_k: cold load temperature in Kelvin
    
    Returns:
        per-bin brightness temperature in Kelvin
    """
    counts = np.asarray(counts, dtype=float)
    cold = np.asarray(avg_cold, dtype=float)
    hot = np.asarray(avg_hot, dtype=float)
    
    if counts.shape != cold.shape or counts.shape != hot.shape:
        raise ValueError("counts, avg_cold, and avg_hot must have the same shape")
    
    eps = np.finfo(float).eps
    denom = hot - cold
    t_brightness = np.full_like(counts, np.nan, dtype=float)
    
    # Avoid division by zero; only calibrate where hot != cold
    valid = np.abs(denom) > eps
    t_brightness[valid] = (
        float(t_cold_k) +
        (counts[valid] - cold[valid]) / denom[valid] * (float(t_hot_k) - float(t_cold_k))
    )
    
    return t_brightness

def interactive_calibration_setup() -> Optional[Dict[str, object]]:
    """
    Interactively select a measurement directory, load hot/cold averages,
    extract calibration temperatures, and return setup dict for calibration.
    
    Returns:
        Dict with keys: 'meas_dir', 'avg_hot', 'avg_cold', 't_hot_k', 't_cold_k', 
                        'n_hot', 'n_cold', 'header_meta'
        or None if user cancels or data is invalid.
    """
    project_root = Path(__file__).resolve().parents[2]
    default_data_dir = project_root / "data"
    if not default_data_dir.is_dir():
        default_data_dir = project_root
    
    meas_dir = choose_directory(default_data_dir)
    if meas_dir is None or not meas_dir.is_dir():
        print("No valid measurement directory selected.")
        return None
    
    meas_dir = (meas_dir)
    spec_files = sorted(meas_dir.glob("*.spec"))
    
    if not spec_files:
        print(f"No .spec files found in {meas_dir}")
        return None
    
    hot_files = [p for p in spec_files if "hot" in p.stem.lower()]
    cold_files = [p for p in spec_files if "cold" in p.stem.lower()]
    
    if not hot_files:
        print(f"No hot .spec files found in {meas_dir}")
        return None
    if not cold_files:
        print(f"No cold .spec files found in {meas_dir}")
        return None
    
    print(f"Loading {len(hot_files)} hot files and {len(cold_files)} cold files from {meas_dir}")
    
    try:
        avg_hot, n_hot = accumulate_group_average(hot_files)
        avg_cold, n_cold = accumulate_group_average(cold_files)
    except Exception as e:
        print(f"Error loading spectra: {e}")
        return None
    
    header_meta = parse_header_csv(meas_dir)
    t_hot_k, t_cold_k = extract_hot_cold_kelvin(header_meta)
    
    if t_hot_k is None or t_cold_k is None:
        print("Warning: Could not extract t_hot and t_cold from header metadata.")
        t_hot_k = t_hot_k or 296.0
        t_cold_k = t_cold_k or 77.0
        print(f"Using defaults: T_hot={t_hot_k:.2f} K, T_cold={t_cold_k:.2f} K")
    
    print(f"Calibration temperatures: T_hot={t_hot_k:.2f} K, T_cold={t_cold_k:.2f} K")
    
    return {
        "meas_dir": meas_dir,
        "avg_hot": avg_hot,
        "avg_cold": avg_cold,
        "t_hot_k": float(t_hot_k),
        "t_cold_k": float(t_cold_k),
        "n_hot": int(n_hot),
        "n_cold": int(n_cold),
        "header_meta": header_meta,
    }

def accumulate_group_average(files: List[Path]) -> Tuple[np.ndarray, int]:
    sum_spectrum: Optional[np.ndarray] = None
    total_n = 0

    for spec_path in files:
        _, spectra, _ = load_spec_file(spec_path)
        n_spectra, n_bins = spectra.shape

        if sum_spectrum is None:
            sum_spectrum = np.zeros(n_bins, dtype=float)
        elif sum_spectrum.shape[0] != n_bins:
            raise ValueError(
                f"Bin count mismatch between files; {spec_path} has {n_bins} bins, expected {sum_spectrum.shape[0]}"
            )

        # Use squared counts for all calculations
        spec_sq = spectra.astype(float) ** 2
        sum_spectrum += spec_sq.sum(axis=0)
        total_n += n_spectra

    if sum_spectrum is None or total_n == 0:
        raise ValueError("No spectra found in provided file list.")

    return sum_spectrum / total_n, total_n


def file_mean_spectrum(spec_path: Path) -> np.ndarray:
    _, spectra, _ = load_spec_file(spec_path)
    # Return mean of squared counts
    return (spectra.astype(float) ** 2).mean(axis=0).astype(float)

def save_hot_cold_average_csv(
    meas_dir: Path,
    avg_hot: np.ndarray,
    avg_cold: np.ndarray,
    header_meta: Dict[str, str],
) -> Path:
    if avg_hot.size != avg_cold.size:
        raise ValueError("avg_hot and avg_cold must have the same length.")

    # import build_x_axis at runtime to avoid circular import
    from plotting_utility import build_x_axis

    x_freq, _ = build_x_axis(avg_hot.size, header_meta, x_axis_mode="frequency")
    out_path = meas_dir / f"{meas_dir.name}_hot_cold_avg.csv"

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["frequency_ghz", "cold_load", "hot_load"])
        for freq, cold_val, hot_val in zip(x_freq, avg_cold, avg_hot):
            writer.writerow(
                [f"{float(freq):.9f}", f"{float(cold_val):.9f}", f"{float(hot_val):.9f}"]
            )

    return out_path












