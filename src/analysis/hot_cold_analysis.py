#!/usr/bin/env python3
"""
Plots hot/cold analysis results from .spec files in a selected measurement directory.

Examples:
python3 src/analysis/hot_cold_analysis.py --plot-noise-temp
python3 src/analysis/hot_cold_analysis.py --plot-all-spectra --plot-avg-spectra
python3 src/analysis/hot_cold_analysis.py --x-axis sidebands --t-hot 300 --t-cold 77 --despike --plot-noise-temp --plot-avg-spectra
"""

from pathlib import Path
import argparse
from typing import Optional, List
import matplotlib.pyplot as plt
import numpy as np

import spectrometer_analysis_utils
from file_parser_utils import parse_header_csv, choose_directory, resolve_measurement_dir_with_specs, print_header_meta, split_hot_cold_files
from plotting_utility import plot_noise_temperature, plot_all_hot_cold_lines, build_x_axis

def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Hot/cold analysis with optional temperature overrides."
    )
    parser.add_argument(
        "--t-hot",
        dest="t_hot",
        type=str,
        default="296",
        help="Override hot load temperature (default 296K).",
    )
    parser.add_argument(
        "--t-cold",
        dest="t_cold",
        type=str,
        default="77",
        help="Override cold load temperature (default 77K).",
    )
    parser.add_argument(
        "--x-axis",
        dest="x_axis",
        choices=["frequency", "bins", "sidebands"],
        default="frequency",
        help=(
            "X-axis mode: 'frequency' -> f_IF with f_LO annotation (default), "
            "'bins' -> bin index, 'sidebands' -> bottom f_USB and top f_LSB."
        ),
    )
    parser.add_argument(
        "--csv-only",
        action="store_true",
        help="Only export averaged hot/cold CSV and skip plotting.",
    )
    parser.add_argument(
        "--despike",
        action="store_true",
        help="Apply impulse-outlier filter before plotting noise temperature.",
    )

    parser.add_argument(
        "--plot-noise-temp",
        action="store_true",
        help="Plot the noise temperature spectrum.",
    )
    parser.add_argument(
        "--plot-all-spectra",
        action="store_true",
        help="Plot all individual hot and cold spectra.",
    )
    parser.add_argument(
        "--browse-spectra",
        action="store_true",
        help="Interactively browse hot/cold spectra one pair at a time.",
    )

    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    default_data_dir = project_root / "data"
    if not default_data_dir.is_dir():
        default_data_dir = project_root
    meas_dir = choose_directory(default_data_dir)

    if meas_dir is None or not meas_dir.is_dir():
        print("No valid measurement directory selected. Exiting.")
        return

    meas_dir = resolve_measurement_dir_with_specs(meas_dir)
    spec_files = sorted(meas_dir.glob("*.spec"))
    if not spec_files:
        print("No .spec files found in {}".format(meas_dir))
        return

    hot_files, cold_files = split_hot_cold_files(spec_files)

    if not hot_files:
        print("No hot .spec files found in {}".format(meas_dir))
        return
    if not cold_files:
        print("No cold .spec files found in {}".format(meas_dir))
        return

    print("Using {} hot files and {} cold files in {}".format(
        len(hot_files), len(cold_files), meas_dir
    ))

    avg_hot, std_hot, n_hot = spectrometer_analysis_utils.accumulate_group_mean_std(hot_files)
    avg_cold, std_cold, n_cold = spectrometer_analysis_utils.accumulate_group_mean_std(cold_files)
    header_meta = parse_header_csv(meas_dir)

    if args.t_hot is not None:
        header_meta["t_hot"] = args.t_hot
    if args.t_cold is not None:
        header_meta["t_cold"] = args.t_cold

    print_header_meta(header_meta)

    out_csv = spectrometer_analysis_utils.save_hot_cold_average_csv(
        meas_dir=meas_dir,
        avg_hot=avg_hot,
        avg_cold=avg_cold,
        header_meta=header_meta,
    )
    print("Saved hot/cold average CSV to {}".format(out_csv))

    if args.csv_only:
        return

    made_any_plot = False

    if args.plot_noise_temp:
        out_noise_temp = plot_noise_temperature(
            meas_dir=meas_dir,
            avg_hot=avg_hot,
            avg_cold=avg_cold,
            header_meta=header_meta,
            x_axis_mode=args.x_axis,
            despike_enabled=args.despike,
        )
        if out_noise_temp is not None:
            print("Saved noise temperature plot to {}".format(out_noise_temp))
            made_any_plot = True

    if args.plot_all_spectra:
        out_lines = plot_all_hot_cold_lines(
            meas_dir=meas_dir,
            hot_files=hot_files,
            cold_files=cold_files,
            header_meta=header_meta,
            x_axis_mode=args.x_axis,
        )
        print("Saved hot/cold per-file lines plot to {}".format(out_lines))
        made_any_plot = True

    if args.browse_spectra:
        _browse_spectra(
            meas_dir=meas_dir,
            hot_files=hot_files,
            cold_files=cold_files,
            header_meta=header_meta,
            x_axis_mode=args.x_axis,
            avg_hot=avg_hot,
            std_hot=std_hot,
            avg_cold=avg_cold,
            std_cold=std_cold,
        )
        made_any_plot = True

    if made_any_plot:
        plt.show()
    else:
        print(
            "No plots selected. Use one or more of: "
            "--plot-noise-temp, --plot-all-spectra, --browse-spectra"
        )


def _browse_spectra(
    meas_dir: Path,
    hot_files: List[Path],
    cold_files: List[Path],
    header_meta: dict,
    x_axis_mode: str,
    avg_hot: np.ndarray,
    std_hot: np.ndarray,
    avg_cold: np.ndarray,
    std_cold: np.ndarray,
) -> None:
    pairs = list(zip(sorted(hot_files), sorted(cold_files)))
    if not pairs:
        print("No hot/cold pairs available for browsing.")
        return

    if len(hot_files) != len(cold_files):
        print(
            f"Warning: hot/cold count mismatch (hot={len(hot_files)}, cold={len(cold_files)}). "
            f"Browsing {len(pairs)} pairs by index."
        )

    idx = 0
    fig, ax = plt.subplots()
    plt.subplots_adjust(right=0.82)

    from matplotlib.widgets import CheckButtons
    state = {"show_hot": True, "show_cold": True}

    ax_checks = fig.add_axes((0.84, 0.72, 0.14, 0.16))
    checks = CheckButtons(ax_checks, ["hot", "cold"], [True, True])

    def _on_check(label) -> None:
        if label == "hot":
            state["show_hot"] = not state["show_hot"]
        elif label == "cold":
            state["show_cold"] = not state["show_cold"]
        _update_plot()

    checks.on_clicked(_on_check)
    setattr(fig, "_browse_checks", checks)
    setattr(fig, "_browse_checks_ax", ax_checks)

    def _update_plot() -> None:
        nonlocal idx
        hot_path, cold_path = pairs[idx]
        hot = spectrometer_analysis_utils.file_mean_spectrum(hot_path)
        cold = spectrometer_analysis_utils.file_mean_spectrum(cold_path)

        x_vals, x_label = build_x_axis(hot.size, header_meta, x_axis_mode=x_axis_mode)

        ax.clear()

        if state["show_hot"]:
            ax.plot(x_vals, hot, label=f"hot: {hot_path.name}", color="tab:red", alpha=0.7)
            ax.plot(x_vals, avg_hot, label="hot avg", color="tab:red", linewidth=1.5)
            ax.fill_between(
                x_vals, avg_hot - std_hot, avg_hot + std_hot,
                color="tab:red", alpha=0.12, label="hot ±1σ"
            )

        if state["show_cold"]:
            ax.plot(x_vals, cold, label=f"cold: {cold_path.name}", color="tab:blue", alpha=0.7)
            ax.plot(x_vals, avg_cold, label="cold avg", color="tab:blue", linewidth=1.5)
            ax.fill_between(
                x_vals, avg_cold - std_cold, avg_cold + std_cold,
                color="tab:blue", alpha=0.12, label="cold ±1σ"
            )

        ax.set_title(f"Pair {idx + 1}/{len(pairs)}")
        ax.set_xlabel(x_label)
        ax.set_ylabel("Mean counts^2")
        ax.legend(loc="best")
        ax.grid(True, alpha=0.3)
        fig.canvas.draw_idle()

    def _on_key(event) -> None:
        nonlocal idx
        if event.key in ("right", "n", "down", " "):
            idx = (idx + 1) % len(pairs)
            _update_plot()
        elif event.key in ("left", "p", "up", "backspace"):
            idx = (idx - 1) % len(pairs)
            _update_plot()
        elif event.key in ("q", "escape"):
            plt.close(fig)

    fig.canvas.mpl_connect("key_press_event", _on_key)
    fig.suptitle("Browse hot/cold spectra (←/→ or p/n, q to quit)")
    _update_plot()


if __name__ == "__main__":
    main()