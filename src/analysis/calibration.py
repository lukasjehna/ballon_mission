#!/usr/bin/env python3
import argparse
import csv
import sys
from pathlib import Path


def calibrate_temperature(counts, cold_counts, hot_counts, t_cold, t_hot):
    if hot_counts == cold_counts:
        raise ValueError("hot and cold calibration counts are identical; slope is undefined")
    return t_cold + (counts - cold_counts) / (hot_counts - cold_counts) * (t_hot - t_cold)


def main():
    parser = argparse.ArgumentParser(
        description="Convert spectrometer counts to calibrated temperature using hot/cold load calibration."
    )
    parser.add_argument("--counts", type=float, help="Measured counts")
    parser.add_argument("--cold-counts", type=float, help="Counts for the cold load")
    parser.add_argument("--hot-counts", type=float, help="Counts for the hot load")
    parser.add_argument("--t-cold", type=float, help="Cold load temperature")
    parser.add_argument("--t-hot", type=float, help="Hot load temperature")
    parser.add_argument("--csv", type=Path, help="Optional input CSV with columns: counts,cold_counts,hot_counts,t_cold,t_hot")
    parser.add_argument("--output", type=Path, help="Optional output CSV path for calibrated temperatures")
    args = parser.parse_args()

    if args.csv:
        rows = []
        with args.csv.open(newline="") as f:
            reader = csv.DictReader(f)
            required = {"counts", "cold_counts", "hot_counts", "t_cold", "t_hot"}
            if not required.issubset(reader.fieldnames or []):
                missing = sorted(required - set(reader.fieldnames or []))
                raise ValueError(f"CSV missing required columns: {', '.join(missing)}")
            for row in reader:
                temp = calibrate_temperature(
                    float(row["counts"]),
                    float(row["cold_counts"]),
                    float(row["hot_counts"]),
                    float(row["t_cold"]),
                    float(row["t_hot"]),
                )
                row["temperature"] = temp
                rows.append(row)

        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", newline="") as f:
                fieldnames = list(rows[0].keys()) if rows else ["counts", "cold_counts", "hot_counts", "t_cold", "t_hot", "temperature"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
        else:
            writer = csv.DictWriter(sys.stdout, fieldnames=list(rows[0].keys()) if rows else ["counts", "cold_counts", "hot_counts", "t_cold", "t_hot", "temperature"])
            writer.writeheader()
            writer.writerows(rows)
        return

    required_args = [args.counts, args.cold_counts, args.hot_counts, args.t_cold, args.t_hot]
    if any(v is None for v in required_args):
        parser.error("either provide --csv or all scalar arguments: --counts --cold-counts --hot-counts --t-cold --t-hot")

    temperature = calibrate_temperature(
        args.counts, args.cold_counts, args.hot_counts, args.t_cold, args.t_hot
    )
    print(temperature)


if __name__ == "__main__":
    main()
