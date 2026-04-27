#!/usr/bin/env python3
"""
Plots hot/cold analysis results from .spec files in a selected measurement directory.
python3 src/analysis/hot_cold_analysis.py --x-axis sidebands --t-hot 300 --t-cold 77 --despike
"""

from pathlib import Path
import argparse
from typing import Optional, List
import matplotlib.pyplot as plt

import spectrometer_analysis_utils

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
    args = parser.parse_args(argv)

    project_root = Path(__file__).resolve().parents[2]
    default_data_dir = project_root / "data"
    if not default_data_dir.is_dir():
        default_data_dir = project_root
    meas_dir = spectrometer_analysis_utils.choose_directory(default_data_dir)

    if meas_dir is None or not meas_dir.is_dir():
        print("No valid measurement directory selected. Exiting.")
        return

    meas_dir = spectrometer_analysis_utils._resolve_measurement_dir_with_specs(meas_dir)
    spec_files = sorted(meas_dir.glob("*.spec"))
    if not spec_files:
        print(f"No .spec files found in {meas_dir}")
        return

    hot_files = [p for p in spec_files if "hot" in p.stem.lower()]
    cold_files = [p for p in spec_files if "cold" in p.stem.lower()]

    if not hot_files:
        print(f"No hot .spec files found in {meas_dir}")
        return
    if not cold_files:
        print(f"No cold .spec files found in {meas_dir}")
        return

    print(f"Using {len(hot_files)} hot files and {len(cold_files)} cold files in {meas_dir}")

    # Plot 1: overall averages
    avg_hot, n_hot = spectrometer_analysis_utils.accumulate_group_average(hot_files)
    avg_cold, n_cold = spectrometer_analysis_utils.accumulate_group_average(cold_files)
    header_meta = spectrometer_analysis_utils.parse_header_csv(meas_dir)
    if args.t_hot is not None:
        header_meta["t_hot"] = args.t_hot
    if args.t_cold is not None:
        header_meta["t_cold"] = args.t_cold

    spectrometer_analysis_utils.print_header_meta(header_meta)

    out_csv = spectrometer_analysis_utils.save_hot_cold_average_csv(
        meas_dir=meas_dir,
        avg_hot=avg_hot,
        avg_cold=avg_cold,
        header_meta=header_meta,
    )
    print(f"Saved hot/cold average CSV to {out_csv}")

    if args.csv_only:
        return

    out_avg = spectrometer_analysis_utils.plot_hot_cold_average(
        meas_dir=meas_dir,
        avg_hot=avg_hot, n_hot=n_hot,
        avg_cold=avg_cold, n_cold=n_cold,
        header_meta=header_meta,
        x_axis_mode=args.x_axis,
    )
    print(f"Saved hot/cold average plot to {out_avg}")

    if args.despike:
        avg_hot_for_noise, hot_removed = spectrometer_analysis_utils._despike_1d_in_window(avg_hot, 0, avg_hot.size - 1)
        avg_cold_for_noise, cold_removed = spectrometer_analysis_utils._despike_1d_in_window(avg_cold, 0, avg_cold.size - 1)
        print(f"Despike applied: hot removed {hot_removed} spikes, cold removed {cold_removed} spikes")
    else:
        avg_hot_for_noise = avg_hot
        avg_cold_for_noise = avg_cold

    out_noise_temp = spectrometer_analysis_utils.plot_noise_temperature(
        meas_dir=meas_dir,
        avg_hot=avg_hot_for_noise,
        avg_cold=avg_cold_for_noise,
        header_meta=header_meta,
        x_axis_mode=args.x_axis,
    )
    if out_noise_temp is not None:
        print(f"Saved noise-temperature plot to {out_noise_temp}")

    # Plot 2: all per-file lines
    out_lines = spectrometer_analysis_utils.plot_all_hot_cold_lines(
        meas_dir=meas_dir,
        hot_files=hot_files,
        cold_files=cold_files,
        header_meta=header_meta,
        x_axis_mode=args.x_axis,
    )
    print(f"Saved hot/cold per-file lines plot to {out_lines}")

    plt.show()


if __name__ == "__main__":
    main()


