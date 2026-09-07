from pathlib import Path

def get_series_specs():
    return [
        {
            "column": "temperature_c",  # <-- lowercase c to match CSV
            "label": "Temperature",
            "unit": "°C",
        },
    ]

def default_data_dir() -> Path:
    return Path("data")
