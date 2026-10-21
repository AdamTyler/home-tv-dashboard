"""Home server widget: systemd service states, with optional NordVPN detail.

options:
  services: [{"name": "Plex", "unit": "plexmediaserver"},
             {"name": "NordVPN", "unit": "nordvpnd", "check": "nordvpn"}]
"""
import re
import subprocess


def _active(unit):
    r = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True)
    return r.stdout.strip() == "active"


def _nordvpn():
    try:
        text = subprocess.run(["nordvpn", "status"], capture_output=True,
                              text=True, timeout=5).stdout
    except Exception:
        return "warn", "Status unknown"
    state = re.search(r"Status:\s*(\w+)", text)
    if state and state.group(1) == "Connected":
        country = re.search(r"Country:\s*(.+)", text)
        return "ok", "Connected" + (" · " + country.group(1).strip() if country else "")
    return "warn", "Not connected"


def data(options):
    rows = []
    for svc in options.get("services", []):
        if not _active(svc["unit"]):
            state, value = "bad", "Stopped"
        elif svc.get("check") == "nordvpn":
            state, value = _nordvpn()
        else:
            state, value = "ok", "Running"
        rows.append({"name": svc["name"], "state": state, "value": value})
    return {"services": rows}
