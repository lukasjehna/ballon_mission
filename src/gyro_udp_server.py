#!/usr/bin/env python3
import argparse
import json
import signal
import socketserver
import threading
import time
from datetime import datetime

from gyro_sensor import init_sensor, read_sensor_data, save_data

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5003
DEFAULT_BUS = 1
DEFAULT_ADDRESS = 0x68

class GyroState:
    def __init__(self, log_interval=None, enable_logging=False, log_suffix="_gyro.csv"):
        self.lock = threading.Lock()
        self.log_interval = log_interval
        self.enable_logging = enable_logging
        self.log_thread = None
        self.stop_event = threading.Event()

        # Each server run gets its own timestamped file prefix
        self.ts = datetime.now().strftime("%Y%m%d%H%M%S")
        self.filename = log_suffix

        if self.enable_logging and self.log_interval and self.log_interval > 0:
            self.start_logging()

    def read_once(self):
        # Serialize I2C access
        with self.lock:
            return read_sensor_data()

    def _log_loop(self):
        while not self.stop_event.is_set():
            data = self.read_once()
            save_data(data, self.ts, self.filename)
            time.sleep(self.log_interval)

    def start_logging(self):
        if self.log_thread and self.log_thread.is_alive():
            return
        if not self.log_interval or self.log_interval <= 0:
            self.log_interval = 1.0
        self.stop_event.clear()
        self.log_thread = threading.Thread(
            target=self._log_loop,
            name="GyroLogger",
            daemon=True,  # do not block process exit
        )
        self.log_thread.start()

    def stop_logging(self):
        self.stop_event.set()
        if self.log_thread:
            self.log_thread.join(timeout=1.0)

class GyroHandler(socketserver.BaseRequestHandler):
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

            # Optional: remote control of logging
            elif cmd == "START":
                self.server.state.start_logging()
                resp = b"OK CONTINUOUS LOG STARTED\n"

            elif cmd == "STOP":
                self.server.state.stop_logging()
                resp = b"OK CONTINUOUS LOG STOPPED\n"

            else:
                resp = f"ERR unknown command: {raw}\n".encode("ascii")

        except Exception as e:
            resp = f"ERR {str(e)}\n".encode("ascii")

        sock.sendto(resp, self.client_address)

class ThreadedUDPServer(socketserver.ThreadingMixIn, socketserver.UDPServer):
    daemon_threads = True  # per-request handler threads are daemonic
    allow_reuse_address = True

def main():
    parser = argparse.ArgumentParser(description="Gyro UDP server (MPU6050)")
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host/interface")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="UDP port")
    parser.add_argument("--bus", type=int, default=DEFAULT_BUS, help="I2C bus number")
    parser.add_argument("--address", type=lambda x: int(x, 0), default=DEFAULT_ADDRESS,
                        help="I2C address (e.g. 0x68)")

    # New options
    parser.add_argument("--background-log", action="store_true",
                        help="enable continuous background logging to CSV")
    parser.add_argument("--log-interval", type=float, default=0.0,
                        help="logging interval in seconds (e.g. 0.1)")

    args = parser.parse_args()

    # Initialize sensor once at startup
    init_sensor(bus_number=args.bus, address=args.address)

    server = ThreadedUDPServer((args.host, args.port), GyroHandler)
    server.state = GyroState(
        log_interval=args.log_interval,
        enable_logging=args.background_log,
        log_suffix="_gyro.csv",
    )

    def shutdown(signum, frame):
        server.state.stop_logging()
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.state.stop_logging()
        server.server_close()

if __name__ == "__main__":
    main()


