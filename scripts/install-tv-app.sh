#!/usr/bin/env bash
# Sign, package and install the Home Dashboard app on the TV, then open it.
# Needs Tizen Studio (~/tizen-studio), a Samsung certificate profile, and the
# TV in Developer Mode with this computer's IP as the host.
# Settings come from local.env (see local.env.example).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/local.env" ] || { echo "Missing local.env (copy local.env.example)"; exit 1; }
source "$ROOT/local.env"
TIZEN=~/tizen-studio/tools/ide/bin/tizen
SDB=~/tizen-studio/tools/sdb

# Build in a temp dir so signatures, the .wgt and your dashboard URL never land in the repo.
BUILD="$(mktemp -d)"
cp "$ROOT/tizen-app/"* "$BUILD/"
sed -i '' "s|__DASHBOARD_URL__|$DASHBOARD_URL|g" "$BUILD/index.html"
"$TIZEN" package -t wgt -s "$CERT_PROFILE" -- "$BUILD"
# The package is named after the app ("Home Dashboard.wgt"); tizen install fails on spaces.
mv "$BUILD"/*.wgt "$BUILD/HomeDashboard.wgt"

"$SDB" connect "$TV_IP"
"$TIZEN" install -n "$BUILD/HomeDashboard.wgt" -s "$TV_IP:26101"
"$SDB" -s "$TV_IP:26101" shell 0 kill HmDash0001 >/dev/null 2>&1 || true
"$SDB" -s "$TV_IP:26101" shell 0 execute HmDash0001.HomeDash
