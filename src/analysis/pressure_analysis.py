# sensors/pressure.py
from pathlib import Path

def get_series_specs():
    # Your CSV: time, temperature_c, humidity_pct, pressure_mbar
    return [
        {
            "column": "temperature_c",
            "label": "Temperature",
            "unit": "°C",
            "transform": lambda s: s - 273.15,
        },
        {
            "column": "humidity_pct",
            "label": "Humidity",
            "unit": "%",
        },
        {
            "column": "pressure_mbar",
            "label": "Pressure",
            "unit": "mbar",
        },
    ]

def default_data_dir() -> Path:
    # e.g. you keep logs under data/
    return Path("data")
