#!/usr/bin/env bash
# Copy the dashboard to the Pi and restart its service.
# Settings come from local.env (see local.env.example).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/local.env" ] || { echo "Missing local.env (copy local.env.example)"; exit 1; }
source "$ROOT/local.env"

# Files with your own values live only on the Pi and are never overwritten.
rsync -a --exclude config.local.json --exclude calendars.json --exclude tv-token.txt \
  "$ROOT/pi/" "$PI_HOST:/opt/tv-dashboard/"
ssh "$PI_HOST" 'sudo cp /opt/tv-dashboard/tv-dashboard.service /etc/systemd/system/ \
  && sudo systemctl daemon-reload && sudo systemctl restart tv-dashboard \
  && systemctl is-active tv-dashboard'
