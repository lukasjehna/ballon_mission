# TODO: Project structure improvements (balloon_mission)

## Goals
- Make the Python code importable and testable as a package (no `sys.path.append(...)` hacks).
- Keep systemd as the runtime orchestration layer, but make it easy to run locally/dev and to validate service health.
- Consolidate UDP protocol/client logic so the main control script and servers share consistent behavior.
- Centralize configuration (ports/hosts/paths) so systemd units and Python stay in sync.

---

## 1) Repo layout (filesystem)
- [ ] Create standard top-level folders:
  - [ ] `src/balloon_mission/` for Python package code
  - [ ] `scripts/` for developer/operator helper scripts (shell)
  - [ ] `systemd/` for `.service` / `.timer` / unit templates and install notes
  - [ ] `config/` for runtime config templates (e.g., TOML/YAML/JSON)
  - [ ] `tests/` for unit/integration tests
  - [ ] `docs/` for operator docs (optional but recommended)

- [ ] Move current helper scripts into `scripts/`
  - [ ] `run_services.sh` -> `scripts/run_services.sh`
  - [ ] `check_services.sh` -> `scripts/check_services.sh`
  - [ ] `run_python_measurement.sh` -> `scripts/run_python_measurement.sh` (if present)

- [ ] Put systemd unit files (or templates) under `systemd/`
  - [ ] `balloon-main.service`
  - [ ] `balloon-udp@.service`
  - [ ] `balloon-udp-spectrometer.service`
  - [ ] Add `systemd/README.md` with install instructions and paths.

---

## 2) Package-ify Python (remove `sys.path.append`)
- [ ] Add `pyproject.toml` (setuptools or hatch/poetry) using a `src/` layout.
- [ ] Create package skeleton:
  - [ ] `src/balloon_mission/__init__.py`
  - [ ] `src/balloon_mission/main_control.py` (logic currently in `run_measurement.py`)
  - [ ] `src/balloon_mission/udp/` (shared UDP client + protocol)
  - [ ] `src/balloon_mission/devices/` (device-level wrappers)

- [ ] Convert `run_measurement.py` into a thin entry script:
  - [ ] Keep CLI parsing there (or move into package as `balloon_mission.cli`)
  - [ ] Import `balloon_mission.main_control:main`
  - [ ] Remove `sys.path.append(os.path.join(..., 'src'))`

---

## 3) Unify UDP client + protocol
- [ ] Create a shared UDP client module (used by main control and tests)
  - [ ] Standard timeout/retry strategy
  - [ ] Consistent receive framing (newline-terminated vs fixed-length)
  - [ ] Consistent error handling (timeouts, partial reads)

- [ ] Define protocol helpers/types (even if “simple strings + JSON”)
  - [ ] Normalize response format for all servers: `{status: ok|err, ...}`
  - [ ] Add strict JSON decode + clear error messages
  - [ ] Decide whether commands are newline-terminated everywhere

- [ ] Replace `cmd()` in `run_measurement.py` with the shared client

---

## 4) Central configuration (ports/host/paths)
- [ ] Create a single configuration source:
  - [ ] `config/default.toml` (or `yaml/json`)
  - [ ] Include: host, ports per service, output roots, default timeouts

- [ ] Make main control read config (CLI flags override config)
- [ ] Make systemd units read the same values (via EnvironmentFile or templating)
  - [ ] Add `config/balloon.env.example` for systemd `EnvironmentFile=...`

---

## 5) Entry points and operator UX
- [ ] Provide a single “operator” entrypoint:
  - [ ] `scripts/run_services.sh` (enable/start/disable)
  - [ ] Optional: `scripts/health_check.sh` or a Python `balloon-health` command

- [ ] Add `README.md` sections:
  - [ ] Quick start (systemd install + starting services)
  - [ ] Running a measurement
  - [ ] Viewing logs (`journalctl -fu ...`)
  - [ ] Where data is written and how it is named

---

## 6) Logging + observability
- [ ] Standardize logging across:
  - [ ] UDP servers
  - [ ] main control
  - [ ] analysis scripts (optional)

- [ ] Ensure logs go to stdout/stderr (journald-friendly)
- [ ] Add a simple “device server health” command:
  - [ ] Each server implements `PING` / `STATUS` returning JSON
  - [ ] Main control can assert everything is up before starting

---

## 7) Testing strategy
- [ ] Unit tests:
  - [ ] Protocol parsing (JSON decode, framing)
  - [ ] UDP client behavior (mock sockets)
  - [ ] Main control sequencing logic (mock client)

- [ ] Integration tests (optional):
  - [ ] Spawn a dummy UDP server in tests and verify end-to-end send/recv
  - [ ] Smoke test: service ports reachable on localhost

---

## 8) Gradual migration plan (minimize downtime)
- [ ] Step 1: introduce package + shared UDP client while keeping current scripts working
- [ ] Step 2: move scripts to `scripts/`, keep root-level stubs that forward (optional)
- [ ] Step 3: migrate systemd units into `systemd/` + document install
- [ ] Step 4: enforce config centralization and remove duplicate port constants
- [ ] Step 5: add tests + CI (optional)

---

## Notes / current hotspots
- `run_measurement.py` currently:
  - embeds ports/constants
  - implements `cmd()` socket logic inline
  - modifies `sys.path` to import from `src/`
- `run_services.sh`:
  - works well as an operator helper, but belongs under `scripts/`
  - should be documented alongside systemd unit files