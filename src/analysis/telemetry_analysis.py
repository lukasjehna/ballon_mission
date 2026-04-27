from pathlib import Path
import pandas as pd


def default_data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def default_csv_path() -> Path | None:
    data_dir = default_data_dir()

    candidates = sorted(data_dir.glob("*_system_telemetry.csv"))
    if candidates:
        return candidates[-1]  # latest by filename timestamp

    direct_name = data_dir / "system_telemetry.csv"
    if direct_name.exists():
        return direct_name

    typo_name = data_dir / "system_telemtry.csv"
    if typo_name.exists():
        return typo_name

    return None


def preprocess_data(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    if "timestamp" in df.columns and "time" not in df.columns:
        df = df.rename(columns={"timestamp": "time"})

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce")

    if "throttled" in df.columns:
        def _to_int(v):
            if isinstance(v, str) and v.startswith("0x"):
                try:
                    return int(v, 16)
                except ValueError:
                    return pd.NA
            return v

        df["throttled_int"] = df["throttled"].map(_to_int)

    return df


def get_series_specs():
    return [
        {"column": "cpu_temp_c", "label": "CPU Temp", "unit": "°C"},
        {"column": "pmic_temp_c", "label": "PMIC Temp", "unit": "°C"},
        {"column": "core_voltage_v", "label": "Core Voltage", "unit": "V"},
        {"column": "passive_state", "label": "Passive State", "unit": ""},
        {"column": "throttled_int", "label": "Throttled (int)", "unit": ""},
    ]
