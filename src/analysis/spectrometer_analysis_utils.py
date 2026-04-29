#!/usr/bin/env python3

from pathlib import Path
import csv
import re
import tkinter as tk
from tkinter import filedialog
from typing import Optional, List, Dict, Tuple

import numpy as np
import matplotlib.pyplot as plt


def _parse_header_line(header: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}
    parts = [p.strip() for p in header.split(",") if p.strip()]
    for part in parts:
        if ":" in part:
            key, val = part.split(":", 1)
            meta[key.strip().lower()] = val.strip()
    return meta


def _find_dedicated_header_file(spec_path: Path) -> Optional[Path]:
    stem = spec_path.stem
    run_stem = stem
    for suffix in ("_hot", "_cold", "_sky", "_amb"):
        if run_stem.endswith(suffix):
            run_stem = run_stem[: -len(suffix)]
            break

    candidates: List[Path] = []
    preferred = spec_path.parent / f"{run_stem}_pi_lab_header.csv"
    if preferred.exists():
        candidates.append(preferred)

    candidates.extend(sorted(spec_path.parent.glob(f"{run_stem}*header*.csv")))
    candidates.extend(sorted(spec_path.parent.glob("*header*.csv")))

    seen = set()
    for p in candidates:
        rp = p.resolve()
        if rp not in seen and p.is_file():
            seen.add(rp)
            return p
    return None


def _parse_dedicated_header_csv(header_csv: Path) -> Dict[str, str]:
    raw: Dict[str, str] = {}
    with header_csv.open("r", newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 2:
                continue
            k = row[0].strip().lower()
            v = row[1].strip()
            if k == "key" and v.lower() == "value":
                continue
            raw[k] = v

    mapped: Dict[str, str] = {}
    if "n_spectra" in raw:
        mapped["number of spectra"] = raw["n_spectra"]
    if "integration_time_ms" in raw:
        mapped["integration time"] = raw["integration_time_ms"]
    if "bandwidth" in raw:
        mapped["bandwidth"] = raw["bandwidth"]

    for k, v in raw.items():
        mapped.setdefault(k, v)
    return mapped


def load_spec_file(spec_path: Path):
    with spec_path.open("rb") as f:
        file_bytes = f.read()

    header_line = ""
    meta_raw: Dict[str, str] = {}
    payload = file_bytes
    header_source = "inline"

    nl = file_bytes.find(b"\n")
    if nl >= 0:
        first_line = file_bytes[:nl].decode("ascii", errors="replace").strip()
        parsed = _parse_header_line(first_line)
        if "number of spectra" in parsed:
            header_line = first_line
            meta_raw = parsed
            payload = file_bytes[nl + 1 :]

    if "number of spectra" not in meta_raw:
        header_csv = _find_dedicated_header_file(spec_path)
        if header_csv is None:
            raise ValueError(
                f"Missing inline header in {spec_path.name} and no dedicated header CSV "
                f"found in {spec_path.parent}"
            )
        meta_raw = _parse_dedicated_header_csv(header_csv)
        header_line = f"[dedicated header] {header_csv.name}"
        header_source = str(header_csv)

    try:
        n_spectra_str = meta_raw.get("number of spectra", "")
        m = re.search(r"\d+", n_spectra_str)
        if m is None:
            raise ValueError("No integer found")
        n_spectra = int(m.group(0))
    except Exception as exc:
        raise ValueError(
            f"Could not parse 'number of spectra' from metadata: {header_line!r}"
        ) from exc

    int_time_ms: Optional[int] = None
    s = meta_raw.get("integration time", "")
    if s:
        m = re.search(r"[-+]?\d*\.?\d+", s)
        if m is not None:
            try:
                int_time_ms = int(float(m.group(0)))
            except ValueError:
                int_time_ms = None

    bandwidth = meta_raw.get("bandwidth")
    rest = payload

    n_times = n_spectra + 1
    times_bytes = 8 * n_times
    if len(rest) < times_bytes:
        raise ValueError(f"File too short for expected {n_times} timestamps: {spec_path}")

    times_raw = rest[:times_bytes]
    spectra_raw = rest[times_bytes:]

    times = np.frombuffer(times_raw, dtype=">f8").astype("float64")

    if len(spectra_raw) % 4 != 0:
        raise ValueError(
            f"Spectra block length {len(spectra_raw)} is not a multiple of 4 bytes"
        )

    total_samples = len(spectra_raw) // 4
    if total_samples % n_spectra != 0:
        raise ValueError(
            f"Total samples {total_samples} not divisible by n_spectra={n_spectra}"
        )

    n_bins = total_samples // n_spectra
    spectra = (
        np.frombuffer(spectra_raw, dtype=">i4")
        .astype("int64")
        .reshape(n_spectra, n_bins)
    )

    meta: Dict[str, object] = {
        "header_line": header_line,
        "header_source": header_source,
        "n_spectra": n_spectra,
        "int_time_ms": int_time_ms,
        "bandwidth": bandwidth,
    }
    return times, spectra, meta


def choose_directory(initialdir: Path) -> Optional[Path]:
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(
        title="Select measurement folder (contains .spec + *_header.csv)",
        initialdir=str(initialdir),
    )
    root.destroy()
    return Path(path) if path else None


def parse_header_csv(meas_dir: Path) -> Dict[str, str]:
    header_files = sorted(meas_dir.glob("*_header.csv"))
    if not header_files:
        return {}

    header_path = header_files[0]
    try:
        with header_path.open("r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f.readlines() if ln.strip()]
    except OSError:
        return {}

    meta: Dict[str, str] = {}
    if not lines:
        return meta

    if "\t" in lines[0] and "=" in lines[0]:
        for part in lines[0].split("\t"):
            if "=" in part:
                k, v = part.split("=", 1)
                meta[k.strip()] = v.strip()
        return meta

    for line in lines:
        if "," not in line:
            continue
        k, v = line.split(",", 1)
        key = k.strip()
        val = v.strip()
        if key.lower() == "key" and val.lower() == "value":
            continue
        if key:
            meta[key] = val
    return meta


def _parse_frequency_ghz(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    s = raw.strip().replace(" ", "").replace(",", ".")
    if not s:
        return None

    lower = s.lower()
    num = "".join(ch for ch in s if ch.isdigit() or ch in ".-+eE")
    if not num:
        return None
    try:
        value = float(num)
    except ValueError:
        return None

    if "ghz" in lower:
        return value
    if "mhz" in lower:
        return value / 1e3
    if "khz" in lower:
        return value / 1e6
    if "hz" in lower:
        return value / 1e9
    return value


def _despike_1d(y: np.ndarray, window: int = 5, sigma_thresh: float = 6.0) -> Tuple[np.ndarray, int]:
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


def _despike_1d_in_window(
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

    filtered, removed = _despike_1d(out[i0:i1 + 1], window=window, sigma_thresh=sigma_thresh)
    out[i0:i1 + 1] = filtered
    return out, removed


def _get_header_value(header_meta: Dict[str, str], *keys: str) -> Optional[str]:
    meta_lc = {k.lower(): v for k, v in header_meta.items()}
    for k in keys:
        v = meta_lc.get(k.lower())
        if v is not None:
            return v
    return None


def _get_lo_ghz(header_meta: Dict[str, str]) -> Optional[float]:
    raw = _get_header_value(header_meta, "f_LO", "f_RX")
    return _parse_frequency_ghz(raw)


def _get_bw_ghz(header_meta: Dict[str, str]) -> Optional[float]:
    raw = _get_header_value(header_meta, "BW", "bandwidth")
    return _parse_frequency_ghz(raw)


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

def _build_x_axis(n_bins: int, header_meta: Dict[str, str], x_axis_mode: str) -> Tuple[np.ndarray, str]:
    if x_axis_mode == "bins":
        return np.arange(n_bins), "Bin index"

    bw_ghz = _get_bw_ghz(header_meta)
    if bw_ghz is None or bw_ghz <= 0:
        return np.arange(n_bins), "Bin index"

    x_if = np.linspace(0.0, bw_ghz, n_bins, endpoint=False)
    return x_if, "f_IF [GHz]"


def _apply_x_axis_format(
    ax: plt.Axes,
    header_meta: Dict[str, str],
    x_axis_mode: str,
    default_label: str,
) -> None:
    if x_axis_mode == "bins" or default_label == "Bin index":
        ax.set_xlabel("Bin index")
        return

    f_lo_ghz = _get_lo_ghz(header_meta)
    if x_axis_mode == "frequency":
        ax.set_xlabel("f_IF [GHz]" if f_lo_ghz is None else f"f_IF [GHz] (f_LO={f_lo_ghz:.6f} GHz)")
        return

    if x_axis_mode == "sidebands":
        if f_lo_ghz is None:
            ax.set_xlabel("f_IF [GHz] (f_LO missing)")
            return

        ticks_if = ax.get_xticks()
        ax.set_xticks(ticks_if)
        ax.set_xticklabels([f"{(f_lo_ghz + t):.3f}" for t in ticks_if])
        ax.set_xlabel("f_USB [GHz]")

        ax_top = ax.twiny()
        ax_top.set_xlim(ax.get_xlim())
        ax_top.set_xticks(ticks_if)
        ax_top.set_xticklabels([f"{(f_lo_ghz - t):.3f}" for t in ticks_if])
        ax_top.set_xlabel("f_LSB [GHz]")


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


def plot_hot_cold_average(
    meas_dir: Path,
    avg_hot: np.ndarray,
    n_hot: int,
    avg_cold: np.ndarray,
    n_cold: int,
    header_meta: Dict[str, str],
    x_axis_mode: str = "frequency",
) -> Path:
    x, x_label = _build_x_axis(avg_hot.size, header_meta, x_axis_mode)

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x, avg_hot, label=f"hot (N={n_hot})", color="tab:red")
    ax.plot(x, avg_cold, label=f"cold (N={n_cold})", color="tab:blue")
    _apply_x_axis_format(ax, header_meta, x_axis_mode, x_label)
    ax.set_ylabel("Counts [arb.]")
    ax.grid(True, alpha=0.3)

    f_lo = _get_header_value(header_meta, "f_LO", "f_RX")
    bw = _get_header_value(header_meta, "BW", "bandwidth")
    t_hot = header_meta.get("t_hot")
    t_cold = header_meta.get("t_cold")

    title_parts: List[str] = []
    if f_lo:
        title_parts.append(f"f_LO={f_lo}")
    if bw:
        title_parts.append(f"BW={bw}")
    if t_hot and t_cold:
        title_parts.append(f"T_hot={t_hot}, T_cold={t_cold}")
    ax.set_title("Hot vs cold average | " + " | ".join(title_parts) if title_parts else "Hot vs cold average spectra")

    ax.legend(loc="best")
    out_path = meas_dir / f"{meas_dir.name}_hot_cold_avg.png"
    fig.tight_layout()
    fig.savefig(out_path)
    return out_path


def plot_all_hot_cold_lines(
    meas_dir: Path,
    hot_files: List[Path],
    cold_files: List[Path],
    header_meta: Dict[str, str],
    x_axis_mode: str = "frequency",
) -> Path:
    fig, ax = plt.subplots(figsize=(10, 5))
    x_label = "Bin index"

    total_hot_spectra = 0
    for spec_path in hot_files:
        _, spectra, _ = load_spec_file(spec_path)
        n_spectra, n_bins = spectra.shape
        x, x_label = _build_x_axis(n_bins, header_meta, x_axis_mode)
        for i in range(n_spectra):
            ax.plot(
                x, (spectra[i, :].astype(float) ** 2), color="tab:red", alpha=0.15, linewidth=0.5,
                label="hot spectra" if total_hot_spectra == 0 else None
            )
            total_hot_spectra += 1

    total_cold_spectra = 0
    for spec_path in cold_files:
        _, spectra, _ = load_spec_file(spec_path)
        n_spectra, n_bins = spectra.shape
        x, x_label = _build_x_axis(n_bins, header_meta, x_axis_mode)
        for i in range(n_spectra):
            ax.plot(
                x, (spectra[i, :].astype(float) ** 2), color="tab:blue", alpha=0.15, linewidth=0.5,
                label="cold spectra" if total_cold_spectra == 0 else None
            )
            total_cold_spectra += 1

    _apply_x_axis_format(ax, header_meta, x_axis_mode, x_label)
    ax.set_ylabel("Counts [arb.]")
    ax.grid(True, alpha=0.3)

    f_lo = _get_header_value(header_meta, "f_LO", "f_RX")
    bw = _get_header_value(header_meta, "BW", "bandwidth")
    title_parts: List[str] = []
    if f_lo:
        title_parts.append(f"f_LO={f_lo}")
    if bw:
        title_parts.append(f"BW={bw}")
    ax.set_title("All hot/cold spectra | " + " | ".join(title_parts) if title_parts else "All hot/cold spectra (all frames)")

    ax.legend(loc="best")
    out_path = meas_dir / f"{meas_dir.name}_hot_cold_lines.png"
    fig.tight_layout()
    fig.savefig(out_path)
    return out_path


def _resolve_measurement_dir_with_specs(meas_dir: Path) -> Path:
    if any(meas_dir.glob("*.spec")):
        return meas_dir
    subdirs = [d for d in meas_dir.iterdir() if d.is_dir()]
    candidates = [d for d in subdirs if any(d.glob("*.spec"))]
    if not candidates:
        return meas_dir
    chosen = sorted(candidates, key=lambda p: (p.name, p.stat().st_mtime))[-1]
    print(f"No .spec files in {meas_dir}; using subfolder {chosen}")
    return chosen


def _parse_temperature_value(raw: Optional[str]) -> Optional[float]:
    if raw is None:
        return None
    s = raw.strip().replace(",", ".")
    if not s:
        return None

    lower = s.lower()
    is_celsius = ("c" in lower) and ("k" not in lower)
    num = "".join(ch for ch in s if ch.isdigit() or ch in ".-+eE")
    if not num:
        return None
    try:
        value = float(num)
    except ValueError:
        return None
    return value + 273.15 if is_celsius else value


def _extract_hot_cold_kelvin(header_meta: Dict[str, str]) -> Tuple[Optional[float], Optional[float]]:
    meta_lc = {k.lower(): v for k, v in header_meta.items()}
    t_hot_raw = meta_lc.get("t_hot") or meta_lc.get("thot")
    t_cold_raw = meta_lc.get("t_cold") or meta_lc.get("tcold")
    return _parse_temperature_value(t_hot_raw), _parse_temperature_value(t_cold_raw)


def plot_noise_temperature(
    meas_dir: Path,
    avg_hot: np.ndarray,
    avg_cold: np.ndarray,
    header_meta: Dict[str, str],
    x_axis_mode: str = "frequency",
    y_min: float = 0.0,
    y_max: float = 30000.0,
    despike_enabled: bool = False,
) -> Optional[Path]:
    t_hot_k, t_cold_k = _extract_hot_cold_kelvin(header_meta)
    if t_hot_k is None or t_cold_k is None:
        print("Skipping noise-temperature plot: missing t_hot/t_cold in header.")
        return None

    t_noise = compute_noise_temperature(avg_hot, avg_cold, t_hot_k, t_cold_k)

    if despike_enabled:
        t_noise, _ = _despike_1d(t_noise)

    fig, ax = plt.subplots(figsize=(10, 5))
    x, x_label = _build_x_axis(t_noise.size, header_meta, x_axis_mode)
    ax.plot(x, t_noise, color="tab:green", linewidth=1.0)
    _apply_x_axis_format(ax, header_meta, x_axis_mode, x_label)
    ax.set_ylabel("Noise temperature [K]")
    ax.set_ylim(y_min, y_max)
    ax.grid(True, alpha=0.3)

    if np.any(np.isfinite(t_noise)):
        i_start = 200
        i_stop = 1851  # Python end index is exclusive, so 1851 includes bin 1850
        t_noise_window = t_noise[i_start:i_stop]

        mean_window = float(np.nanmean(t_noise_window)) if np.any(np.isfinite(t_noise_window)) else float("nan")

        ax.set_title(
            f" T_hot={t_hot_k:.2f} K, "
            f"T_cold={t_cold_k:.2f} K, mean(200..1850)={mean_window:.2f} K"
        )
    else:
        ax.set_title(f" T_hot={t_hot_k:.2f} K, T_cold={t_cold_k:.2f} K (no valid bins)")
    out_path = meas_dir / f"{meas_dir.name}_noise_temperature.png"
    fig.tight_layout()
    fig.savefig(out_path)
    return out_path


def print_header_meta(header_meta: Dict[str, str]) -> None:
    if not header_meta:
        print("Header metadata: <none found>")
        return
    print("Header metadata:")
    for k in sorted(header_meta.keys()):
        print(f"  {k}={header_meta[k]}")


def save_hot_cold_average_csv(
    meas_dir: Path,
    avg_hot: np.ndarray,
    avg_cold: np.ndarray,
    header_meta: Dict[str, str],
) -> Path:
    if avg_hot.size != avg_cold.size:
        raise ValueError("avg_hot and avg_cold must have the same length.")

    x_freq, _ = _build_x_axis(avg_hot.size, header_meta, x_axis_mode="frequency")
    out_path = meas_dir / f"{meas_dir.name}_hot_cold_avg.csv"

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["frequency_ghz", "cold_load", "hot_load"])
        for freq, cold_val, hot_val in zip(x_freq, avg_cold, avg_hot):
            writer.writerow(
                [f"{float(freq):.9f}", f"{float(cold_val):.9f}", f"{float(hot_val):.9f}"]
            )

    return out_path


def add_relative_frequency_top_axis(
    ax: plt.Axes,
    center_freq_ghz: float,
    label: str = "f_RX - f_center [GHz]",
    decimals: int = 3,
) -> plt.Axes:
    ticks = ax.get_xticks()
    ax_top = ax.twiny()
    ax_top.set_xlim(ax.get_xlim())
    ax_top.set_xticks(ticks)
    d = max(0, int(decimals))
    fmt = f"{{:.{d}f}}"
    ax_top.set_xticklabels([fmt.format(t - center_freq_ghz) for t in ticks])
    ax_top.set_xlabel(label)
    return ax_top


def launch_interactive_noise_temperature_browser(
    entries: List[Dict[str, object]],
    bin_start: int = 200,
    bin_stop: int = 1850,
    despike_enabled: bool = False,
    despike_window: int = 5,
    despike_sigma: float = 6.0,
    center_freq_ghz: Optional[float] = None,
) -> Optional[plt.Figure]:
    if not entries:
        return None

    from matplotlib.widgets import Button, Slider

    fig, ax = plt.subplots(figsize=(11, 5))
    plt.subplots_adjust(bottom=0.30 if despike_enabled else 0.18)

    (line,) = ax.plot([], [], color="tab:green", linewidth=1.0)
    span = ax.axvspan(0, 0, color="tab:gray", alpha=0.12, lw=0)
    ax.set_ylabel("Noise temperature [K]")
    ax.grid(True, alpha=0.3)

    ax_top = ax.twiny()
    ax_top.set_xlim(ax.get_xlim())
    ax_top.set_xlabel("Bin index")

    state = {
        "idx": 0,
        "dsp_window": max(3, int(despike_window) | 1),
        "dsp_sigma": max(0.1, float(despike_sigma)),
    }

    slider_w = None
    slider_s = None

    if despike_enabled:
        ax_w = fig.add_axes([0.10, 0.09, 0.50, 0.03])
        ax_s = fig.add_axes([0.10, 0.04, 0.50, 0.03])
        slider_w = Slider(ax_w, "despike window", 3, 51, valinit=state["dsp_window"], valstep=1)
        slider_s = Slider(ax_s, "despike sigma", 0.5, 20.0, valinit=state["dsp_sigma"])

    def _get_bin_window_for_entry(e: Dict[str, object]) -> Tuple[int, int]:
        """Get bin_start and bin_stop for current entry, using per-entry values or defaults."""
        if "bin_start" in e and "bin_stop" in e:
            return int(e["bin_start"]), int(e["bin_stop"])
        return bin_start, bin_stop

    def _compute_t_noise_for_entry(e: Dict[str, object]) -> Tuple[np.ndarray, int]:
        entry_bin_start, entry_bin_stop = _get_bin_window_for_entry(e)

        # Backward-compatible path: precomputed t_noise only
        if "avg_hot" not in e or "avg_cold" not in e:
            y_pre = np.asarray(e.get("t_noise", []), dtype=float)
            if despike_enabled:
                y_pre, removed = _despike_1d_in_window(
                    y_pre,
                    bin_start=entry_bin_start,
                    bin_stop=entry_bin_stop,
                    window=state["dsp_window"],
                    sigma_thresh=state["dsp_sigma"],
                )
                return y_pre, int(removed)
            return y_pre, int(e.get("removed_spikes", 0))

        hot = np.asarray(e["avg_hot"], dtype=float)
        cold = np.asarray(e["avg_cold"], dtype=float)
        if hot.size == 0 or cold.size != hot.size:
            return np.full_like(hot, np.nan, dtype=float), 0

        removed = 0
        if despike_enabled:
            hot, r_h = _despike_1d_in_window(
                hot,
                bin_start=entry_bin_start,
                bin_stop=entry_bin_stop,
                window=state["dsp_window"],
                sigma_thresh=state["dsp_sigma"],
            )
            cold, r_c = _despike_1d_in_window(
                cold,
                bin_start=entry_bin_start,
                bin_stop=entry_bin_stop,
                window=state["dsp_window"],
                sigma_thresh=state["dsp_sigma"],
            )
            removed = int(r_h + r_c)

        t_hot_k = e.get("t_hot_k")
        t_cold_k = e.get("t_cold_k")
        if (t_hot_k is None or t_cold_k is None) and isinstance(e.get("header_meta"), dict):
            h = e["header_meta"]
            t_hot_k, t_cold_k = _extract_hot_cold_kelvin(h)

        if t_hot_k is None or t_cold_k is None:
            return np.full_like(hot, np.nan, dtype=float), removed

        t_noise = compute_noise_temperature(hot, cold, float(t_hot_k), float(t_cold_k))
        return t_noise, removed

    def _get_x_axis_for_entry(e: Dict[str, object], n_bins: int) -> Tuple[np.ndarray, str]:
        header_meta = e.get("header_meta")
        if isinstance(header_meta, dict):
            x_if, lbl = _build_x_axis(n_bins, header_meta, x_axis_mode="frequency")
            x_if = np.asarray(x_if, dtype=float)
            if x_if.size == n_bins and np.all(np.isfinite(x_if)) and lbl != "Bin index":
                return x_if, "f_IF [GHz]"
        return np.arange(n_bins, dtype=float), "Bin index"

    def _update_top_bin_axis(x: np.ndarray) -> None:
        ticks = ax.get_xticks()
        ax_top.set_xlim(ax.get_xlim())
        ax_top.set_xticks(ticks)

        if x.size <= 1:
            ax_top.set_xticklabels(["0"] * len(ticks))
            return

        if np.allclose(x, np.arange(x.size, dtype=float)):
            bin_vals = np.rint(ticks).astype(int)
        else:
            step = (x[-1] - x[0]) / max(1, x.size - 1)
            bin_vals = np.rint((ticks - x[0]) / step).astype(int) if step != 0 else np.zeros_like(ticks, dtype=int)

        bin_vals = np.clip(bin_vals, 0, x.size - 1)
        ax_top.set_xticklabels([str(int(v)) for v in bin_vals])

    def _draw() -> None:
        e = entries[state["idx"]]
        entry_bin_start, entry_bin_stop = _get_bin_window_for_entry(e)
        y, removed_spikes = _compute_t_noise_for_entry(e)
        x, x_label = _get_x_axis_for_entry(e, y.size)

        line.set_data(x, y)
        ax.set_xlim((0, 0.8) if x.size > 1 else (0, 2))
        ax.set_xlabel(x_label)
        ax.set_ylim(3000.0, 35000)

        i0 = max(0, int(entry_bin_start))
        i1 = min(y.size, int(entry_bin_stop) + 1)
        w = y[i0:i1]
        mean_w = float(np.nanmean(w)) if np.any(np.isfinite(w)) else float("nan")

        if x.size > 0:
            l_idx = max(0, min(y.size - 1, i0))
            r_idx = max(0, min(y.size - 1, max(i0, i1 - 1)))
            x_l = float(x[l_idx]); x_r = float(x[r_idx])
            if x_r <= x_l and y.size > 1:
                step = float((x[-1] - x[0]) / max(1, y.size - 1))
                x_r = x_l + abs(step)
            span.set_x(x_l)
            span.set_width(max(0.0, x_r - x_l))

        _update_top_bin_axis(x)

        spikes_txt = ""
        if despike_enabled:
            spikes_txt = (
                f", removed spikes={removed_spikes}, "
                f"w={state['dsp_window']}, sigma={state['dsp_sigma']:.2f}"
            )

        ax.set_title(
            f"{e.get('name', '<unknown>')} | f_RX={float(e.get('f_rx_ghz', float('nan'))):.3f} GHz | "
            f"T_hot={float(e.get('t_hot_k', float('nan'))):.2f} K, "
            f"T_cold={float(e.get('t_cold_k', float('nan'))):.2f} K, "
            f"mean({entry_bin_start}..{entry_bin_stop})={mean_w:.2f} K{spikes_txt}"
        )
        fig.canvas.draw_idle()

    def _step(delta: int) -> None:
        state["idx"] = (state["idx"] + delta) % len(entries)
        _draw()

    def _on_slider(_val) -> None:
        if slider_w is not None:
            w = int(round(slider_w.val))
            if w < 3:
                w = 3
            if w % 2 == 0:
                w += 1
            state["dsp_window"] = w
        if slider_s is not None:
            state["dsp_sigma"] = max(0.1, float(slider_s.val))
        _draw()

    ax_prev = fig.add_axes([0.76, 0.02, 0.10, 0.07])
    ax_next = fig.add_axes([0.87, 0.02, 0.10, 0.07])
    btn_prev = Button(ax_prev, "Prev")
    btn_next = Button(ax_next, "Next")
    btn_prev.on_clicked(lambda _evt: _step(-1))
    btn_next.on_clicked(lambda _evt: _step(+1))

    if slider_w is not None:
        slider_w.on_changed(_on_slider)
    if slider_s is not None:
        slider_s.on_changed(_on_slider)

    def _on_key(evt) -> None:
        if evt.key in ("left", "up"):
            _step(-1)
        elif evt.key in ("right", "down"):
            _step(+1)

    fig.canvas.mpl_connect("key_press_event", _on_key)
    fig._noise_browser_buttons = (btn_prev, btn_next)
    fig._noise_browser_sliders = (slider_w, slider_s)

    _draw()
    return fig
