import os
import re
import tkinter as tk
from tkinter import filedialog, messagebox
import pandas as pd


def transform_file(input_path):
    df = pd.read_csv(input_path)

    required = {"timestamp", "sensor_id", "temperature_c"}
    if not required.issubset(df.columns):
        raise ValueError(
            "Input file must contain the columns: timestamp, sensor_id, temperature_c"
        )

    wide = (
        df.pivot_table(
            index="timestamp",
            columns="sensor_id",
            values="temperature_c",
            aggfunc="first",
        )
        .reset_index()
    )

    wide.columns.name = None

    sensor_columns = [col for col in wide.columns if col != "timestamp"]
    wide = wide[["timestamp"] + sorted(sensor_columns)]

    wide = wide.rename(
        columns={col: f"{col}_temp_C" for col in sensor_columns}
    )

    directory = os.path.dirname(input_path)
    filename = os.path.basename(input_path)

    match = re.match(r"^(.*)_temperature\.csv$", filename)
    if match:
        output_name = f"{match.group(1)}_temperature2.csv"
    else:
        stem, _ = os.path.splitext(filename)
        output_name = f"{stem}_temperature2.csv"

    output_path = os.path.join(directory, output_name)
    wide.to_csv(output_path, index=False)
    return output_path


def main():
    root = tk.Tk()
    root.withdraw()

    input_path = filedialog.askopenfilename(
        title="Select temperature CSV file",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
    )

    if not input_path:
        return

    try:
        output_path = transform_file(input_path)
        messagebox.showinfo(
            "Done",
            f"Converted file saved as:\n{output_path}",
        )
    except Exception as e:
        messagebox.showerror("Error", str(e))


if __name__ == "__main__":
    main()