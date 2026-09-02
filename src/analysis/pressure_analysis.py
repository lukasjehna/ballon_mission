from pathlib import Path

def get_series_specs():
    # Your CSV: time, temperature_c, humidity_pct, pressure_mbar or pressure_hpa
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

def preprocess_data(df):
    """Normalize pressure data to mbar if it's in hpa."""
    if "pressure_hpa" in df.columns:
        # hPa and mbar are equivalent (1 hPa = 1 mbar)
        df["pressure_mbar"] = df["pressure_hpa"]
    elif "pressure_mbar" not in df.columns:
        raise ValueError("No 'pressure_mbar' or 'pressure_hpa' column found")
    
    return df

def default_data_dir() -> Path:
    return Path("data")