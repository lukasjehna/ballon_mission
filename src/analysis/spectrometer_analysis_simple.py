#!/usr/bin/env python3
from pathlib import Path
import argparse
import numpy as np
import matplotlib.pyplot as plt
from typing import Optional, List, Dict, Tuple

from background_analysis_utils import choose_file, _get_bandwidth_hz
from spectrometer_analysis_utils import load_spec_file

n_bins = 8192


def plot_spectra(
    times: np.ndarray,
    spectra: np.ndarray,
    meta: Dict[str, object],
    spec_path: Path,
    show: bool = True,
    allan: bool = False,
    allan_bin_start: Optional[int] = None,
    allan_bin_end: Optional[int] = None,
) -> Tuple[Path, Path]:
    """
    Plot mean and standard deviation over all spectra (first figure),
    and up to 20 individual spectra (second figure).
    Optionally run Allan analysis.
    """
    n_spectra, n_bins = spectra.shape
    bw_hz = _get_bandwidth_hz(meta, n_bins)
    if bw_hz is None:
        print("Bandwidth header is empty or could not be read. Assuming BW = 4 GHz.")
        bw_hz = 4.0

    # Bottom x-axis is frequency
    x_freq = np.linspace(0.0, bw_hz, n_bins)

    def freq_to_bin(x):
        return x * n_bins / bw_hz

    def bin_to_freq(x):
        return x * bw_hz / n_bins

    # Statistics over all spectra
    mean_all = spectra.mean(axis=0)
    if n_spectra > 1:
        std_all = spectra.std(axis=0, ddof=1)
    else:
        std_all = np.zeros_like(mean_all)

    # Helper: add top bin-index axis, compatible with old Matplotlib
    def add_bin_axis(ax_freq):
        # New Matplotlib: use secondary_xaxis if available
        if hasattr(ax_freq, "secondary_xaxis"):
            ax_bins = ax_freq.secondary_xaxis(
                "top", functions=(freq_to_bin, bin_to_freq)
            )
            ax_bins.set_xlabel("Bin index")
            return ax_bins

        # Fallback for old Matplotlib: use twiny and relabel ticks
        ax_bins = ax_freq.twiny()
        ax_bins.set_xlim(ax_freq.get_xlim())
        freq_ticks = ax_freq.get_xticks()
        bin_ticks = freq_to_bin(freq_ticks)
        ax_bins.set_xticks(freq_ticks)
        ax_bins.set_xticklabels([f"{int(b)}" for b in bin_ticks])
        ax_bins.set_xlabel("Bin index")
        return ax_bins

    # ── Figure 1: mean ±1σ over all spectra ──────────────────────────────
    fig1, ax_freq1 = plt.subplots(figsize=(10, 5))
    ax_freq1.plot(x_freq, mean_all, color="k", linewidth=2, label="mean (all)")
    if n_spectra > 1:
        ax_freq1.fill_between(
            x_freq,
            mean_all - std_all,
            mean_all + std_all,
            color="k",
            alpha=0.2,
            label="±1σ (all)",
        )

    ax_freq1.set_xlabel("Frequency [Hz]")
    ax_freq1.set_ylabel("Counts [arb.]")
    ax_freq1.grid(True, alpha=0.3)
    ax_freq1.legend(loc="best", fontsize="small")
    ax_freq1.set_title("Mean spectrum with ±1σ band")

    # Top x-axis: bins (version‑compatible)
    add_bin_axis(ax_freq1)

    # ── Figure 2: up to 20 individual spectra ────────────────────────────
    fig2, ax_freq2 = plt.subplots(figsize=(10, 5))
    n_to_plot = min(20, n_spectra)
    for i in range(n_to_plot):
        ax_freq2.plot(
            x_freq,
            spectra[i],
            alpha=0.5,
            label=f"spectrum {i}",
        )

    ax_freq2.set_xlabel("Frequency [Hz]")
    ax_freq2.set_ylabel("Counts [arb.]")
    ax_freq2.grid(True, alpha=0.3)
    if n_to_plot <= 10:
        ax_freq2.legend(loc="best", fontsize="small")
    ax_freq2.set_title(f"First {n_to_plot} individual spectra")

    # Top x-axis: bins (version‑compatible)
    add_bin_axis(ax_freq2)

    # Save figures
    plot_dir = Path(__file__).resolve().parent / "plot"
    plot_dir.mkdir(parents=True, exist_ok=True)
    out_path_mean = plot_dir / f"{spec_path.stem}_mean_std.png"
    out_path_individual = plot_dir / f"{spec_path.stem}_single_spectra.png"

    fig1.tight_layout()
    fig2.tight_layout()
    fig1.savefig(out_path_mean)
    fig2.savefig(out_path_individual)

    # Allan analysis (full dataset, but restricted bin range if requested)
    if allan:
        power_path, allan_path, min_allan_time = plot_allan_variance(
            times=times,
            spectra=spectra,
            meta=meta,
            spec_path=spec_path,
            bin_start=allan_bin_start,
            bin_end=allan_bin_end,
            show=False,
        )
        print(f"Saved Allan plots: {power_path}, {allan_path}")
        print(f"Allan time τ_A (min Allan deviation): {min_allan_time:.3g} s")

    if show:
        plt.show()

    return out_path_mean, out_path_individual


def allan_variance_two_sample(data: np.ndarray) -> float:
    """
    Two-sample Allan variance σ²(τ = 1 sample) for a 1D time series.
    """
    y = np.asarray(data, dtype=float)
    if y.size < 2:
        return 0.0
    diffs = np.diff(y)
    return 0.5 * np.mean(diffs**2)


def allan_variance_vs_tau(
    data: np.ndarray,
    dt: float,
    m_max: Optional[int] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Overlapping Allan variance as a function of averaging time τ = m * dt.

    data : 1D array of samples y_k
    dt   : basic sampling interval [s]
    m_max: maximum averaging factor m; defaults to N//4.
    """
    y = np.asarray(data, dtype=float)
    N = y.size
    if N < 3:
        return np.array([]), np.array([])

    if m_max is None:
        m_max = max(1, N // 4)

    m_values = np.unique(
        np.logspace(0, np.log10(m_max), num=min(20, m_max), dtype=int)
    )
    taus = m_values * dt
    sigma2 = np.full_like(taus, np.nan, dtype=float)

    for i, m in enumerate(m_values):
        if N < 2 * m + 1:
            continue
        # Overlapping averages of length m
        kernel = np.ones(m, dtype=float) / m
        y_avg = np.convolve(y, kernel, mode="valid")  # length N - m + 1
        diff = y_avg[1:] - y_avg[:-1]
        sigma2[i] = 0.5 * np.mean(diff**2)

    # Remove NaNs that might occur for largest m
    valid = np.isfinite(sigma2)
    return taus[valid], sigma2[valid]


def plot_allan_variance(
    times: np.ndarray,
    spectra: np.ndarray,
    meta: Dict[str, object],
    spec_path: Path,
    bin_start: Optional[int] = None,
    bin_end: Optional[int] = None,
    show: bool = True,  # kept for compatibility, but show handled by caller
) -> Tuple[Path, Path, float]:
    """
    Compute and plot Allan variance of total power vs time, and
    Allan deviation as a function of averaging time τ. Also print
    the Allan time τ_A (τ at which Allan deviation is minimal).

    bin_start / bin_end specify the bin index range used to compute
    total power per spectrum; defaults to the full bin range.
    """
    # Use only spectra times; meas_spectra() stored one extra timestamp
    t_spec = times[1:]
    if t_spec.shape[0] != spectra.shape[0]:
        raise ValueError("Mismatch between times and spectra length")

    # Select bin range for total power
    _, n_bins = spectra.shape
    if bin_start is None:
        bin_start = 0
    if bin_end is None:
        bin_end = n_bins
    bin_start = max(0, min(bin_start, n_bins - 1))
    bin_end = max(bin_start + 1, min(bin_end, n_bins))

    # 1D series: mean counts per spectrum
    total_power = spectra.mean(axis=1).astype(float)

    # Basic two-sample Allan variance (τ = 1 sample)
    sigma2_2s = allan_variance_two_sample(total_power)

    # Derive nominal sampling interval dt [s]
    dt_array = np.diff(t_spec)
    dt = float(np.median(dt_array)) if dt_array.size > 0 else 1.0

    # If integration time is known, prefer that
    int_time_ms = meta.get("int_time_ms")
    if isinstance(int_time_ms, int) and int_time_ms > 0:
        dt = int_time_ms / 1000.0

    # Allan variance vs averaging time τ
    taus, sigma2_tau = allan_variance_vs_tau(total_power, dt)
    if taus.size == 0:
        print("Not enough data points to compute Allan variance vs τ.")
        plot_dir = Path(__file__).resolve().parent / "plot"
        dummy_path = plot_dir / f"{spec_path.stem}_allan.png"
        return dummy_path, dummy_path, dt  # fallback, should rarely happen

    sigma_tau = np.sqrt(sigma2_tau)

    # Allan time: τ at minimum Allan deviation
    idx_min = int(np.argmin(sigma_tau))
    allan_time = float(taus[idx_min])
    print(f"Allan variance (two-sample, τ=1): {sigma2_2s:.3g}")
    print(f"Allan time τ_A (min Allan deviation): {allan_time:.3g} s")

    # ── Plot 1: total power vs time ───────────────────────────────────────
    fig1, ax1 = plt.subplots(figsize=(6, 4))
    ax1.plot(t_spec - t_spec[0], total_power, marker="o", linestyle="-")
    ax1.set_xlabel("Time since start [s]")
    ax1.set_ylabel("Mean counts [arb.]")
    ax1.grid(True, alpha=0.3)
    ax1.set_title(f"Total power, Allan var (two-sample) = {sigma2_2s:.3g}")

    # ── Plot 2: Allan deviation vs τ ─────────────────────────────────────
    fig2, ax2 = plt.subplots(figsize=(6, 4))
    ax2.loglog(taus, sigma_tau, marker="o", linestyle="-")
    ax2.axvline(allan_time, color="r", linestyle="--",
                label=f"τ_A ≈ {allan_time:.3g} s")
    ax2.set_xlabel("Averaging time τ [s]")
    ax2.set_ylabel("Allan deviation σ(τ)")
    ax2.grid(True, which="both", alpha=0.3)
    ax2.legend(loc="best", fontsize="small")
    ax2.set_title("Allan deviation vs averaging time")

    plot_dir = Path(__file__).resolve().parent / "plot"
    plot_dir.mkdir(parents=True, exist_ok=True)
    out_path_time = plot_dir / f"{spec_path.stem}_allan_series.png"
    out_path_tau = plot_dir / f"{spec_path.stem}_allan_tau.png"

    fig1.tight_layout()
    fig2.tight_layout()
    fig1.savefig(out_path_time)
    fig2.savefig(out_path_tau)

    # Do NOT call plt.show() here; caller handles it so all figures show together
    return out_path_time, out_path_tau, allan_time


def plot_overlay_spectra(
    times: np.ndarray,
    spectra: np.ndarray,
    meta: Dict[str, object],
    spec_path: Path,
    show: bool = True,
) -> Path:
    """
    Legacy-style plot: overlay all spectra in one figure (bin index on x-axis).
    """
    n_spectra, n_bins = spectra.shape
    x = np.arange(n_bins)

    fig, ax = plt.subplots(figsize=(10, 5))
    if n_spectra == 1:
        ax.plot(x, spectra[0], label="spectrum 0")
    else:
        for i in range(n_spectra):
            ax.plot(x, spectra[i], alpha=0.4, label=f"spectrum {i}")

    title_parts = [spec_path.name]
    bw = meta.get("bandwidth")
    if isinstance(bw, str) and bw:
        title_parts.append(f"bw={bw}")
    t_int = meta.get("int_time_ms")
    if isinstance(t_int, int):
        title_parts.append(f"t_int={t_int} ms")
    ax.set_title(" | ".join(title_parts))

    ax.set_xlabel("Bin index")
    ax.set_ylabel("Counts [arb.]")
    ax.grid(True, alpha=0.3)
    if n_spectra <= 10:
        ax.legend(loc="best", fontsize="small")

    plot_dir = Path(__file__).resolve().parent / "plot"
    plot_dir.mkdir(parents=True, exist_ok=True)
    out_path = plot_dir / f"{spec_path.stem}.png"

    fig.tight_layout()
    fig.savefig(out_path)

    if show:
        plt.show()

    return out_path


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Plot spectra from a .spec file produced by the spectrometer UDP server"
    )
    parser.add_argument(
        "--allan-bin-range",
        type=str,
        default=":",
        help=(
            "Bin index range to use for Allan analysis as 'start:end' "
            "(0-based, end exclusive). Default ':' = full bin range."
        ),
    )
    parser.add_argument(
        "--allan",
        action="store_true",
        help="Also compute (and optionally plot) Allan variance of the spectra.",
    )
    parser.add_argument(
        "--mode",
        choices=["stats", "overlay", "both"],
        default="stats",
        help=(
            "Plot mode: 'stats' (mean/std + single spectra), "
            "'overlay' (all spectra in one figure), or 'both'."
        ),
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save plots without opening GUI windows.",
    )
    args = parser.parse_args(argv)

    # Always show file dialog
    data_dir = Path(__file__).resolve().parent.parent / "data"
    spec_path = choose_file(
        data_dir,
        title="Select spectrum file",
        filetypes=[
            ("Spectra files", "*.spec"),
            ("All files", "*.*"),
        ],
    )
    if spec_path is None:
        print("No file selected. Exiting.")
        return

    # Load data ONCE (expensive operation)
    times, spectra, meta = load_spec_file(spec_path)

    # Print basic header / metadata information
    n_spectra = meta.get("n_spectra")
    int_time_ms = meta.get("int_time_ms")
    bandwidth = meta.get("bandwidth")
    header_line = meta.get("header_line")
    print("=== Spectrometer file header ===")
    print(f"File: {spec_path}")
    print(f"Raw header: {header_line}")
    hs = meta.get("header_source")
    if hs and hs != "inline":
        print(f"Header source: dedicated file -> {hs}")
    else:
        print("Header source: inline header in .spec file")
    print(f"Number of spectra: {n_spectra}")
    if int_time_ms is not None:
        print(f"Integration time per spectrum: {int_time_ms} ms")
    else:
        print("Integration time per spectrum: unknown")
    if bandwidth is not None:
        print(f"Bandwidth: {bandwidth}")
    else:
        print("Bandwidth: unknown")
    print("================================\n")

    n_total = spectra.shape[0]
    _, n_bins = spectra.shape

    def _parse_bin_range(rng: str, n_total_bins: int) -> Tuple[int, int]:
        rng = rng.strip()
        if ":" in rng:
            start_str, end_str = rng.split(":", 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else n_total_bins
        else:
            # single index "k" -> [k, k+1)
            idx = int(rng)
            start, end = idx, idx + 1
        start = max(0, start)
        end = min(n_total_bins, end)
        if end <= start:
            end = min(n_total_bins, start + 1)
        return start, end

    allan_bin_start, allan_bin_end = _parse_bin_range(args.allan_bin_range, n_bins)
    args.allan_bin_start = allan_bin_start
    args.allan_bin_end = allan_bin_end

    show_plots = not args.no_show

    if args.mode in ("stats", "both"):
        out_mean, out_individual = plot_spectra(
            times=times,
            spectra=spectra,
            meta=meta,
            spec_path=spec_path,
            show=False,
            allan=args.allan,
            allan_bin_start=args.allan_bin_start,
            allan_bin_end=args.allan_bin_end,
        )
        print(f"Saved mean/std plot to {out_mean}")
        print(f"Saved individual spectra plot to {out_individual}")
    elif args.allan:
        power_path, allan_path, min_allan_time = plot_allan_variance(
            times=times,
            spectra=spectra,
            meta=meta,
            spec_path=spec_path,
            bin_start=args.allan_bin_start,
            bin_end=args.allan_bin_end,
            show=False,
        )
        print(f"Saved Allan plots: {power_path}, {allan_path}")
        print(f"Allan time τ_A (min Allan deviation): {min_allan_time:.3g} s")

    if args.mode in ("overlay", "both"):
        out_overlay = plot_overlay_spectra(
            times=times,
            spectra=spectra,
            meta=meta,
            spec_path=spec_path,
            show=False,
        )
        print(f"Saved overlay plot to {out_overlay}")

    if show_plots:
        plt.show()


if __name__ == "__main__":
    main()


