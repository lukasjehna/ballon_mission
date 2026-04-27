#!/usr/bin/env python3
# This code is designed to work with the MS8607_02BA_I2CS I2C Mini Module available at
# [https://www.controleverything.com/products](https://www.controleverything.com/products)

import smbus
import time
import csv
import argparse
from datetime import datetime
from pathlib import Path

def get_THP_from_MS8607():
    # Get I2C bus
    bus = smbus.SMBus(1)

    # MS8607_02BA address, 0x76(118)
    #       0x1E(30)    Reset command
    bus.write_byte(0x76, 0x1E)
    time.sleep(0.5)

    # Read 12 bytes of calibration data
    data1 = bus.read_i2c_block_data(0x76, 0xA2, 2)  # SENST1
    data2 = bus.read_i2c_block_data(0x76, 0xA4, 2)  # OFFT1
    data3 = bus.read_i2c_block_data(0x76, 0xA6, 2)  # TCS
    data4 = bus.read_i2c_block_data(0x76, 0xA8, 2)  # TCO
    data5 = bus.read_i2c_block_data(0x76, 0xAA, 2)  # TREF
    data6 = bus.read_i2c_block_data(0x76, 0xAC, 2)  # TEMPSENS

    # Convert the data
    c1 = data1[0] * 256 + data1[1]
    c2 = data2[0] * 256 + data2[1]
    c3 = data3[0] * 256 + data3[1]
    c4 = data4[0] * 256 + data4[1]
    c5 = data5[0] * 256 + data5[1]
    c6 = data6[0] * 256 + data6[1]

    # Initiate pressure conversion (OSR = 256)
    bus.write_byte(0x76, 0x40)
    time.sleep(0.5)

    # Read D1 (pressure)
    data = bus.read_i2c_block_data(0x76, 0x00, 3)
    D1 = data[0] * 65536 + data[1] * 256 + data[2]

    # Initiate temperature conversion (OSR = 256)
    bus.write_byte(0x76, 0x50)
    time.sleep(0.5)

    # Read D2 (temperature)
    data0 = bus.read_i2c_block_data(0x76, 0x00, 3)
    D2 = data0[0] * 65536 + data0[1] * 256 + data0[2]

    # Compensation calculations
    dT = D2 - c5 * 256
    Temp = 2000 + dT * c6 / 8388608
    OFF = c2 * 131072 + (c4 * dT) / 64
    SENS = c1 * 65536 + (c3 * dT) / 128

    if Temp >= 2000:
        Ti = 5 * (dT * dT) / 274877906944
        OFFi = 0
        SENSi = 0
    else:
        Ti = 3 * (dT * dT) / 8589934592
        OFFi = 61 * ((Temp - 2000) * (Temp - 2000)) / 16
        SENSi = 29 * ((Temp - 2000) * (Temp - 2000)) / 16
        if Temp < -1500:
            OFFi = OFFi + 17 * ((Temp + 1500) * (Temp + 1500))
            SENSi = SENSi + 9 * ((Temp + 1500) * (Temp + 1500))

    OFF2 = OFF - OFFi
    SENS2 = SENS - SENSi
    cTemp = (Temp - Ti) / 100.0
    pressure = ((((D1 * SENS2) / 2097152) - OFF2) / 32768.0) / 100.0

    # Humidity part
    bus.write_byte(0x40, 0xFE)  # reset
    time.sleep(0.3)
    bus.write_byte(0x40, 0xF5)  # NO Hold master
    time.sleep(0.5)
    data0 = bus.read_byte(0x40)
    data1 = 0
    D3 = data0 * 256 + data1
    humidity = (-6.0 + (125.0 * (D3 / 65536.0)))

    # Convert Celsius to Kelvin
    kTemp = cTemp + 273.15

    # Round to two decimals using existing helper
    kTemp = two_decimals(kTemp)
    humidity = two_decimals(humidity)
    pressure = two_decimals(pressure)

    return (kTemp, humidity, pressure)

def two_decimals(number):
    stry = "%.2f" % number
    return float(stry)

def main(sample_interval=1.0, duration=None, print_only=False):
    """
    - sample_interval: seconds between measurements
    - duration: total seconds to run; None means run until Ctrl+C
    - print_only: if True, only print readings without saving to CSV
    """
    # Build data/ path relative to project root (parent of src)
    project_root = Path(__file__).resolve().parents[1]
    data_dir = project_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Filename: YYYYmmddHHMMSS_pressure.csv
    start_ts = datetime.now()
    filename = start_ts.strftime("%Y%m%d%H%M%S") + "_pressure.csv"
    filepath = data_dir / filename

    header = ["time", "temperature_K", "humidity_pct", "pressure_mbar"]

    fp = None
    writer = None
    print(f"Saved measurements to {filepath}")
    print("")
    print(",".join(header))
    if not print_only:
        fp = filepath.open("w", newline="")
        writer = csv.writer(fp, delimiter=",")
        writer.writerow(header)
        fp.flush()

    start_time = time.time()

    try:
        while True:
            kTemp, humidity, pressure = get_THP_from_MS8607()
            # Print timestamp in form [HH:MM:SS], e.g. [14:00:58]
            t_str = datetime.now().strftime("[%H:%M:%S]")
            row = [t_str, kTemp, humidity, pressure]

            # Save if not in print-only mode
            if writer is not None:
                writer.writerow(row)
                fp.flush()

            print("|".join(map(str, row)))

            if duration is not None and (time.time() - start_time) >= duration:
                break

            time.sleep(sample_interval)
    except KeyboardInterrupt:
        pass
    finally:
        if fp is not None:
            fp.close()

    if not print_only:
        print(f"Stopped logging")
    else:
        print("Print-only mode: no file saved.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read MS8607 and save or print measurements.")
    parser.add_argument("--print-only", action="store_true",
                        help="Print readings to stdout without saving to CSV.")
    args = parser.parse_args()

    # Example: 1 second sampling indefinitely; stop with Ctrl+C
    main(sample_interval=1.0, duration=None, print_only=args.print_only)

