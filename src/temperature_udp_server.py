#!/usr/bin/env python3
import argparse
import csv
import json
import signal
import socketserver
import threading
import time
from datetime import datetime
from pathlib import Path

# Import the necessary functions from your temperature module
from temperature_sensor import find_sensors, read_temp

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5006


class TemperatureState:
    def __init__(self, log_interval=None, enable_logging=False, log_suffix="_temperature.csv"):
        self.lock = threading.Lock()
        try:
            # Map sensor_id -> device file path
            self.sensors = find_sensors()
        except Exception:
            # Start with no sensors if discovery fails; server remains available
            self.sensors = {}

        self.log_interval = log_interval
        self.enable_logging = enable_logging
        self.log_thread = None
        self.stop_event = threading.Event()

        # Prepare CSV path under project_root/data/
        script_dir = Path(__file__).resolve().parent      # e.g., .../balloon_mission/src
        data_dir = script_dir.parent / "data"             # e.g., .../balloon_mission/data
        data_dir.mkdir(parents=True, exist_ok=True)

        timestamp_prefix = datetime.now().strftime("%Y%m%d%H%M%S")
        self.filename = f"{timestamp_prefix}{log_suffix}"
        self.filepath = data_dir / self.filename

        self.fp = None
        self.writer = None

        if self.enable_logging and self.log_interval and self.log_interval > 0:
            self.start_logging()

    def _open_csv_if_needed(self):
        if self.fp is None:
            need_header = not self.filepath.exists() or self.filepath.stat().st_size == 0
            self.fp = self.filepath.open("a", newline="")
            self.writer = csv.writer(self.fp, delimiter=",")
            if need_header:
                # timestamp, sensor_id, temperature_c  (one row per sensor)
                self.writer.writerow(["timestamp", "sensor_id", "temperature_c"])
                self.fp.flush()

    def list_ids(self):
        return list(self.sensors.keys())

    def read_all_once(self):
        # Serialize filesystem access to the 1‑Wire devices
        with self.lock:
            readings = {}
            for sensor_id, path in self.sensors.items():
                val = read_temp(path)
                readings[sensor_id] = None if val is None else round(val, 3)
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        return {"time": now, "temperatures_c": readings}

    def _log_loop(self):
        self._open_csv_if_needed()
        try:
            while not self.stop_event.is_set():
                reading = self.read_all_once()
                ts = reading["time"]
                for sensor_id, temp in reading["temperatures_c"].items():
                    if temp is None:
                        self.writer.writerow([ts, sensor_id, "NaN"])
                    else:
                        self.writer.writerow([ts, sensor_id, f"{temp:.3f}"])
                self.fp.flush()
                time.sleep(self.log_interval)
        finally:
            # Let stop_logging handle actual close for symmetry
            pass

    def start_logging(self):
        if self.log_thread and self.log_thread.is_alive():
            return
        if not self.log_interval or self.log_interval <= 0:
            self.log_interval = 1.0
        self.stop_event.clear()
        self.log_thread = threading.Thread(
            target=self._log_loop,
            name="TemperatureLogger",
            daemon=True,  # do not block interpreter exit
        )
        self.log_thread.start()

    def stop_logging(self):
        self.stop_event.set()
        if self.log_thread:
            self.log_thread.join(timeout=1.0)
        if self.fp is not None:
            try:
                self.fp.close()
            except Exception:
                pass
            self.fp = None
            self.writer = None


class TemperatureHandler(socketserver.BaseRequestHandler):
    # For UDP, self.request == (data, socket)
    def handle(self):
        data, sock = self.request
        raw = data.decode("ascii", errors="ignore").strip()
        try:
            cmd = raw.upper() if raw else "READ"
            if cmd == "PING":
                resp = b"OK PONG\n"
            elif cmd == "READ":
                reading = self.server.state.read_all_once()
                resp = (json.dumps(reading, separators=(",", ":")) + "\n").encode("ascii")
            elif cmd == "LIST":
                ids = self.server.state.list_ids()
                resp = (json.dumps({"sensors": ids}, separators=(",", ":")) + "\n").encode("ascii")
            # Optional: remote control of logging
            elif cmd == "START":
                self.server.state.start_logging()
                resp = b"OK LOG STARTED\n"
            elif cmd == "STOP":
                self.server.state.stop_logging()
                resp = b"OK LOG STOPPED\n"
            else:
                resp = f"ERR unknown command: {raw}\n".encode("ascii")
        except Exception as e:
            resp = f"ERR {str(e)}\n".encode("ascii")
        sock.sendto(resp, self.client_address)


class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    parser = argparse.ArgumentParser(
        description="Temperature UDP server (DS18B20 via 1‑Wire)"
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host/interface")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port")

    # New options for background logging
    parser.add_argument(
        "--background-log",
        action="store_true",
        help="enable continuous background logging to CSV",
    )
    parser.add_argument(
        "--log-interval",
        type=float,
        default=0.0,
        help="logging interval in seconds (e.g. 1.0)",
    )

    args = parser.parse_args()

    server = ThreadedUDPServer((args.host, args.port), TemperatureHandler)
    server.state = TemperatureState(
        log_interval=args.log_interval,
        enable_logging=args.background_log,
        log_suffix="_temperature.csv",
    )

    def _shutdown(signum, frame):
        try:
            server.state.stop_logging()
        except Exception:
            pass
        try:
            server.shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.state.stop_logging()
        server.server_close()


if __name__ == "__main__":
    main()


