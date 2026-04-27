#!/usr/bin/env python3
import time

import libpcap as pcap
import matplotlib.pyplot as plt
import numpy as np

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
def plothist(adc,nbins=32):
     fig=plt.figure()
     adcm=sum(adc,[]) #unnest
     plt.hist(adcm,nbins,range=(0,63))
     fig.show()

def live_measurement(pmc, bandwidth=4, delay=0.5):
    plt.ion()  # interactive mode

    fig, ax = plt.subplots()
    line, = ax.plot([], [])
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
            ax.autoscale_view()
            plt.pause(delay)
        except KeyboardInterrupt:
            print("Live measurement stopped.")
            break
        except Exception as exc:
            print(f"Error during live measurement: {exc}")
            time.sleep(1)


if __name__ == "__main__":
    # dev_name = b'\\Device\\NPF_{8164B0EB-67A2-4A12-A97C-846787F14DD6}'  # Dell Laptop OSAS-B
    dev_name = b"eth0"  # Raspberry Pi

    print(pcap.lib_version())
    try:
        pmc = pmc_backend.PmcBackend(
            dev_name,
            window_coefficients_csv="config/wind_coeff_hamm.csv",
        )
    except Exception:
        raise RuntimeError(
            "Make sure to execute this from the project root and not from within src/"
        )
    # time.sleep(1)
    # pmc.connect()


