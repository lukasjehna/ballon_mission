#!/usr/bin/env bash

# Usage without a sudo kill, but it uses sudo internally anyway:
#   ./run_services.sh enable           # enable autostart
#   ./run_services.sh enable --now     # enable autostart and start now
#   ./run_services.sh start            # start now only
#   ./run_services.sh disable          # disable autostart

set -euo pipefail

ARGS1="${1:-enable}"
ARGS2="${2:-}"

case "$ARGS1" in

  enable)
    ACTION=enable
    EXTRA_FLAG=
    if [[ "$ARGS2" == "--now" ]]; then
      EXTRA_FLAG=--now
    fi
    ;;

  start)
    ACTION=start
    EXTRA_FLAG=
    ;;

  disable)
    ACTION=disable
    EXTRA_FLAG=--now
    ;;

  *)
    echo "Usage: $0 enable [--now] | start | disable" >&2
    exit 1
    ;;

esac

sudo systemctl "$ACTION" $EXTRA_FLAG balloon-udp@chopper.service \
  balloon-udp@pressure.service \
  balloon-udp@temperature.service \
  balloon-udp@gyro.service \
  balloon-udp@receiver.service \
  balloon-udp@telemetry.service

sudo systemctl "$ACTION" $EXTRA_FLAG balloon-udp-spectrometer.service
sudo systemctl "$ACTION" $EXTRA_FLAG balloon-main.service

echo "Following logs (Ctrl-C to stop)..."
exec sudo journalctl -fu balloon-main.service \
-u 'balloon-udp@*.service' \
-u balloon-udp-spectrometer.service
