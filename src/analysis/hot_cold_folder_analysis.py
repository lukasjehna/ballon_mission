#!/usr/bin/env python3
"""Plot hot/cold analysis results from .spec files in a measurement directory."""

from pathlib import Path
import argparse
from datetime import datetime
import re
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
from matplotlib.widgets import Button
import numpy as np

import spec_analysis_utils as sau

_TIMESTAMPED_LOAD = re.compile(r"^(?P<timestamp>\d{14})(?P<load>hot|cold)(?:[^a-z].*)?$", re.IGNORECASE)


def _timestamped_load_files(spec_files: Sequence[Path]) -> Tuple[List[Tuple[datetime, Path]], List[Tuple[datetime, Path]]]:
    """Return valid, timestamp-sorted hot and cold files; report ignored candidates."""
    hot: List[Tuple[datetime, Path]] = []
    cold: List[Tuple[datetime, Path]] = []
    for path in spec_files:
        stem = path.stem
        is_hot = "hot" in stem.lower()
        is_cold = "cold" in stem.lower()
        if not (is_hot or is_cold):
            continue
        match = _TIMESTAMPED_LOAD.match(stem)
        if match is None:
            print(f"Ignoring {path.name}: hot/cold file lacks leading YYYYMMDDhhmmss timestamp.")
            continue
        try:
            stamp = datetime.strptime(match.group("timestamp"), "%Y%m%d%H%M%S")
        except ValueError:
            print(f"Ignoring {path.name}: invalid leading timestamp.")
            continue
        (hot if match.group("load").lower() == "hot" else cold).append((stamp, path))
    return sorted(hot), sorted(cold)


def _ordered_nearest_pairs(
    hot: Sequence[Tuple[datetime, Path]], cold: Sequence[Tuple[datetime, Path]]
) -> List[Tuple[Tuple[datetime, Path], Tuple[datetime, Path]]]:
    """Minimum-total-separation monotonic matching of min(len(hot), len(cold)) pairs."""
    if not hot or not cold:
        return []
    # Dynamic programming keeps each load sequence chronological and permits extras.
    n, m = len(hot), len(cold)
    want = min(n, m)
    inf = float("inf")
    cost = np.full((n + 1, m + 1, want + 1), inf)
    parent: Dict[Tuple[int, int, int], Tuple[int, int, int, str]] = {}
    cost[0, 0, 0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            for k in range(want + 1):
                current = cost[i, j, k]
                if not np.isfinite(current):
                    continue
                if i < n and current < cost[i + 1, j, k]:
                    cost[i + 1, j, k] = current
                    parent[i + 1, j, k] = (i, j, k, "skip_hot")
                if j < m and current < cost[i, j + 1, k]:
                    cost[i, j + 1, k] = current
                    parent[i, j + 1, k] = (i, j, k, "skip_cold")
                if i < n and j < m and k < want:
                    delta = abs((hot[i][0] - cold[j][0]).total_seconds())
                    if current + delta < cost[i + 1, j + 1, k + 1]:
                        cost[i + 1, j + 1, k + 1] = current + delta
                        parent[i + 1, j + 1, k + 1] = (i, j, k, "pair")
    i, j, k = n, m, want
    pairs = []
    while (i, j, k) != (0, 0, 0):
        pi, pj, pk, action = parent[i, j, k]
        if action == "pair":
            pairs.append((hot[pi], cold[pj]))
        i, j, k = pi, pj, pk
    return list(reversed(pairs))


def _load_pair_entries(
    pairs: Sequence[Tuple[Tuple[datetime, Path], Tuple[datetime, Path]]],
    header_meta: Dict[str, str],
) -> List[Dict[str, object]]:
    entries: List[Dict[str, object]] = []
    for (hot_time, hot_path), (cold_time, cold_path) in pairs:
        try:
            hot_mean = sau.file_mean_spectrum(hot_path)
            cold_mean = sau.file_mean_spectrum(cold_path)
            if hot_mean.size == 0 or cold_mean.size == 0:
                raise ValueError("empty spectrum")
            if hot_mean.shape != cold_mean.shape:
                raise ValueError(f"bin-count mismatch ({hot_mean.size} vs {cold_mean.size})")
        except (OSError, ValueError, EOFError) as exc:
            print(f"Skipping pair {hot_path.name} / {cold_path.name}: {exc}")
            continue
        entries.append({
            "hot_path": hot_path, "cold_path": cold_path,
            "hot_time": hot_time, "cold_time": cold_time,
            "hot": hot_mean, "cold": cold_mean,
            "separation_s": abs((hot_time - cold_time).total_seconds()),
        })
    return entries


def _launch_interactive_pairs(entries: Sequence[Dict[str, object]], header_meta: Dict[str, str], x_axis_mode: str, despike: bool) -> Optional[plt.Figure]:
    if not entries:
        print("No readable timestamp-matched hot/cold pairs available for interactive plotting.")
        return None
    t_hot, t_cold = sau._extract_hot_cold_kelvin(header_meta)
    if t_hot is None or t_cold is None:
        print("Interactive pairs need valid t_hot and t_cold values.")
        return None

    fig, (ax_spec, ax_noise) = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    fig.subplots_adjust(bottom=0.14, hspace=0.32)
    hot_line, = ax_spec.plot([], [], color="tab:red", label="hot")
    cold_line, = ax_spec.plot([], [], color="tab:blue", label="cold")
    noise_line, = ax_noise.plot([], [], color="tab:green", linewidth=1.0)
    ax_spec.set_ylabel("Counts [arb.]")
    ax_noise.set_ylabel("Noise temperature [K]")
    ax_spec.grid(True, alpha=0.3); ax_noise.grid(True, alpha=0.3)
    ax_spec.legend(loc="best")
    state = {"index": 0}

    def draw() -> None:
        entry = entries[state["index"]]
        hot = np.asarray(entry["hot"], dtype=float)
        cold = np.asarray(entry["cold"], dtype=float)
        noise = sau.compute_noise_temperature(hot, cold, t_hot, t_cold)
        if despike:
            noise, _ = sau._despike_1d(noise)
        x, label = sau._build_x_axis(hot.size, header_meta, x_axis_mode)
        hot_line.set_data(x, hot); cold_line.set_data(x, cold); noise_line.set_data(x, noise)
        if x.size > 1:
            ax_spec.set_xlim(float(x[0]), float(x[-1]))
        else:
            ax_spec.set_xlim(0, 1)
        for axis in (ax_spec, ax_noise):
            axis.relim(); axis.autoscale_view(scalex=False, scaley=True)
            sau._apply_x_axis_format(axis, header_meta, x_axis_mode, label)
        i0, i1 = 200, min(1851, noise.size)
        mean = float(np.nanmean(noise[i0:i1])) if i1 > i0 and np.any(np.isfinite(noise[i0:i1])) else float("nan")
        ax_spec.set_title(f"Pair {state['index'] + 1}/{len(entries)}: {entry['hot_path'].name}  |  {entry['cold_path'].name}")
        ax_noise.set_title(f"T_hot={t_hot:.2f} K, T_cold={t_cold:.2f} K, Δt={entry['separation_s']:.0f} s, mean(200..1850)={mean:.2f} K")
        fig.canvas.draw_idle()

    def step(delta: int) -> None:
        state["index"] = (state["index"] + delta) % len(entries)
        draw()

    prev_ax = fig.add_axes([0.75, 0.03, 0.10, 0.055])
    next_ax = fig.add_axes([0.86, 0.03, 0.10, 0.055])
    prev, next_ = Button(prev_ax, "Previous"), Button(next_ax, "Next")
    prev.on_clicked(lambda _event: step(-1)); next_.on_clicked(lambda _event: step(1))
    fig.canvas.mpl_connect("key_press_event", lambda event: step(-1) if event.key in ("left", "up") else step(1) if event.key in ("right", "down") else None)
    fig._pair_browser_buttons = (prev, next_)
    draw()
    return fig


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Hot/cold analysis with optional temperature overrides.")
    parser.add_argument("--t-hot", dest="t_hot", type=str, default="296", help="Override hot load temperature (default 296K).")
    parser.add_argument("--t-cold", dest="t_cold", type=str, default="77", help="Override cold load temperature (default 77K).")
    parser.add_argument("--x-axis", dest="x_axis", choices=["frequency", "bins", "sidebands"], default="frequency", help="X-axis mode: frequency, bins, or sidebands.")
    parser.add_argument("--csv-only", action="store_true", help="Only export averaged hot/cold CSV and skip plotting.")
    parser.add_argument("--despike", action="store_true", help="Apply impulse-outlier filter before plotting noise temperature.")
    parser.add_argument("--plot-noise-temp", action="store_true", help="Plot the noise temperature spectrum.")
    parser.add_argument("--plot-all-spectra", action="store_true", help="Plot all individual hot and cold spectra.")
    parser.add_argument("--plot-avg-spectra", action="store_true", help="Plot averaged hot and cold spectra.")
    parser.add_argument("--plot-interactive-pairs", action="store_true", help="Interactively browse nearest timestamp-matched hot/cold file pairs.")
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    default_data_dir = project_root / "data"
    meas_dir = sau.choose_directory(default_data_dir if default_data_dir.is_dir() else project_root)
    if meas_dir is None or not meas_dir.is_dir():
        print("No valid measurement directory selected. Exiting."); return
    meas_dir = sau._resolve_measurement_dir_with_specs(meas_dir)
    spec_files = sorted(meas_dir.glob("*.spec"))
    if not spec_files:
        print(f"No .spec files found in {meas_dir}"); return
    hot_files = [p for p in spec_files if "hot" in p.stem.lower()]
    cold_files = [p for p in spec_files if "cold" in p.stem.lower()]
    if not hot_files or not cold_files:
        print(f"Both hot and cold .spec files are required in {meas_dir}"); return

    header_meta = sau.parse_header_csv(meas_dir)
    header_meta["t_hot"] = args.t_hot
    header_meta["t_cold"] = args.t_cold
    sau.print_header_meta(header_meta)

    made_any_plot = False
    if args.plot_interactive_pairs:
        stamped_hot, stamped_cold = _timestamped_load_files(spec_files)
        if len(stamped_hot) != len(stamped_cold):
            print(f"Timestamped file counts differ: {len(stamped_hot)} hot, {len(stamped_cold)} cold; unmatched files are skipped.")
        pairs = _ordered_nearest_pairs(stamped_hot, stamped_cold)
        entries = _load_pair_entries(pairs, header_meta)
        made_any_plot = _launch_interactive_pairs(entries, header_meta, args.x_axis, args.despike) is not None

    # Existing averaged workflow intentionally remains unchanged for its original flags.
    needs_average = args.csv_only or args.plot_avg_spectra or args.plot_noise_temp or args.plot_all_spectra or not args.plot_interactive_pairs
    if needs_average:
        print(f"Using {len(hot_files)} hot files and {len(cold_files)} cold files in {meas_dir}")
        avg_hot, n_hot = sau.accumulate_group_average(hot_files)
        avg_cold, n_cold = sau.accumulate_group_average(cold_files)
        out_csv = sau.save_hot_cold_average_csv(meas_dir, avg_hot, avg_cold, header_meta)
        print(f"Saved hot/cold average CSV to {out_csv}")
        if args.csv_only: return
        if args.plot_avg_spectra:
            print(f"Saved hot/cold average plot to {sau.plot_hot_cold_average(meas_dir, avg_hot, n_hot, avg_cold, n_cold, header_meta, args.x_axis)}")
            made_any_plot = True
        if args.plot_noise_temp:
            out = sau.plot_noise_temperature(meas_dir, avg_hot, avg_cold, header_meta, args.x_axis, despike_enabled=args.despike)
            if out is not None: print(f"Saved noise temperature plot to {out}")
            made_any_plot = True
        if args.plot_all_spectra:
            print(f"Saved hot/cold per-file lines plot to {sau.plot_all_hot_cold_lines(meas_dir, hot_files, cold_files, header_meta, args.x_axis)}")
            made_any_plot = True
    if made_any_plot:
        plt.show()
    elif not args.csv_only:
        print("No plots selected. Use --plot-interactive-pairs or an existing plotting option.")

if __name__ == "__main__":
    main()
