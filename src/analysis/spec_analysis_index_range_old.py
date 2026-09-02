# Run either python -m spectrometer_analysis path/to/20251119090740.spec or python spectrometer_analysis.py, in which case a dialog opens to select a .spec file from your data directory.​
# python run_spectrometer_analysis.py measurement.spec --index-range 100:200, quit to end. close plot windows after chaning.
# --no-interactive for old version
#!/usr/bin/env python3
from pathlib import Path
import argparse
import struct
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.widgets import Cursor
from typing import Optional, List, Dict, Tuple
from src.analysis_core import choose_file  # reuse GUI file picker

def _parse_header_line(header: str) -> Dict[str, str]:
    """
    Parse a header of the form:
    "number of spectra: N, integration time: Xms, bandwidth: Y"
    into a dict with lowercase keys.
    """
    meta: Dict[str, str] = {}
    parts = [p.strip() for p in header.split(",") if p.strip()]
    for part in parts:
        if ":" in part:
            key, val = part.split(":", 1)
            meta[key.strip().lower()] = val.strip()
    return meta


def load_spec_file(spec_path: Path):
    """
    Load a .spec file created by SpectrometerState.measure().

    Returns:
        times: 1D np.ndarray of shape (n_spectra + 1,) with absolute times [s]
        spectra: 2D np.ndarray of shape (n_spectra, n_bins) with int counts
        meta: dict with parsed header fields
    """
    with spec_path.open("rb") as f:
        header_line = f.readline().decode("ascii", errors="replace").strip()
        meta_raw = _parse_header_line(header_line)

        # number of spectra: N
        try:
            n_spectra_str = meta_raw.get("number of spectra", "")
            n_spectra = int(n_spectra_str.split()[0])
        except Exception as exc:
            raise ValueError(
                f"Could not parse 'number of spectra' from header: {header_line!r}"
            ) from exc

        # integration time: Xms  (optional)
        int_time_ms: Optional[int] = None
        if "integration time" in meta_raw:
            s = meta_raw["integration time"]
            if "ms" in s:
                s = s.split("ms", 1)[0]
            try:
                int_time_ms = int(s.strip())
            except ValueError:
                int_time_ms = None

        # bandwidth: string (optional)
        bandwidth = meta_raw.get("bandwidth")

        # Remaining content: big-endian doubles for times, then big-endian longs per spectrum
        rest = f.read()

    # meas_spectra() stores one initial timestamp plus one per spectrum
    n_times = n_spectra + 1
    times_bytes = 8 * n_times
    if len(rest) < times_bytes:
        raise ValueError(
            f"File too short for expected {n_times} timestamps: {spec_path}"
        )

    times_raw = rest[:times_bytes]
    spectra_raw = rest[times_bytes:]

    # Times: big-endian float64
    times = np.frombuffer(times_raw, dtype=">f8").astype("float64")

    # Spectra: big-endian signed long (4 bytes each on this format)
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
        "n_spectra": n_spectra,
        "int_time_ms": int_time_ms,
        "bandwidth": bandwidth,
    }
    return times, spectra, meta

def _parse_index_range(rng: str, n_total: int) -> Tuple[int, int]:
    """
    Parse a range specification like "10:20" or "5" into (start, end),
    0-based, end exclusive, clamped to [0, n_total].
    """
    rng = rng.strip()
    if ":" in rng:
        start_str, end_str = rng.split(":", 1)
        start = int(start_str) if start_str else 0
        end = int(end_str) if end_str else n_total
    else:
        # Single index "k" → [k, k+1)
        idx = int(rng)
        # clamp idx into valid index range
        idx = max(0, min(idx, max(0, n_total - 1)))
        start, end = idx, idx + 1

    # Final clamp: start in [0, n_total-1], end in (start, n_total]
    if n_total <= 0:
        return 0, 0

    start = max(0, min(start, n_total - 1))
    end = max(start + 1, min(end, n_total))

    return start, end



def plot_spectra(
    times: np.ndarray,
    spectra: np.ndarray,
    meta: Dict[str, object],
    spec_path: Path,
    idx_start: int = 0,
    idx_end: Optional[int] = None,
    show: bool = True,
    allan: bool = False,
    allan_bin_start: Optional[int] = None,
    allan_bin_end: Optional[int] = None,
) -> Path:
    n_spectra, n_bins = spectra.shape

    if idx_end is None:
        idx_end = n_spectra

    # Clamp range
    idx_start = max(0, min(idx_start, n_spectra - 1))
    idx_end = max(idx_start + 1, min(idx_end, n_spectra))

    x = np.arange(n_bins)

    # Statistics over *all* spectra
    mean_all = spectra.mean(axis=0)
    if n_spectra > 1:
        std_all = spectra.std(axis=0, ddof=1)
    else:
        std_all = np.zeros_like(mean_all)

    # Subset to show individually
    subset = spectra[idx_start:idx_end, :]
    fig, ax = plt.subplots(figsize=(10, 5))

    # Plot only the selected range as faint individual spectra
    n_subset = subset.shape[0]
    for i in range(n_subset):
        ax.plot(
            x,
            subset[i],
            alpha=0.3,
            label=f"spectrum {idx_start + i}",
        )

    # Overlay mean and ±1σ band of *all* spectra
    ax.plot(x, mean_all, color="k", linewidth=2, label="mean (all)")
    if n_spectra > 1:
        ax.fill_between(
            x,
            mean_all - std_all,
            mean_all + std_all,
            color="k",
            alpha=0.2,
            label="±1σ (all)",
        )

    ax.set_xlabel("Bin index")
    ax.set_ylabel("Counts [arb.]")
    ax.grid(True, alpha=0.3)
    if n_subset <= 10:
        ax.legend(loc="best", fontsize="small")
    # ... existing plotting code ...

    ax.set_xlabel("Bin index")
    ax.set_ylabel("Counts [arb.]")
    ax.grid(True, alpha=0.3)
    if n_subset <= 10:
        ax.legend(loc="best", fontsize="small")

    # Add interactive crosshair cursor
    cursor = Cursor(
        ax,
        useblit=True,
        color="red",
        linewidth=0.8,
        horizOn=True,
        vertOn=True,
    )

    plot_dir = Path(__file__).resolve().parent / "plot"
    plot_dir.mkdir(parents=True, exist_ok=True)
    out_path = plot_dir / f"{spec_path.stem}.png"
    fig.tight_layout()
    fig.savefig(out_path)

    plot_dir = Path(__file__).resolve().parent / "plot"
    plot_dir.mkdir(parents=True, exist_ok=True)
    out_path = plot_dir / f"{spec_path.stem}.png"
    fig.tight_layout()
    fig.savefig(out_path)

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

    # Show all figures (spectra + Allan) together
    if show:
        plt.show()

    return out_path
    
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
    bin_end: Optional[int]= None,
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

def interactive_cli_loop(times, spectra, meta, spec_path, args):
    """Interactive loop: plot with current range, prompt for new range."""
    n_total = spectra.shape[0]
    print(f"\nLoaded {n_total} spectra. Interactive mode.")
    print("Enter new index range (e.g., '100:200', '50', '0:10') or 'quit' to exit.")
    
    while True:
        # Parse current range (initially from args, then from input)
        if not hasattr(interactive_cli_loop, 'current_range'):
            current_range = args.index_range
        idx_start, idx_end = _parse_index_range(current_range, n_total)
        
        print(f"Using range: {current_range} → spectra {idx_start}:{idx_end} ({idx_end-idx_start} shown)")
        out_path = plot_spectra(
            times=times,
            spectra=spectra,
            meta=meta,
            spec_path=spec_path,
            idx_start=idx_start,
            idx_end=idx_end,
            show=True,
            allan=args.allan,
            allan_bin_start=args.allan_bin_start,
            allan_bin_end=args.allan_bin_end,
        )
        print(f"Saved plot to {out_path}")
        
        # Prompt for new range
        user_input = input("\nNew index range (or 'quit'): ").strip()
        if user_input.lower() in ('quit', 'q', 'exit'):
            print("Exiting.")
            break
        if not user_input:
            print("No input; using previous range.")
            continue
        current_range = user_input  # Update for next iteration
        # Store in function-local state to persist across loops
        interactive_cli_loop.current_range = current_range

def main(argv: Optional[List[str]]  = None) -> None:
    parser = argparse.ArgumentParser(
        description="Plot spectra from a .spec file produced by the spectrometer UDP server"
    )
    parser.add_argument(
        "spec_file",
        nargs="?",
        help=".spec file to load (if omitted, a file dialog is shown)",
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
        "--index-range",
        type=str,
        default="0:1",
        help=(
            "Initial index range of spectra to plot individually as 'start:end' (0-based, "
            "end exclusive), or a single index 'k'. Default: 0:1 (first spectrum)."
        ),
    )
    parser.add_argument(
        "--allan",
        action="store_true",
        help="Also compute (and optionally plot) Allan variance of the spectra.",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive CLI loop.",
    )
    args = parser.parse_args(argv)

    if args.spec_file:
        spec_path = Path(args.spec_file)
    else:
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

    def _parse_bin_range(rng: str, n_total: int) -> Tuple[int, int]:
        rng = rng.strip()
        if ":" in rng:
            start_str, end_str = rng.split(":", 1)
            start = int(start_str) if start_str else 0
            end = int(end_str) if end_str else n_total
        else:
            # single index "k" -> [k, k+1)
            idx = int(rng)
            start, end = idx, idx + 1
        start = max(0, start)
        end = min(n_total, end)
        if end <= start:
            end = min(n_total, start + 1)
        return start, end

    allan_bin_start, allan_bin_end = _parse_bin_range(args.allan_bin_range, n_bins)
    args.allan_bin_start = allan_bin_start
    args.allan_bin_end = allan_bin_end
    if args.interactive:
        # Interactive loop
        interactive_cli_loop(times, spectra, meta, spec_path, args)
    else:
        # One-shot mode
        idx_start, idx_end = _parse_index_range(args.index_range, n_total)
        out_path = plot_spectra(
            times=times,
            spectra=spectra,
            meta=meta,
            spec_path=spec_path,
            idx_start=idx_start,
            idx_end=idx_end,
            show=True,
            allan=args.allan,
            allan_bin_start=args.allan_bin_start,
            allan_bin_end=args.allan_bin_end,
        )
        print(f"Saved plot to {out_path}")

if __name__ == "__main__":
    main()

