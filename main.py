# use sudo fuser -k 5126/udp to kill a process from another shell
# Make sure to run this with via run_python_measurement.sh to start the udp servers.
import socket
import time
import os
import sys
import signal
import json
import argparse
sys.path.append(os.path.join(os.path.dirname(__file__), 'src')) # Add src/ to path

# add LED control import
from devices import led_control

os.umask(0o000) #no default restriction for files

chopper=5001
receiver=5002
gyro=5003
pressure=5004
spectrometer=5005
temperature=5006
telemetry=5007
SOCKET_TYPE={'UDP':socket.SOCK_DGRAM,'TCP':socket.SOCK_STREAM}
TIMEOUT = 10
SPECTROMETER_TIMEOUT = 120
IP= '127.0.0.1'

f_s_ghz = 235.710 # Signal frequeny
f_if_start_ghz = 0.100  # 100 MHz
f_if_step_ghz = 0.01  # 10 MHz

points_per_sideband = 20

# USB and LSB are defined realtive to LO. Because we use f_s its reveresed.
DEFAULT_FREQ_GHZ_LIST = (
    [round(f_s_ghz - f_if_start_ghz - i * f_if_step_ghz, 6)
     for i in range(points_per_sideband)] # USB
    +
    [round(f_s_ghz + f_if_start_ghz + i * f_if_step_ghz, 6)
     for i in range(points_per_sideband)] # LSB
)

DEFAULT_BW = "2GHz"
DEFAULT_INT_MS = 500
DEFAULT_N_SPECTRA = 20
DEFAULT_N_ITERATIONS = 2
DEFAULT_SETTLE_TIME_S = 2.1
DEFAULT_OUT_DIR = "data/"

ports = {
    chopper: "chopper",
    receiver: "receiver",
    gyro: "gyro",
    pressure: "pressure",
    spectrometer: "spectrometer",
    temperature: "temperature",
    telemetry: "telemetry",
}

# Global flag set by Ctrl+C
_stop_requested = False
print("Run this python script via run_python_measurement.sh to start the device udp server.")
def _sigint_handler(signum, frame):
    """
    Signal handler for SIGINT (Ctrl+C).
    It does NOT abort the program immediately, but asks the
    hot/cold loop to finish the current iteration and then stop.
    """
    global _stop_requested
    print("Ctrl+C detected: will stop after the current hot/cold cycle.")
    _stop_requested = True

def _cmd_preview(command, max_len=120):
    try:
        s = command.decode("utf-8", errors="replace").strip()
    except Exception:
        s = repr(command)
    return s if len(s) <= max_len else s[:max_len] + "..."

def cmd(port, command, ip=IP, noansw=0, answerTerminated=True, packetlen=1024, timeout=TIMEOUT, socketType='UDP'):
    try:
        pname = ports.get(port, str(port))
    except Exception:
        pname = str(port)

    cmd_preview = _cmd_preview(command)
    proto = SOCKET_TYPE.get(socketType, socket.SOCK_DGRAM)
    answ = b''

    with socket.socket(socket.AF_INET, proto) as s:
        s.settimeout(timeout)

        try:
            if socketType == 'UDP':
                s.sendto(command, (ip, port))
            else:
                s.connect((ip, port))
                s.sendall(command)
        except Exception as exc:
            print(f"cmd send error to {pname}({port}) cmd='{cmd_preview}': {exc}")
            return b''

        if noansw:
            return b''

        try:
            data = s.recv(packetlen)
            if not data:
                print(f"empty reply from {pname}({port}) cmd='{cmd_preview}'")
                return b''
            answ += data

            if answerTerminated:
                while answ and answ[-1] != 10:
                    try:
                        data = s.recv(packetlen)
                        if not data:
                            break
                        answ += data
                    except socket.timeout:
                        break
            else:
                while len(answ) < packetlen:
                    try:
                        data = s.recv(packetlen - len(answ))
                        if not data:
                            break
                        answ += data
                    except socket.timeout:
                        break

        except socket.timeout:
            print(f"socket timeout on {pname}({port}) cmd='{cmd_preview}', received={answ!r}")
            return answ
        except Exception as exc:
            print(f"cmd recv error from {pname}({port}) cmd='{cmd_preview}': {exc}")
            return answ

    # If server returns JSON status=err, print it with service name.
    try:
        txt = answ.decode("utf-8", errors="replace").strip()
        if txt.startswith("{"):
            payload = json.loads(txt)
            if isinstance(payload, dict) and payload.get("status") == "err":
                print(
                    f"server error from {pname}({port}) cmd='{cmd_preview}': "
                    f"{payload.get('error', payload)}"
                )
    except Exception:
        pass

    return answ
    
def chopper_set(angle):
    # Reuse your cmd() with socketType='UDP'
    return cmd(chopper, f"{angle:.1f}\n".encode(), socketType='UDP')

def receiver_set(f):
    # Reuse your cmd() with socketType='UDP'
    return cmd(receiver, f"{f:.1f}\n".encode(), socketType='UDP')

def gyro_start_continuous():
    return cmd(gyro, b"START\n", socketType='UDP')

def gyro_stop_continuous():
    return cmd(gyro, b"STOP\n", socketType='UDP')

def gyro_read():
    # Ask the gyro UDP server for a one-shot reading. 
    return cmd(gyro, b"READ\n", socketType='UDP')

def pressure_read():
    # Ask the pressure UDP server for a one-shot reading. 
    return cmd(pressure, b"READ\n", socketType='UDP')

def pressure_start_continuous():
    return cmd(pressure, b"START\n", socketType='UDP')

def pressure_stop_continuous():
    return cmd(pressure, b"STOP\n", socketType='UDP')

def temperature_read():
    # Ask the pressure UDP server for a one-shot reading. 
    return cmd(temperature, b"READ\n", socketType='UDP')

def temperature_start_continuous():
    return cmd(temperature, b"START\n", socketType='UDP')

def temperature_stop_continuous():
    return cmd(temperature, b"STOP\n", socketType='UDP')

def read_telemetry():
    raw = cmd(telemetry, b"READ\n")
    # Expecting a JSON line like {"timestamp": "...", "cpu_temp_c": ..., ...}\n
    return json.loads(raw.decode("ascii"))


def start_continuous_telemetry():
    """
    Tell the system telemetry server to start background CSV logging.
    """
    cmd(telemetry, b"START\n", noansw=1)


def stop_continuous_telemetry():
    """
    Tell the system telemetry server to stop background CSV logging.
    """
    cmd(telemetry, b"STOP\n", noansw=1)

def spectrometer_control(buf, timeout=SPECTROMETER_TIMEOUT): 
    return cmd(spectrometer,buf.encode('utf-8'), timeout=timeout, socketType='UDP')
#buf message form:
#INIT 2 GHz 500

def spectrometer_connect():
    return spectrometer_control("CONN")

def spectrometer_init(bw="2GHz", int_ms=500):
    return spectrometer_control(f"INIT {bw} {int_ms}")

def spectrometer_adc(out_dir="data/"):
    return spectrometer_control(f"ADC {out_dir}")

def spectrometer_meas(n_spectra=1, out_dir="data/"):
    return spectrometer_control(f"MEAS {n_spectra} {out_dir}")

def spectrometer_meas_repeated(n_cycles=1, n_spectra_per_per_cycle=1, out_dir="data/", wait_s=1.0):
    for i in range(n_cycles):
        spectrometer_meas(n_spectra=n_spectra_per_per_cycle, out_dir=out_dir)
        if _stop_requested:
            print("Stop requested, ending spectromter_meas_repeated loop.")
            break

        if i < n_cycles - 1:
            time.sleep(wait_s)

def spectrometer_create_timestamp_dir(out_root="data/"):
    return spectrometer_control(f"DIR {out_root}")

def spectrometer_write_header(
    out_dir,
    f_rx_ghz,
    bw,
    n_iterations,
    int_ms,
    n_spectra=None,
):
    """
    Ask the spectrometer server to write a header CSV into out_dir
    containing f_RX, bandwidth, n_iterations, integration time, and n_spectra.
    """
    parts = [f"HEAD {out_dir}"]
    # Number of spectra per iteration
    if n_spectra is not None:
        parts.append(str(int(n_spectra)))
    else:
        parts.append("None")

    # f_rx_ghz, bw, n_iterations, int_ms
    parts.append(f"{float(f_rx_ghz):.6f}")
    parts.append(str(bw))
    parts.append(str(int(n_iterations)))
    parts.append(str(int(int_ms)))

    cmd_str = " ".join(parts)
    return spectrometer_control(cmd_str)

def spectrometer_hot_cold(n_spectra, out_dir, tag):
    tag = str(tag).lower()
    return spectrometer_control(f"HOTCOLD {int(n_spectra)} {out_dir} {tag}")


def start_background_measurements():
    print("Starting background measurements (gyro, pressure, temperature, telemetry).")
    gyro_start_continuous()
    pressure_start_continuous()
    temperature_start_continuous()
    start_continuous_telemetry()

def stop_background_measurements():
    print("Stopping background measurements (gyro, pressure, temperature, telemetry).")
    gyro_stop_continuous()
    pressure_stop_continuous()
    temperature_stop_continuous()
    stop_continuous_telemetry()

# takes the first frequency from the list.
def run_hot_cold_cycles(
    freq_ghz=DEFAULT_FREQ_GHZ_LIST[0],
    bw=DEFAULT_BW,
    int_ms=DEFAULT_INT_MS,
    n_spectra=DEFAULT_N_SPECTRA,
    n_iterations=DEFAULT_N_ITERATIONS,
    settle_time_s=DEFAULT_SETTLE_TIME_S,
    out_dir=DEFAULT_OUT_DIR,
    connect=True,
    initialize=True,
):
    """
    Perform gas spectroscopy hot/cold cycles with the chopper.
    Ctrl+C (SIGINT) will be caught and converted into a request to stop
    """

    print(
        f"Starting gas spectroscopy: f={freq_ghz} GHz, "
        f"n_spectra={n_spectra}, iterations={n_iterations}, "
        f"settle={settle_time_s} s, out_dir='{out_dir}'"
    )

    print(f"Setting receiver frequency to {freq_ghz} GHz")
    receiver_set(freq_ghz)

    if connect:
        print("Open and configure a libpcap capture handle for the spectrometer link")
        spectrometer_connect()
    else:
        print("Skipping spectrometer connect (connect=False).")    

    if initialize:
        print(f"Initialize spectrometer with bw={bw} and int_ms={int_ms}.")
        spectrometer_init(bw=bw, int_ms=int_ms)
    else:
        print("Skipping spectrometer init (initialize=False).")

    print(f"Creating session directory under '{out_dir}'")
    dir_resp = spectrometer_create_timestamp_dir(out_dir)
    try:
        dir_info = json.loads(dir_resp.decode("ascii"))
    except Exception as exc:
        raise RuntimeError(f"Failed to parse DIR response: {dir_resp!r}") from exc

    if dir_info.get("status") != "ok":
        raise RuntimeError(f"DIR command failed: {dir_info}")

    session_dir = dir_info["session_dir"]
    print(f"Using session directory: {session_dir}")

    print(
        f"Writing header CSV in '{session_dir}' "
        f"(n_spectra_hint={n_spectra})"
    )

    spectrometer_write_header(
        out_dir=session_dir,
        f_rx_ghz=freq_ghz,
        bw=bw,
        n_iterations=n_iterations,
        int_ms=int_ms,
        n_spectra=n_spectra,
    )

    # 5) Perform hot–cold cycles with tagged measurements
    cycle = 0
    while cycle < n_iterations and not _stop_requested:
        cycle += 1

        # HOT
        print(f"Cycle {cycle}/{n_iterations}: HOT position (0 deg)")
        chopper_set(10)
        time.sleep(settle_time_s)
        spectrometer_hot_cold(n_spectra=n_spectra,
                                out_dir=session_dir,
                                tag="hot")

        if _stop_requested:
            break

        # COLD
        print(f"Cycle {cycle}/{n_iterations}: COLD position (45 deg)")
        chopper_set(65)
        time.sleep(settle_time_s)
        spectrometer_hot_cold(n_spectra=n_spectra,
                                out_dir=session_dir,
                                tag="cold")

    if _stop_requested:
        print("Stop requested: exiting after the last completed hot/cold cycle.")
    else:
        print("Gas spectroscopy hot/cold cycles completed.")



def run_full_measurement(
    freq_ghz=DEFAULT_FREQ_GHZ_LIST, #f_S-f_IF = 235.71 GHz-0.2097 GHz = 235.5003 GHz = f_LO USB
    bw=DEFAULT_BW,
    int_ms=DEFAULT_INT_MS,
    n_spectra=DEFAULT_N_SPECTRA,
    n_iterations=DEFAULT_N_ITERATIONS,
    settle_time_s=DEFAULT_SETTLE_TIME_S,
    out_dir=DEFAULT_OUT_DIR
):
    """
    - Starts continuous background measurements.
    - Sets up Libpcap and initializes the spectrometer once at the start.
    - Calls run_hot_cold_cycles() with one frequency at a time.
    - Loops over all requested frequencies.
    """
    global _stop_requested
    _stop_requested = False

    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, _sigint_handler)

    # Normalize to list[float]
    if isinstance(freq_ghz, (int, float)):
        freq_list = [float(freq_ghz)]
    else:
        freq_list = [float(f) for f in freq_ghz]

    # Initialize LEDs and ensure they are turned off at the end
    red_pwm = green_pwm = blue_pwm = None
    try:
        red_pwm, green_pwm, blue_pwm = led_control.init_leds()
        # set LED color (adjust values as desired)
        led_control.set_color(red_pwm, green_pwm, blue_pwm, 0.2, 0.2, 0.2)

        start_background_measurements()
        try:
            print("Connecting spectrometer once before frequency loop.")
            spectrometer_connect()
            print(f"Initializing spectrometer once: bw={bw}, int_ms={int_ms}.")
            spectrometer_init(bw=bw, int_ms=int_ms)

            for i, f_ghz in enumerate(freq_list, start=1):
                if _stop_requested:
                    print("Stop requested, ending frequency loop.")
                    break

                print(f"\n=== Frequency {i}/{len(freq_list)}: {f_ghz} GHz ===")
                run_hot_cold_cycles(
                    freq_ghz=f_ghz,
                    bw=bw,
                    int_ms=int_ms,
                    n_spectra=n_spectra,
                    n_iterations=n_iterations,
                    settle_time_s=settle_time_s,
                    out_dir=out_dir,
                    connect=False,  
                    initialize=False, 
                )
        finally:
            stop_background_measurements()
    finally:
        if red_pwm is not None:
            led_control.cleanup(red_pwm, green_pwm, blue_pwm)

def parse_args():
    parser = argparse.ArgumentParser(
        description="Control devices and optionally run gas spectroscopy hot/cold cycles."
    )

    # background + spectroscopy
    parser.add_argument(
        "--full",
        action="store_true",
        help="run gas spectroscopy hot/cold measurement sequence.",
    )

    # Only background
    parser.add_argument(
        "--no-spectrometer",
        action="store_true",
        help="No connect and no initialization.",
    )

    parser.add_argument(
        "--freq-ghz",
        type=float,
        nargs="+",
        default=DEFAULT_FREQ_GHZ_LIST,
        help="One or more receiver frequencies in GHz (default:%(default)s).",
    )
    parser.add_argument(
        "--bw",
        type=str,
        default=DEFAULT_BW,
        help="Spectrometer bandwidth string (default: %(default)s).",
    )
    parser.add_argument(
        "--int-ms",
        type=int,
        default=DEFAULT_INT_MS,
        help="Integration time in ms (default: %(default)s).",
    )
    parser.add_argument(
        "--n-spectra",
        type=int,
        default=DEFAULT_N_SPECTRA,
        help="Spectra per hot/cold phase (default: %(default)s).",
    )
    parser.add_argument(
        "--n-iterations",
        type=int,
        default=DEFAULT_N_ITERATIONS,
        help="Number of hot/cold cycles (default: %(default)s).",
    )
    parser.add_argument(
        "--settle-time",
        type=float,
        default=DEFAULT_SETTLE_TIME_S,
        help="Chopper settle time in seconds (default: %(default)s).",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default=DEFAULT_OUT_DIR,
        help="Output directory root on spectrometer side (default: %(default)s).",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # Add other modes here later if needed
    if args.full:
        run_full_measurement(
            freq_ghz=args.freq_ghz,
            bw=args.bw,
            int_ms=args.int_ms,
            n_spectra=args.n_spectra,
            n_iterations=args.n_iterations,
            settle_time_s=args.settle_time,
            out_dir=args.out_dir,
        )
    elif not args.no_spectrometer:
        spectrometer_connect()
        spectrometer_init(bw="2GHz", int_ms=500)
        print("Libpcap connection opened. Spectrometer initialized to bw=2 GHz and int_ms=500")
    else:
        print("No action specified (use --full to background measurement plus gas spectroscopy).")

if __name__ == "__main__":
    main()

