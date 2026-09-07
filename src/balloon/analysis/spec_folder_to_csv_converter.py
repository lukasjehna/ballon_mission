#!/usr/bin/env python3
from __future__ import annotations

import csv
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

import spec_analysis_utils as sau


def select_folder(initialdir: Path | None = None) -> Path | None:
    root = tk.Tk()
    root.withdraw()
    root.update()
    path = filedialog.askdirectory(
        title="Select folder containing .spec files",
        initialdir=str(initialdir) if initialdir else None,
        mustexist=True,
    )
    root.destroy()
    return Path(path) if path else None


def spec_to_csv(spec_path: Path, output_dir: Path) -> Path:
    times, spectra, meta = sau.load_spec_file(spec_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{spec_path.stem}.csv"

    x, xlabel = sau.build_x_axis(spectra.shape[1], meta, "frequency")

    with out_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["timestamp_s", xlabel, "spectrum_index", "count"])
        for spectrum_index, (timestamp, spectrum) in enumerate(zip(times, spectra)):
            for x_value, count in zip(x, spectrum):
                writer.writerow(
                    [float(timestamp), float(x_value), spectrum_index, int(count)]
                )

    return out_path


def convert_folder(folder: Path) -> tuple[list[Path], list[tuple[Path, Exception]]]:
    output_dir = folder / "csv"
    spec_files = sorted(
        path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".spec"
    )

    converted: list[Path] = []
    failures: list[tuple[Path, Exception]] = []
    for spec_path in spec_files:
        try:
            converted.append(spec_to_csv(spec_path, output_dir))
        except Exception as exc:
            failures.append((spec_path, exc))

    return converted, failures


def main() -> None:
    folder = select_folder(Path.cwd())
    if folder is None:
        return

    spec_files = [
        path for path in folder.iterdir() if path.is_file() and path.suffix.lower() == ".spec"
    ]
    if not spec_files:
        messagebox.showinfo("No files found", f"No .spec files were found in:\n{folder}")
        return

    converted, failures = convert_folder(folder)
    output_dir = folder / "csv"

    if failures:
        failed_files = "\n".join(f"- {path.name}: {exc}" for path, exc in failures)
        messagebox.showwarning(
            "Conversion completed with errors",
            f"Converted {len(converted)} of {len(spec_files)} file(s).\n\n"
            f"CSV output folder:\n{output_dir}\n\n"
            f"Failed files:\n{failed_files}",
        )
    else:
        messagebox.showinfo(
            "Done",
            f"Converted {len(converted)} .spec file(s).\n\n"
            f"CSV files saved in:\n{output_dir}",
        )


if __name__ == "__main__":
    main()
