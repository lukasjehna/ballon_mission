# src/mpu6050_sensor.py
"""
MPU6050 Sensor Module
======================
Functions to initialize and read data from MPU6050 (gyroscope + accelerometer),
calculate tilt angles, and save data to CSV in the 'data/' folder.

Project Structure:
    project_root/
    ├── config/
    ├── data/          ← CSV files saved here
    ├── logs/
    ├── main.py
    ├── src/
    │   └── mpu6050_sensor.py
    └── ...
"""

import smbus
import math
import time
import csv
import os
from datetime import datetime
from pathlib import Path

# === Constants ===
POWER_MGMT_1 = 0x6B
DEFAULT_BUS = 1
DEFAULT_ADDRESS = 0x68

# === Global I2C bus ===
bus = None

# === Paths (relative to project root) ===
PROJECT_ROOT = Path(__file__).resolve().parent.parent  # src/ -> project root
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)  # Create data folder if not exists


def init_sensor(bus_number=DEFAULT_BUS, address=DEFAULT_ADDRESS):
    """
    Initialize I2C bus and wake up MPU6050.
    
    :param bus_number: I2C bus number (default: 1)
    :param address: MPU6050 I2C address (default: 0x68)
    """
    global bus
    bus = smbus.SMBus(bus_number)
    bus.write_byte_data(address, POWER_MGMT_1, 0)


def read_byte(reg, address=DEFAULT_ADDRESS):
    return bus.read_byte_data(address, reg)


def read_word(reg, address=DEFAULT_ADDRESS):
    h = bus.read_byte_data(address, reg)
    l = bus.read_byte_data(address, reg + 1)
    return (h << 8) + l


def read_word_2c(reg, address=DEFAULT_ADDRESS):
    val = read_word(reg, address)
    return -((65535 - val) + 1) if val >= 0x8000 else val


def dist(a, b):
    return math.sqrt(a * a + b * b)


def get_y_rotation(x, y, z):
    radians = math.atan2(x, dist(y, z))
    return -math.degrees(radians)


def get_x_rotation(x, y, z):
    radians = math.atan2(y, dist(x, z))
    return math.degrees(radians)


def read_gyroscope(address=DEFAULT_ADDRESS):
    gyro_x = read_word_2c(0x43, address) / 131.0
    gyro_y = read_word_2c(0x45, address) / 131.0
    gyro_z = read_word_2c(0x47, address) / 131.0
    return gyro_x, gyro_y, gyro_z


def read_accelerometer(address=DEFAULT_ADDRESS):
    accel_x = read_word_2c(0x3B, address) / 16384.0
    accel_y = read_word_2c(0x3D, address) / 16384.0
    accel_z = read_word_2c(0x3F, address) / 16384.0
    return accel_x, accel_y, accel_z


def read_sensor_data(address=DEFAULT_ADDRESS):
    """
    Read all sensor data and compute rotations.
    
    :return: Dict with gyroscope, accelerometer, and rotation
    """
    gyro_x, gyro_y, gyro_z = read_gyroscope(address)
    accel_x, accel_y, accel_z = read_accelerometer(address)
    x_rot = get_x_rotation(accel_x, accel_y, accel_z)
    y_rot = get_y_rotation(accel_x, accel_y, accel_z)

    return {
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],  # ms precision
        'gyroscope': {'x': gyro_x, 'y': gyro_y, 'z': gyro_z},
        'accelerometer': {'x': accel_x, 'y': accel_y, 'z': accel_z},
        'rotation': {'x': x_rot, 'y': y_rot}
    }


def save_data_to_csv(data, filename="mpu6050_log.csv"):
    """
    Save sensor data to CSV file in data/ folder.
    Appends new row. Creates file with header if not exists.
    
    :param data: Dict from read_sensor_data()
    :param filename: Name of CSV file (default: mpu6050_log.csv)
    """
    file_path = DATA_DIR / filename

    # Flatten data for CSV
    row = {
        'timestamp': data['timestamp'],
        'gyro_x': data['gyroscope']['x'],
        'gyro_y': data['gyroscope']['y'],
        'gyro_z': data['gyroscope']['z'],
        'accel_x': data['accelerometer']['x'],
        'accel_y': data['accelerometer']['y'],
        'accel_z': data['accelerometer']['z'],
        'rot_x': data['rotation']['x'],
        'rot_y': data['rotation']['y'],
    }

    file_exists = file_path.exists()

    with open(file_path, mode='a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


# === Example usage (for testing when run directly) ===
if __name__ == "__main__":
    init_sensor()
    print(f"Logging data to: {DATA_DIR / 'mpu6050_log.csv'}")
    try:
        while True:
            data = read_sensor_data()
            save_data_to_csv(data)
            print(f"[{data['timestamp']}] "
                  f"Gyro: ({data['gyroscope']['x']:.2f}, {data['gyroscope']['y']:.2f}, {data['gyroscope']['z']:.2f}) | "
                  f"Accel: ({data['accelerometer']['x']:.3f}, {data['accelerometer']['y']:.3f}, {data['accelerometer']['z']:.3f}) | "
                  f"Rot: X={data['rotation']['x']:.1f}°, Y={data['rotation']['y']:.1f}°")
            time.sleep(0.1)  # 10 Hz logging
    except KeyboardInterrupt:
        print("\nLogging stopped.")
