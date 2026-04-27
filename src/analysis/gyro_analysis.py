# src/gyro_analysis.py
from pathlib import Path

def get_series_specs():
    return [
        # Gyro
        {"column": "gyro_x_dps", "label": "Gyro X", "unit": "°/s"},
        {"column": "gyro_y_dps", "label": "Gyro Y", "unit": "°/s"},
        {"column": "gyro_z_dps", "label": "Gyro Z", "unit": "°/s"},
        # Acceleration
        {"column": "accel_x_g", "label": "Accel X", "unit": "g"},
        {"column": "accel_y_g", "label": "Accel Y", "unit": "g"},
        {"column": "accel_z_g", "label": "Accel Z", "unit": "g"},
        # Integrated/estimated rotation (as present in your CSV)
        {"column": "rot_x_deg", "label": "Rot X", "unit": "°"},
        {"column": "rot_y_deg", "label": "Rot Y", "unit": "°"},
    ]

def default_data_dir() -> Path:
    return Path("data")
