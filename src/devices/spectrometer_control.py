#!/usr/bin/env python3
import time

import matplotlib.pyplot as plt
import numpy as np
import argparse
import code
import sys
import spectrometer_backend as pmc_backend


def plot_spectrum(data, bandwidth=4, fig_num=2, normalize=False):
    spectrum_sum = np.sum(data, 0)
    if normalize:
        norm = np.max(spectrum_sum)
    else:
        norm = 1
    spectrum = np.array(spectrum_sum / norm, dtype=float)
    freqs = np.linspace(0, bandwidth * 1000, 8192)
    fig = plt.figure(fig_num)
    plt.plot(freqs, np.log(spectrum) / np.log(10) * 20)
    fig.show()


def plot_adc(adc, *args):
    indices = range(0, len(adc[0][:]))
    fig = plt.figure(1)
    for channel in adc:
        plt.plot(indices, channel, *args)
    fig.show()


def plot_hist(adc, nbins=32):
    fig = plt.figure()
    adc_merged = sum(adc, [])  # unnest
    plt.hist(adc_merged, nbins, range=(0, 63))
    fig.show()


def plothist(adc, nbins=32):
    fig = plt.figure()
    adcm = sum(adc, [])  # unnest
    plt.hist(adcm, nbins, range=(0, 63))
    fig.show()
    ax.set_xlabel("Frequency [MHz]")
    ax.set_ylabel("Power [dB]")
    ax.set_title("Live Spectrum")
    ax.grid(True)

    while True:
        try:
            data, timestamps = pmc.meas_spectra(1)
            spectrum = np.array(data[0], dtype=float)
            freqs = np.linspace(0, bandwidth * 1000, len(spectrum))
            y_vals = 20 * np.log10(spectrum / np.max(spectrum))

            line.set_data(freqs, y_vals)
            ax.relim()
            positive_mask = spectrum > 0
            if spectrum.size == 0 or not np.any(positive_mask):
                time.sleep(1)
                continue

            max_spectrum = np.max(spectrum[positive_mask])
            normalized_spectrum = spectrum / max_spectrum
            normalized_spectrum = np.where(
                normalized_spectrum > 0,
                normalized_spectrum,
                np.finfo(float).tiny,
            )
            y_vals = 20 * np.log10(normalized_spectrum)
        except KeyboardInterrupt:
            print("Live measurement stopped.")
            break
        except Exception as exc:
            print(f"Error during live measurement: {exc}")
            time.sleep(1)


if __name__ == "__main__":
    # dev_name = b'\\Device\\NPF_{8164B0EB-67A2-4A12-A97C-846787F14DD6}'  # Dell Laptop OSAS-B
    dev_name = b"eth0"  # Raspberry Pi

    epilog = (
        "Quick interactive examples (when run with -i):\n"
        "  pmc.connect()                                # connect to device\n"
        "  pmc.setup_pmcc(pmc_backend.load('config/allregs.bin'), bandwidth='2GHz', int_time_ms=500)\n"
        "  pmc.readReg(0)                               # check connection (should output 6)\n"
        "  plothist(pmc.readADC())                      # test ADC utilization\n"
        "  save(pmc.readAll(),'test.bin')               # save register dump\n"
        "  d,t = pmc.meas_spectra(5); plot_spectrum(d)\n"
        "  t  # absolute timestamps; dt(t)  # relative timestamps\n"
    )

    parser = argparse.ArgumentParser(
        description="Spectrometer control helper",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--connect", action="store_true", help="call pmc.connect() after startup")
    parser.add_argument(
        "--setup",
        action="store_true",
        help="load registers and run pmc.setup_pmcc using --regs/--bandwidth/--int_time_ms",
    )
    parser.add_argument("--regs", default="config/allregs.bin", help="registers file to load")
    parser.add_argument("--bandwidth", default="2GHz", help="bandwidth for setup_pmcc")
    parser.add_argument("--int_time_ms", type=int, default=500, help="integration time for setup_pmcc")
    args = parser.parse_args()

    try:
        pmc = pmc_backend.PmcBackend(
            dev_name,
            window_coefficients_csv="config/wind_coeff_hamm.csv",
        )
    except Exception:
        raise RuntimeError("Make sure to execute this from the project root and not from within src/")

    if args.connect:
        pmc.connect()

    if args.setup:
        pmc.setup_pmcc(pmc_backend.load(args.regs), bandwidth=args.bandwidth, int_time_ms=args.int_time_ms)



