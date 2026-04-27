#!/usr/bin/env python3
# Read DS18B20 temperatures from an arbitrary number of sensors.

import os
import glob
import time
import csv
import argparse
from pathlib import Path

# If needed, uncomment to load kernel modules for the 1-Wire interface
# os.system('modprobe w1-gpio')
# os.system('modprobe w1-therm')

BASE_DIR = '/sys/bus/w1/devices/'

def find_sensors():
    sensors = glob.glob(BASE_DIR + '28-*')
    if not sensors:
        raise RuntimeError("No 1-Wire temperature sensors found.")
    return {os.path.basename(s): s + '/w1_slave' for s in sensors}

def read_temp_raw(device_file):
    with open(device_file, 'r') as f:
        return f.readlines()

def read_temp(device_file, max_retries=10, retry_delay=0.2):
    # Retry until CRC line ends with YES and the t= field is present
    for _ in range(max_retries):
        lines = read_temp_raw(device_file)
        if lines and lines[0].strip().endswith('YES'):
            pos = lines[1].find('t=')
            if pos != -1:
                try:
                    return float(lines[1][pos+2:]) / 1000.0
                except ValueError:
                    pass
        time.sleep(retry_delay)
    return None  # give up after retries

def get_args():
    parser = argparse.ArgumentParser(
        description="Read temperatures from all connected 1-Wire DS18B20 sensors."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Time interval between readings in seconds."
    )
    parser.add_argument(
        "--print-only",
        action="store_true",
        help="Disable CSV logging; only print to console."
    )
    return parser.parse_args()

def main():
    args = get_args()
    script_dir = Path(__file__).resolve().parent           # e.g., .../balloon_mission/src
    data_dir = script_dir.parent / "data"                  # e.g., .../balloon_mission/data
    data_dir.mkdir(parents=True, exist_ok=True)

    timestamp_prefix = time.strftime("%Y%m%d%H%M%S")
    out_name = f"{timestamp_prefix}_temperature.csv"
    out_path = data_dir / out_name

    try:
        sensors = find_sensors()
    except RuntimeError as e:
        print(str(e))
        return

    print(f"Detected sensors: {', '.join(sensors.keys())}")
    print("timestamp, sensor_id, temperature °C")
    # Open CSV if logging is enabled (default)
    csv_file = None
    writer = None
    if not args.print_only:
        print(f"Data saved to '{out_path}'.\n")
        need_header = not out_path.exists() or out_path.stat().st_size == 0
        csv_file = open(out_path, "a", newline="")
        writer = csv.writer(csv_file, delimiter=",")
        if need_header:
            writer.writerow(["timestamp", "sensor_id", "temperature_c"])
            csv_file.flush()

    try:
        while True:
            ts = time.strftime("%H:%M:%S")
            line_parts = []
            for sensor_id, path in sensors.items():
                temp = read_temp(path)
                if temp is not None:
                    line_parts.append(f"{sensor_id}: {temp:.2f}")
                    if writer is not None:
                        writer.writerow([ts, sensor_id, f"{temp:.3f}"])
                else:
                    line_parts.append(f"{sensor_id}: NaN")
                    if writer is not None:
                        writer.writerow([ts, sensor_id, "NaN"])
            print(f"[{ts}] " + " | ".join(line_parts))
            if csv_file is not None:
                csv_file.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        if csv_file is not None:
            print(f"\nLogging stopped.")
        else:
            print("\nStopped by user.")
    finally:
        if csv_file is not None:
            csv_file.close()

if __name__ == "__main__":
    main()
