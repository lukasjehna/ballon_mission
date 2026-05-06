from pathlib import Path
import os
import sys
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure
import numpy as np

# ensure package imports from project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # adjust to project root
sys.path.insert(0, str(PROJECT_ROOT))

from spectrometer_analysis_utils import interactive_calibration_setup, calibrate_spectrum_to_temperature, accumulate_group_average

from plotting_utility import build_x_axis, apply_x_axis_format
from file_parser_utils import read_two_column_file, choose_directory, parse_header_csv, resolve_measurement_dir_with_specs

from plotting_utility import plot_spectrum
# Use calibrated laboratory measurements to calibrate the T_sky=T_c of uncalibrated ground measurement. Then compare the ground measurements with the simulation ozone peak simluation around 235.71 GHz GroundSim0kmAlt   


def calibrate_and_plot_ground_sim() -> None:
    """
    Interactively select calibrated and uncalibrated measurement folders,
    then calibrate and plot the uncalibrated data using the calibrated references.
    """
    print("\n=== Step 1: Select CALIBRATED reference measurement folder ===")
    calib_setup = interactive_calibration_setup()
    if calib_setup is None:
        print("No calibrated reference data loaded. Exiting.")
        return
    
    calib_avg_hot = calib_setup["avg_hot"]
    calib_avg_cold = calib_setup["avg_cold"]
    t_hot_k = calib_setup["t_hot_k"]
    t_cold_k = calib_setup["t_cold_k"]
    
    print("\n=== Step 2: Select UNCALIBRATED measurement folder ===")
    project_root = PROJECT_ROOT
    default_data_dir = project_root / "data"
    if not default_data_dir.is_dir():
        default_data_dir = project_root
    
    uncalib_dir = choose_directory(default_data_dir)
    if uncalib_dir is None or not uncalib_dir.is_dir():
        print("No valid uncalibrated measurement directory selected.")
        return
    
    uncalib_dir = resolve_measurement_dir_with_specs(uncalib_dir)
    spec_files = sorted(uncalib_dir.glob("*.spec"))
    
    if not spec_files:
        print(f"No .spec files found in {uncalib_dir}")
        return
    
    hot_files = [p for p in spec_files if "hot" in p.stem.lower()]
    cold_files = [p for p in spec_files if "cold" in p.stem.lower()]
    
    if not hot_files or not cold_files:
        print("Could not find both hot and cold .spec files in uncalibrated folder.")
        return
    
    print(f"Loading {len(hot_files)} hot and {len(cold_files)} cold uncalibrated files...")
    
    try:
        uncalib_avg_hot, n_uncalib_hot = accumulate_group_average(hot_files)
        uncalib_avg_cold, n_uncalib_cold = accumulate_group_average(cold_files)
    except Exception as e:
        print(f"Error loading uncalibrated spectra: {e}")
        return

    # Estimate sky temperature from uncalibrated hot/cold Y-factor (median in bins 200..1850)
    t_rx_k = 11000.0     # Receiver noise temperature [K]
    t_hot_c_k = 296.0    # Calibration hot load [K]
    t_cold_c_k = 77.0    # Calibration cold load [K] (kept for traceability)
    bin_start, bin_stop = 200, 1850

    i0 = max(0, bin_start)
    i1 = min(uncalib_avg_hot.size - 1, bin_stop)
    eps = np.finfo(float).eps
    t_sky_k = np.nan

    if i0 <= i1:
        hot_w = uncalib_avg_hot[i0:i1 + 1]
        cold_w = uncalib_avg_cold[i0:i1 + 1]
        valid = np.isfinite(hot_w) & np.isfinite(cold_w) & (np.abs(cold_w) > eps)

        if np.any(valid):
            y_bins = hot_w[valid] / cold_w[valid]
            y_bins = y_bins[np.isfinite(y_bins)]
            if y_bins.size > 0:
                y_sky = float(np.nanmedian(y_bins))
                if abs(y_sky - 1.0) > eps:
                    t_sky_k = (t_hot_c_k - y_sky * t_rx_k) / (y_sky - 1.0)
                    print(
                        f"Estimated uncalibrated sky temperature: "
                        f"y_sky(median,{bin_start}..{bin_stop})={y_sky:.6f}, "
                        f"t_sky_k={t_sky_k:.2f} K"
                    )
                else:
                    print("Could not compute t_sky_k: y_sky is too close to 1.")
            else:
                print("Could not compute t_sky_k: no finite Y-factor bins.")
        else:
            print("Could not compute t_sky_k: no valid bins in selected range.")
    else:
        print("Could not compute t_sky_k: invalid bin window.")

    # Calibrate the uncalibrated spectra
    print(f"Calibrating using T_hot={t_hot_k:.2f} K, T_cold={t_cold_k:.2f} K...")
    calib_uncalib_hot = calibrate_spectrum_to_temperature(
        uncalib_avg_hot, calib_avg_cold, calib_avg_hot, t_hot_k, t_cold_k
    )
    calib_uncalib_cold = calibrate_spectrum_to_temperature(
        uncalib_avg_cold, calib_avg_cold, calib_avg_hot, t_hot_k, t_cold_k
    )
    
    # Plot calibrated hot and cold averages
    header_meta = parse_header_csv(uncalib_dir)
    x, x_label = build_x_axis(calib_uncalib_hot.size, header_meta, "frequency")
    
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x, calib_uncalib_hot, label=f"Calibrated hot (N={n_uncalib_hot})", color="tab:red", linewidth=1.5)
    ax.plot(x, calib_uncalib_cold, label=f"Calibrated cold (N={n_uncalib_cold})", color="tab:blue", linewidth=1.5)
    apply_x_axis_format(ax, header_meta, "frequency", x_label)
    ax.set_ylabel("Brightness Temperature [K]")
    ax.set_xlabel(x_label)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")
    ax.set_title(f"Calibrated Hot/Cold Loads — {uncalib_dir.name}")
    
    # Save plot
    plot_dir = uncalib_dir / "calibrated_plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    plot_path = plot_dir / f"{uncalib_dir.name}_calibrated_hot_cold.png"
    fig.tight_layout()
    fig.savefig(plot_path, dpi=150)
    print(f"Saved calibrated plot to {plot_path}")
    
    plt.show()

def main():
    # locate data file relative to project
    project = PROJECT_ROOT
    data_file = project / "data" / "GroundSim0kmAlt.txt"
    if not data_file.exists():
        raise FileNotFoundError(f"{data_file} not found")

    # file has a header line; use skip_header_lines=1
    freq_hz, bt = read_two_column_file(data_file, skip_header_lines=1, delimiter=None)
    f_rx_ghz = 235.983
    # convert frequency to GHz for plotting
    freq_ghz = abs(freq_hz / 1e9 - f_rx_ghz)

    # output plot path
    plot_dir = project / "src" / "analysis" / "plots"
    plot_dir.mkdir(parents=True, exist_ok=True)
    plot_path = plot_dir / "GroundSim0kmAlt.png"

    # plot and save
    title = "GroundSim0kmAlt — Brightness temperature"
    plot_spectrum(freq_ghz, bt, xlabel="Frequency (GHz)", ylabel="Brightness temperature (K)",
                  title=title, figpath=str(plot_path), show=False)
    
    # Run interactive calibration workflow
    print("\n" + "="*60)
    print("Starting interactive calibration of measurement data...")
    print("="*60)
    calibrate_and_plot_ground_sim()

if __name__ == "__main__":
    main()
