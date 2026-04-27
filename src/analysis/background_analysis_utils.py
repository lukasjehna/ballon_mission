from pathlib import Path
from typing import Optional, Sequence, Tuple, Dict

import pandas as pd
import matplotlib.pyplot as plt


def load_data(csv_path: Path):
    df = pd.read_csv(csv_path)

    # Detect a suitable time column
    time_col = None
    for candidate in ("time", "timestamp"):
        if candidate in df.columns:
            time_col = candidate
            break

    if time_col is None:
        raise ValueError(
            f"No 'time' or 'timestamp' column found in {csv_path}"
        )

    # Parse as datetime
    df[time_col] = pd.to_datetime(df[time_col])

    # Ensure there is a 'time' column for plotting
    if "time" not in df.columns:
        df["time"] = df[time_col]

    return df


def choose_file(
    initialdir: Path,
    title: str = "Select data CSV",
    filetypes: Optional[Sequence[Tuple[str, str]]] = None,
) -> Optional[Path]:
    import tkinter as tk
    from tkinter import filedialog

    if filetypes is None:
        filetypes = [("CSV files", "*.csv"), ("All files", "*.*")]

    root = tk.Tk()
    root.withdraw()
    path = filedialog.askopenfilename(
        title=title,
        filetypes=filetypes,
        initialdir=str(initialdir),
    )
    root.destroy()
    return Path(path) if path else None


def plot_time_series(
    df,
    series_specs,
    title: str = "",
    csv_path: Optional[Path] = None,
    show: bool = True,
) -> Optional[Path]:
    """
    series_specs: list of dicts with keys:
        - column
        - label
        - unit
        - transform (optional function)

    If csv_path is given, save the figure as ../plot/<csv_stem>.png
    relative to this src/ folder and return that Path.
    """
    n = len(series_specs)
    fig, axes = plt.subplots(n, 1, figsize=(10, 3 * n), sharex=True)
    if n == 1:
        axes = [axes]
    if title:
        fig.suptitle(title)

    for ax, spec in zip(axes, series_specs):
        data = df[spec["column"]]
        if "transform" in spec and spec["transform"] is not None:
            data = spec["transform"](data)
        ax.plot(df["time"], data)
        ylabel = spec["label"]
        if spec.get("unit"):
            ylabel += f" [{spec['unit']}]"
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)

    axes[-1].set_xlabel("Time")
    fig.autofmt_xdate()
    fig.tight_layout(rect=[0, 0.03, 1, 0.95])

    out_path: Optional[Path] = None
    if csv_path is not None:
        csv_path = Path(csv_path).resolve()
        out_path = csv_path.with_suffix(".png")
        fig.savefig(out_path)

    if show:
        plt.show()

    return out_path


def _get_bandwidth_hz(meta: Dict[str, object], n_bins: int) -> Optional[float]:
    """
    Extract total bandwidth in Hz from meta['bandwidth'] if possible.
    Accepts values like '200 MHz', '50e6', '1 GHz', '2GHz',
    or plain numbers (assumed Hz).
    """
    bw = meta.get("bandwidth")
    if bw is None:
        return None

    s = str(bw).strip()
    s_lower = s.lower()

    # Remove unit suffixes from the numeric part
    for unit in ("ghz", "mhz", "khz", "hz"):
        if unit in s_lower:
            # split at the first occurrence of the unit string
            idx = s_lower.index(unit)
            num_part = s[:idx].strip()
            break
    else:
        num_part = s  # no unit found, assume pure number

    try:
        val = float(num_part)
    except ValueError:
        return None

    # Apply scaling based on unit
    if "ghz" in s_lower:
        val *= 1e9
    elif "mhz" in s_lower:
        val *= 1e6
    elif "khz" in s_lower:
        val *= 1e3
    # else: assume Hz

    return val

