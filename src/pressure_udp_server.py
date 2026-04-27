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

from pressure_sensor import get_THP_from_MS8607

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5004


class PressureState:
    def __init__(self, log_interval=None, enable_logging=False, log_suffix="_pressure.csv"):
        self.lock = threading.Lock()
        self.log_interval = log_interval
        self.enable_logging = enable_logging
        self.log_thread = None
        self.stop_event = threading.Event()

        # Prepare CSV path under project_root/data/
        project_root = Path(__file__).resolve().parents[1]
        data_dir = project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Filename: YYYYmmddHHMMSS_pressure.csv
        self.start_ts = datetime.now()
        self.filename = self.start_ts.strftime("%Y%m%d%H%M%S") + log_suffix
        self.filepath = data_dir / self.filename

        self.fp = None
        self.writer = None

        if self.enable_logging and self.log_interval and self.log_interval > 0:
            self.start_logging()

    def _open_csv_if_needed(self):
        if self.fp is None:
            header = ["time", "temperature_K", "humidity_pct", "pressure_mbar"]
            self.fp = self.filepath.open("w", newline="")
            self.writer = csv.writer(self.fp, delimiter=",")
            self.writer.writerow(header)
            self.fp.flush()

    def read_once(self):
        # Serialize I2C access
        with self.lock:
            k_temp, humidity, pressure = get_THP_from_MS8607()
        # ISO-8601 timestamp (seconds precision) for convenience
        now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        return {
            "time": now,
            "temperature_K": k_temp,
            "humidity_pct": humidity,
            "pressure_mbar": pressure,
        }

    def _log_loop(self):
        self._open_csv_if_needed()
        try:
            while not self.stop_event.is_set():
                reading = self.read_once()
                row = [
                    reading["time"],
                    reading["temperature_K"],
                    reading["humidity_pct"],
                    reading["pressure_mbar"],
                ]
                self.writer.writerow(row)
                self.fp.flush()
                time.sleep(self.log_interval)
        finally:
            # Do not close here; let stop_logging handle it for symmetry
            pass

    def start_logging(self):
        if self.log_thread and self.log_thread.is_alive():
            return
        if not self.log_interval or self.log_interval <= 0:
            self.log_interval = 1.0
        self.stop_event.clear()
        self.log_thread = threading.Thread(
            target=self._log_loop,
            name="PressureLogger",
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


class PressureHandler(socketserver.BaseRequestHandler):
    # For UDP, self.request == (data, socket)
    def handle(self):
        data, sock = self.request
        raw = data.decode("ascii", errors="ignore").strip()
        try:
            cmd = raw.upper() if raw else "READ"

            if cmd == "PING":
                resp = b"OK PONG\n"

            elif cmd == "READ":
                reading = self.server.state.read_once()
                resp = (json.dumps(reading, separators=(",", ":")) + "\n").encode("ascii")

            # Optional logging control commands
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
    parser = argparse.ArgumentParser(description="Pressure UDP server (MS8607)")
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

    server = ThreadedUDPServer((args.host, args.port), PressureHandler)
    server.state = PressureState(
        log_interval=args.log_interval,
        enable_logging=args.background_log,
        log_suffix="_pressure.csv",
    )

    def shutdown(signum, frame):
        try:
            server.state.stop_logging()
        except Exception:
            pass
        try:
            server.shutdown()
        except Exception:
            pass

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.state.stop_logging()
        server.server_close()


if __name__ == "__main__":
    main()


