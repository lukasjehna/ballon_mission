import os
import glob
import time
import csv
import argparse

# Load kernel modules for the 1-Wire interface
os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

BASE_DIR = '/sys/bus/w1/devices/'

def find_sensors():
    sensors = glob.glob(BASE_DIR + '28-*')
    if not sensors:
        raise RuntimeError("No 1-Wire temperature sensors found.")
    return {os.path.basename(s): s + '/w1_slave' for s in sensors}

def read_temp_raw(device_file):
    with open(device_file, 'r') as f:
        return f.readlines()

def read_temp(device_file):
    lines = read_temp_raw(device_file)
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw(device_file)
    pos = lines[1].find('t=')
    if pos != -1:
        temp_c = float(lines[1][pos+2:]) / 1000.0
        return temp_c

def main():
    parser = argparse.ArgumentParser(
        description="Read temperatures from all connected 1-Wire DS18B20 sensors."
    )
    parser.add_argument(
        "--mode",
        choices=["print", "save"],
        default="print",
        help="Select 'print' to output to console or 'save' to log to file (CSV)."
    )
    parser.add_argument(
        "--file",
        default="temperatures.csv",
        help="Output file name (used only in save mode)."
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Time interval between readings in seconds."
    )
    args = parser.parse_args()

    sensors = find_sensors()
    print(f"Detected sensors: {', '.join(sensors.keys())}")

    if args.mode == "save":
        with open(args.file, "a", newline="") as f:
            writer = csv.writer(f, delimiter=",")
            writer.writerow(["timestamp", "sensor_id", "temperature_C"])

            try:
                while True:
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
                    for sensor_id, path in sensors.items():
                        temp_c = read_temp(path)
                        writer.writerow([timestamp, sensor_id, f"{temp_c:.3f}"])
                    f.flush()
                    time.sleep(args.interval)
            except KeyboardInterrupt:
                print(f"\nLogging stopped. Data saved to '{args.file}'.")
    else:
        try:
            while True:
                timestamp = time.strftime("%H:%M:%S")
                readings = []
                for sensor_id, path in sensors.items():
                    temp_c = read_temp(path)
                    readings.append(f"{sensor_id}: {temp_c:.2f} °C")
                print(f"[{timestamp}] " + " | ".join(readings))
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped by user.")

if __name__ == "__main__":
    main()
