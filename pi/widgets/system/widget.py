"""System widget: free space on drives plus the Pi's temperature and load.

options:
  drives: [{"name": "Media drive", "path": "/mnt/media"}]
  temperature_unit: "F" or "C" (default "F")
"""
import os
import shutil


def _drive(d):
    try:
        du = shutil.disk_usage(d["path"])
    except OSError:
        return {"name": d["name"], "state": "bad", "value": "Not mounted"}
    free = du.free / du.total
    value = ("%.1f TB free" % (du.free / 2**40) if du.free >= 2**40
             else "%d GB free" % (du.free // 2**30))
    return {"name": d["name"], "state": "bad" if free < 0.1 else "warn" if free < 0.2 else "ok",
            "value": value}


def data(options):
    rows = [_drive(d) for d in options.get("drives", [])]

    with open("/sys/class/thermal/thermal_zone0/temp") as f:
        temp_c = int(f.read()) / 1000
    state = "bad" if temp_c > 80 else "warn" if temp_c > 68 else "ok"
    if options.get("temperature_unit", "F").upper() == "C":
        temp = "%d°C" % round(temp_c)
    else:
        temp = "%d°F" % round(temp_c * 9 / 5 + 32)
    rows.append({"name": "Pi temperature", "state": state, "value": temp})

    load = os.getloadavg()[0]
    rows.append({"name": "Pi load", "state": "warn" if load > 3 else "ok",
                 "value": "%.2f" % load})
    return {"rows": rows}
