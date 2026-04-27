#!/usr/bin/env python3
"""
Select one main measurement folder and plot average noise temperature
for all contained measurement directories automatically.

Example:
python3 src/analysis/noise_temperature_frequency_scan.py --t-hot 296 --t-cold 77 --bin-start 200 --bin-stop 1850 --despike --errorbars
"""

from pathlib import Path
import argparse
from typing import Optional, List, Tuple
import tkinter as tk
from tkinter import filedialog, messagebox

import numpy as np
import matplotlib.pyplot as plt

import spectrometer_analysis_utils


def _extract_hot_cold_kelvin(header_meta: dict) -> Tuple[Optional[float], Optional[float]]:
    meta_lc = {k.lower(): v for k, v in header_meta.items()}
    t_hot_raw = meta_lc.get("t_hot") or meta_lc.get("thot")
    t_cold_raw = meta_lc.get("t_cold") or meta_lc.get("tcold")
    return spectrometer_analysis_utils._parse_temperature_value(t_hot_raw), spectrometer_analysis_utils._parse_temperature_value(t_cold_raw)

def _select_single_directory(initialdir: Path) -> Optional[Path]:
    root = tk.Tk()
    root.withdraw()
    path = filedialog.askdirectory(
        title="Select main folder containing measurements",
        initialdir=str(initialdir),
    )
    root.destroy()
    return Path(path) if path else None


def _discover_measurement_dirs(main_dir: Path) -> List[Path]:
    discovered: List[Path] = []
    seen = set()

    # Include main_dir itself, then direct subdirectories.
    candidates = [main_dir] + sorted([p for p in main_dir.iterdir() if p.is_dir()])

    for candidate in candidates:
        meas_dir = spectrometer_analysis_utils._resolve_measurement_dir_with_specs(candidate)
        key = str(meas_dir.resolve())
        if key in seen:
            continue
        if any(meas_dir.glob("*.spec")):
            discovered.append(meas_dir)
            seen.add(key)

    return discovered



def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Average noise temperature from one main folder.")
    parser.add_argument( "--folder", type=str, default=None, help="Main folder containing measurement directories. If omitted, GUI single-folder selection is used.",)
    parser.add_argument("--t-hot", type=str, default="296", help="Override T_hot (e.g. 296 or 23C).")
    parser.add_argument("--t-cold", type=str, default="77", help="Override T_cold (e.g. 77 or -196C).")
    parser.add_argument("--center-freq", type=float, default=235.71, help="Center frequency [GHz] for bin window calculation (default 235.71).")
    parser.add_argument("--bin-offset", type=int, default=615, help="Bin offset around center frequency (default 615).")
    parser.add_argument("--bin-start", type=int, default=None, help="Start bin (inclusive) for mean. If omitted, computed from --center-freq and --bin-offset.")
    parser.add_argument("--bin-stop", type=int, default=None, help="Stop bin (inclusive) for mean. If omitted, computed from --center-freq and --bin-offset.")
    parser.add_argument("--save", type=str, default=None, help="Optional output PNG path. If omitted, figure is only shown.",)
    parser.add_argument("--despike", action="store_true", default=None, help="Apply impulse-outlier filter to noise temperature before statistics/plotting.",)
    parser.add_argument("--errorbars",action="store_true",default=None, help="Show error bars on plot (default: no error bars).",)
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    default_data_dir = project_root / "data"
    if not default_data_dir.is_dir():
        default_data_dir = project_root

    if args.folder:
        main_folder = Path(args.folder)
    else:
        main_folder = _select_single_directory(default_data_dir)

    if not main_folder:
        print("No folder selected. Exiting.")
        return
    if not main_folder.is_dir():
        print(f"Not a directory: {main_folder}")
        return

    measurement_dirs = _discover_measurement_dirs(main_folder)
    if not measurement_dirs:
        print(f"No measurement directories with .spec files found in: {main_folder}")
        return

    # Output files in selected folder
    summary_txt = main_folder / "noise_temperature_frequency_scan_summary.txt"

    freqs_ghz: List[float] = []
    means: List[float] = []
    stds: List[float] = []
    removed_spikes_per_meas: List[int] = []
    interactive_noise_entries: List[dict] = []
    summary_lines: List[str] = []
    used_bin_starts: List[int] = []
    used_bin_stops: List[int] = []

    for meas_dir in measurement_dirs:
        if not meas_dir.is_dir():
            print(f"Skipping (not a directory): {meas_dir}")
            continue

        spec_files = sorted(meas_dir.glob("*.spec"))
        if not spec_files:
            print(f"Skipping (no .spec files): {meas_dir}")
            continue

        hot_files = [p for p in spec_files if "hot" in p.stem.lower()]
        cold_files = [p for p in spec_files if "cold" in p.stem.lower()]
        if not hot_files or not cold_files:
            print(f"Skipping (missing hot/cold files): {meas_dir}")
            continue

        avg_hot, _ = spectrometer_analysis_utils.accumulate_group_average(hot_files)
        avg_cold, _ = spectrometer_analysis_utils.accumulate_group_average(cold_files)

        header_meta = spectrometer_analysis_utils.parse_header_csv(meas_dir)
        # Also read inline metadata from the .spec file so bandwidth is available
        _, _, spec_meta = spectrometer_analysis_utils.load_spec_file(spec_files[0])
        header_meta = {**header_meta, **{k: str(v) for k, v in spec_meta.items() if v is not None}}

        meta_lc = {k.lower(): v for k, v in header_meta.items()}
        f_rx_ghz = spectrometer_analysis_utils._parse_frequency_ghz(meta_lc.get("f_rx"))
        if f_rx_ghz is None:
            print(f"Skipping (missing/invalid f_RX): {meas_dir}")
            continue

        if args.t_hot is not None:
            header_meta["t_hot"] = args.t_hot
        if args.t_cold is not None:
            header_meta["t_cold"] = args.t_cold

        t_hot_k, t_cold_k = _extract_hot_cold_kelvin(header_meta)
        if t_hot_k is None or t_cold_k is None:
            print(f"Skipping (missing t_hot/t_cold): {meas_dir}")
            continue

        # Compute bin window for this measurement if not explicitly provided
        if args.bin_start is None or args.bin_stop is None:
            bw_ghz = spectrometer_analysis_utils._get_bw_ghz(header_meta)
            bin_start, bin_stop = spectrometer_analysis_utils._compute_bin_window_from_center_freq(
                center_freq_ghz=args.center_freq,
                f_rx_ghz=f_rx_ghz,
                bandwidth_ghz=bw_ghz,
                bin_offset=args.bin_offset,
            )
            # Use explicit args if provided, otherwise use computed values
            bin_start = args.bin_start if args.bin_start is not None else bin_start
            bin_stop = args.bin_stop if args.bin_stop is not None else bin_stop
        else:
            bin_start = args.bin_start
            bin_stop = args.bin_stop

        # Track the actual bin_start/bin_stop used
        used_bin_starts.append(bin_start)
        used_bin_stops.append(bin_stop)

        t_noise = spectrometer_analysis_utils.compute_noise_temperature(avg_hot, avg_cold, t_hot_k, t_cold_k)

        start = max(0, bin_start)
        stop_exclusive = min(t_noise.size, bin_stop + 1)
        if start >= stop_exclusive:
            print(f"Skipping (invalid bin window): {meas_dir}")
            continue

        removed_spikes = 0
        t_noise_for_stats = t_noise
        if args.despike:
            t_noise_for_stats, removed_spikes = spectrometer_analysis_utils._despike_1d_in_window(
                t_noise,
                bin_start=start,
                bin_stop=stop_exclusive - 1,
            )

        window = t_noise_for_stats[start:stop_exclusive]
        if not np.any(np.isfinite(window)):
            print(f"Skipping (no valid noise-temperature bins): {meas_dir}")
            continue

        finite_window = window[np.isfinite(window)]
        mean_t = float(np.mean(finite_window))
        std_t = float(np.std(finite_window, ddof=1)) if finite_window.size > 1 else 0.0

        freqs_ghz.append(f_rx_ghz)
        means.append(mean_t)
        stds.append(std_t)
        removed_spikes_per_meas.append(removed_spikes)

        if args.despike:
            line = (
                f"{meas_dir.name}: f_RX={f_rx_ghz:.3f} GHz: "
                f"mean noise temperature = {mean_t:.2f} ± {std_t:.2f} K, "
                f"removed spikes = {removed_spikes}"
            )
        else:
            line = (
                f"{meas_dir.name}: f_RX={f_rx_ghz:.3f} GHz: "
                f"mean noise temperature = {mean_t:.2f} ± {std_t:.2f} K"
            )
        summary_lines.append(line)
        print(line)

        interactive_noise_entries.append(
            {
                "name": meas_dir.name,
                "f_rx_ghz": f_rx_ghz,
                "t_hot_k": t_hot_k,
                "t_cold_k": t_cold_k,
                "t_noise": t_noise_for_stats.copy(),
                "avg_hot": avg_hot.copy(),
                "avg_cold": avg_cold.copy(),
                "removed_spikes": removed_spikes,
                "header_meta": dict(header_meta),
                "bin_start": bin_start,
                "bin_stop": bin_stop,
            }
        )

    if not means:
        print("No valid folders to plot. Exiting.")
        return

    # Pick the first valid bin_start/bin_stop for interactive browser
    browser_bin_start = next((b for b in used_bin_starts if b is not None), None)
    browser_bin_stop = next((b for b in used_bin_stops if b is not None), None)

    order = np.argsort(freqs_ghz)
    x = np.asarray(freqs_ghz, dtype=float)[order]
    y = np.asarray(means, dtype=float)[order]
    yerr = np.asarray(stds, dtype=float)[order]
    spike_counts = np.asarray(removed_spikes_per_meas, dtype=int)[order]
    ordered_entries = [interactive_noise_entries[i] for i in np.argsort(freqs_ghz)]

    center_freq_ghz = args.center_freq
    print(f"Using center frequency {center_freq_ghz:.3f} GHz for relative frequency axis.")

    fig, ax = plt.subplots(figsize=(11, 5))
    show_errorbars = getattr(args, "errorbars", False)
    errorbar_kwargs = {
        "fmt": "o",
        "linewidth": 1.5,
        "capsize": 3 if show_errorbars else 0,
        "color": "tab:green",
        "ecolor": "tab:green",
    }

    if show_errorbars:
        ax.errorbar(x, y, yerr=yerr, **errorbar_kwargs)
    else:
        ax.errorbar(x, y, yerr=None, **errorbar_kwargs)

    ax.xaxis.set_major_locator(plt.MaxNLocator(nbins=10))
    ax.tick_params(axis="x", rotation=30, labelsize=9)
    ax.set_ylabel("Average noise temperature [K]")
    ax.set_xlabel("f_RX [GHz]")

    ax_top = spectrometer_analysis_utils.add_relative_frequency_top_axis(ax, center_freq_ghz)
    ax_top.tick_params(axis="x", rotation=30, labelsize=9)

    ax.set_title(
        f"Average noise temperature, "
        f"f_center={center_freq_ghz:.3f} GHz"
    )
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    out_png = Path(args.save) if args.save else (main_folder / "noise_temperature_frequency_scan.png")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png)
    print(f"Saved figure: {out_png}")

    if args.despike:
        fig_sp, ax_sp = plt.subplots(figsize=(11, 5))
        ax_sp.plot(x, spike_counts, "o", color="tab:orange", linewidth=1.5)
        ax_sp.xaxis.set_major_locator(plt.MaxNLocator(nbins=10))
        ax_sp.yaxis.set_major_locator(plt.MaxNLocator(integer=True))
        ax_sp.tick_params(axis="x", rotation=30, labelsize=9)
        ax_sp.set_ylabel("Removed spikes [count]")
        ax_sp.set_xlabel("f_RX [GHz]")

        ax_sp_top = spectrometer_analysis_utils.add_relative_frequency_top_axis(ax_sp, center_freq_ghz)
        ax_sp_top.tick_params(axis="x", rotation=30, labelsize=9)

        ax_sp.set_title(
            f"Removed spikes after despike, "
            f"f_center={center_freq_ghz:.3f} GHz"
        )
        ax_sp.grid(True, alpha=0.3)
        fig_sp.tight_layout()

        if args.save:
            out_spikes_png = out_png.with_name(f"{out_png.stem}_spikes{out_png.suffix}")
        else:
            out_spikes_png = main_folder / "noise_temperature_frequency_scan_spikes.png"
        out_spikes_png.parent.mkdir(parents=True, exist_ok=True)
        fig_sp.savefig(out_spikes_png)
        print(f"Saved spikes figure: {out_spikes_png}")

    # Save printed result lines to text file in selected folder.
    summary_txt.write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    print(f"Saved summary: {summary_txt}")

    browser_fig = spectrometer_analysis_utils.launch_interactive_noise_temperature_browser(
        entries=interactive_noise_entries,
        bin_start=browser_bin_start,
        bin_stop=browser_bin_stop,
        despike_enabled=bool(args.despike),
        center_freq_ghz=args.center_freq,
    )
    if browser_fig is not None:
        print("Opened interactive noise-temperature browser (Prev/Next buttons or arrow keys).")

    plt.show()


if __name__ == "__main__":
    main()
