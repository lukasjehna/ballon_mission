#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.widgets import Button, Slider
import tkinter as tk
from tkinter import filedialog

import spec_analysis_utils as sau


def select_spec_file(initialdir: Path | None = None) -> Path | None:
    root = tk.Tk()
    root.withdraw()
    root.update()
    path = filedialog.askopenfilename(
        title="Select a .spec file",
        initialdir=str(initialdir) if initialdir else None,
        filetypes=[("SPEC files", "*.spec"), ("All files", "*.*")],
    )
    root.destroy()
    return Path(path) if path else None


class SpecFileViewer:
    def __init__(self, spec_path: Path, x_axis_mode: str = "frequency"):
        self.spec_path = spec_path
        self.x_axis_mode = x_axis_mode
        self.times, self.spectra, self.meta = sau.load_spec_file(spec_path)

        self.n_spectra, self.n_bins = self.spectra.shape
        self.x, self.xlabel = sau.build_x_axis(self.n_bins, self.meta, self.x_axis_mode)

        self.index = 0
        self.y_log = False

        self.mean_spec = np.mean(self.spectra.astype(float), axis=0)
        self.std_spec = np.std(self.spectra.astype(float), axis=0)
        self.lower = self.mean_spec - self.std_spec
        self.upper = self.mean_spec + self.std_spec

        self.fig, (self.ax_all, self.ax_stats, self.ax_single) = plt.subplots(
            3, 1, figsize=(12, 11), sharex=False
        )
        self.fig.subplots_adjust(bottom=0.24, hspace=0.42)

        self.log_button_ax = self.fig.add_axes([0.80, 0.06, 0.14, 0.06])
        self.log_button = Button(self.log_button_ax, "Log Y: OFF")
        self.log_button.on_clicked(self.toggle_log_y)

        self.slider_ax = self.fig.add_axes([0.12, 0.07, 0.58, 0.04])
        self.slider = Slider(
            self.slider_ax,
            "Spectrum",
            1,
            max(1, self.n_spectra),
            valinit=1,
            valstep=1,
        )
        self.slider.on_changed(self.on_slider)

        self.prev_ax = self.fig.add_axes([0.12, 0.01, 0.08, 0.05])
        self.next_ax = self.fig.add_axes([0.21, 0.01, 0.08, 0.05])
        self.prev_button = Button(self.prev_ax, "Prev")
        self.next_button = Button(self.next_ax, "Next")
        self.prev_button.on_clicked(lambda _event: self.step(-1))
        self.next_button.on_clicked(lambda _event: self.step(1))

        self.fig.canvas.mpl_connect("key_press_event", self.on_key)
        self.draw()

    def toggle_log_y(self, _event) -> None:
        self.y_log = not self.y_log
        self.log_button.label.set_text("Log Y: ON" if self.y_log else "Log Y: OFF")
        self.draw()

    def on_slider(self, val) -> None:
        idx = int(val) - 1
        if idx != self.index:
            self.index = idx
            self.draw()

    def step(self, delta: int) -> None:
        self.index = max(0, min(self.n_spectra - 1, self.index + delta))
        self.slider.set_val(self.index + 1)
        self.draw()

    def on_key(self, event) -> None:
        if event.key in ("left", "up"):
            self.step(-1)
        elif event.key in ("right", "down"):
            self.step(1)
        elif event.key == "home":
            self.index = 0
            self.slider.set_val(1)
            self.draw()
        elif event.key == "end":
            self.index = self.n_spectra - 1
            self.slider.set_val(self.n_spectra)
            self.draw()
        elif event.key == "l":
            self.toggle_log_y(None)

    def _clear_axes(self) -> None:
        for ax in (self.ax_all, self.ax_stats, self.ax_single):
            ax.cla()
            ax.grid(True, alpha=0.3, which="both")
            ax.set_yscale("log" if self.y_log else "linear")

    def draw(self) -> None:
        self._clear_axes()

        # Top subplot: all spectra in the file
        for spectrum in self.spectra:
            self.ax_all.plot(self.x, spectrum, color="tab:blue", alpha=0.12, linewidth=0.8)
        self.ax_all.set_title(f"{self.spec_path.name} — all spectra")
        self.ax_all.set_ylabel("Counts")

        # Middle subplot: mean and std
        self.ax_stats.plot(self.x, self.mean_spec, color="tab:blue", linewidth=1.5, label="Mean")
        self.ax_stats.plot(self.x, self.upper, color="tab:orange", linewidth=1.0, linestyle="--", label="Mean + 1 std")
        self.ax_stats.plot(self.x, self.lower, color="tab:orange", linewidth=1.0, linestyle="--", label="Mean - 1 std")
        self.ax_stats.fill_between(self.x, self.lower, self.upper, color="tab:orange", alpha=0.2)
        self.ax_stats.set_title("Mean and standard deviation")
        self.ax_stats.set_ylabel("Counts")
        self.ax_stats.legend(loc="best")

        # Bottom subplot: single spectrum browser
        spectrum = self.spectra[self.index]
        self.ax_single.plot(self.x, spectrum, color="tab:green", linewidth=1.2)
        self.ax_single.set_title(f"Spectrum {self.index + 1}/{self.n_spectra}")
        self.ax_single.set_xlabel(self.xlabel)
        self.ax_single.set_ylabel("Counts")

        for ax in (self.ax_all, self.ax_stats, self.ax_single):
            ax.set_xscale("linear")

        nspectra = self.meta.get("n_spectra") if isinstance(self.meta, dict) else None
        inttime = self.meta.get("inttimems") if isinstance(self.meta, dict) else None
        bandwidth = self.meta.get("bandwidth") if isinstance(self.meta, dict) else None
        info_bits = []
        if nspectra is not None:
            info_bits.append(f"N={nspectra}")
        if inttime is not None:
            info_bits.append(f"t={inttime} ms")
        if bandwidth is not None:
            info_bits.append(f"BW={bandwidth}")
        if info_bits:
            self.ax_all.text(
                0.01,
                0.98,
                ", ".join(info_bits),
                transform=self.ax_all.transAxes,
                va="top",
                ha="left",
                fontsize=9,
                bbox=dict(facecolor="white", alpha=0.75, edgecolor="none"),
            )

        self.fig.canvas.draw_idle()

    def show(self) -> None:
        plt.show()


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Interactively view one .spec file with three subplots: all spectra, mean/std, and a single-spectrum browser."
    )
    parser.add_argument("spec_file", nargs="?", default=None, help="Path to a .spec file. If omitted, a file picker opens.")
    parser.add_argument(
        "--x-axis",
        dest="xaxis",
        choices=["frequency", "bins", "sidebands"],
        default="frequency",
        help="X-axis mode.",
    )
    args = parser.parse_args(argv)

    if args.spec_file is None:
        chosen = select_spec_file(Path.cwd())
        if chosen is None:
            print("No file selected. Exiting.")
            return
        spec_path = chosen
    else:
        spec_path = Path(args.spec_file).expanduser().resolve()

    if not spec_path.is_file() or spec_path.suffix.lower() != ".spec":
        print(f"Not a .spec file: {spec_path}")
        return

    viewer = SpecFileViewer(spec_path, x_axis_mode=args.xaxis)
    viewer.show()


if __name__ == "__main__":
    main(sys.argv[1:])
