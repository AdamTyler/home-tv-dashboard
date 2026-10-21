#!/usr/bin/env python3
"""TV dashboard for a Samsung Tizen TV, served from a Raspberry Pi.

- Serves index.html and a small JSON API (weather, calendar, home status,
  app launching).
- Watches the TV's power state and opens the dashboard app whenever the TV
  turns on.
"""
import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events
from samsungtvws import SamsungTVWS

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
# Your own values (TV/Pi addresses, location, timezone, ...) go here.
# It's git-ignored and its top-level keys replace those in config.json.
LOCAL_CONFIG_PATH = os.path.join(HERE, "config.local.json")
PLEX_PREFS = os.path.expanduser(
    "~/Library/Application Support/Plex Media Server/Preferences.xml")

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("tv-dashboard")


def load_config():
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    try:
        with open(LOCAL_CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        log.warning("no config.local.json; using defaults from config.json")
    return cfg


CFG = load_config()
MEDIA_MOUNT = CFG.get("media_mount", "/mnt/library")
SERVICES = [(s["name"], s["unit"]) for s in CFG.get("services", [])]


# --- TV control ---------------------------------------------------------

_tv_lock = threading.Lock()


def tv_call(fn):
    """Run fn(tv) on a fresh connection; the TV only allows one at a time."""
    with _tv_lock:
        tv = SamsungTVWS(host=CFG["tv_ip"], port=8002, name="PiDashboard",
                         token_file=os.path.join(HERE, "tv-token.txt"),
                         timeout=15)
        try:
            return fn(tv)
        finally:
            try:
                tv.close()
            except Exception:
                pass


def tv_power():
    """'on', 'standby', or 'off' (unreachable)."""
    url = "http://%s:8001/api/v2/" % CFG["tv_ip"]
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            device = json.load(r).get("device", {})
        return device.get("PowerState", "on")
    except Exception:
        return "off"


def open_dashboard():
    """Open the installed TV app, or fall back to the TV's browser."""
    app_id = CFG.get("dashboard_app_id")
    if app_id:
        tv_call(lambda tv: tv.run_app(app_id))
    else:
        tv_call(lambda tv: tv.open_browser(CFG["dashboard_url"]))


def watcher():
    last = tv_power()
    log.info("watcher started; TV is %s", last)
    while True:
        time.sleep(3)
        now = tv_power()
        if now != last:
            log.info("TV power: %s -> %s", last, now)
        if now == "on" and last != "on":
            time.sleep(CFG.get("launch_delay_seconds", 8))
            try:
                open_dashboard()
                log.info("opened dashboard on TV")
            except Exception as e:
                log.warning("could not open dashboard: %s", e)
        last = now


# --- Weather (Open-Meteo, no API key) -----------------------------------

_weather_cache = {"at": 0, "data": None}


def weather():
    loc = CFG.get("location")
    if not loc:
        return {"error": "no-location"}
    if _weather_cache["data"] and time.time() - _weather_cache["at"] < 600:
        return _weather_cache["data"]
    q = urllib.parse.urlencode({
        "latitude": loc["lat"], "longitude": loc["lon"],
        "current": "temperature_2m,apparent_temperature,weather_code,"
                   "wind_speed_10m,relative_humidity_2m,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                 "precipitation_probability_max",
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "timezone": "auto", "forecast_days": 5,
    })
    with urllib.request.urlopen(
            "https://api.open-meteo.com/v1/forecast?" + q, timeout=10) as r:
        data = json.load(r)
    data["place"] = loc["name"]
    _weather_cache.update(at=time.time(), data=data)
    return data


# --- Calendar (iCal feeds; private links live in calendars.json) -------

CALENDARS_PATH = os.path.join(HERE, "calendars.json")
TZ = ZoneInfo(CFG.get("timezone", "UTC"))
_calendar_cache = {"at": 0, "data": None}


def time_range(start, end):
    """'10:30 – 11am', '9am – 12:30pm', '3pm'."""
    def fmt(dt, suffix=True):
        s = str(dt.hour % 12 or 12) + (":%02d" % dt.minute if dt.minute else "")
        return s + (("am" if dt.hour < 12 else "pm") if suffix else "")
    if end <= start:
        return fmt(start)
    same_half = (start.hour < 12) == (end.hour < 12)
    return "%s – %s" % (fmt(start, suffix=not same_half), fmt(end))


def calendar_events():
    if _calendar_cache["data"] and time.time() - _calendar_cache["at"] < 600:
        return _calendar_cache["data"]
    try:
        with open(CALENDARS_PATH) as f:
            calendars = json.load(f)
    except FileNotFoundError:
        return {"events": [], "errors": ["no calendars.json"]}

    now = datetime.now(TZ)
    today = now.date()
    start = datetime.combine(today, datetime.min.time(), TZ)
    end = start + timedelta(days=CFG.get("calendar_days", 45))
    events, errors = [], []
    for cal in calendars:
        try:
            req = urllib.request.Request(cal["url"], headers={"User-Agent": "tv-dashboard"})
            with urllib.request.urlopen(req, timeout=15) as r:
                ics = icalendar.Calendar.from_ical(r.read())
            for ev in recurring_ical_events.of(ics).between(start, end):
                s = ev.get("DTSTART").dt
                e = ev.get("DTEND").dt if ev.get("DTEND") else None
                item = {"title": str(ev.get("SUMMARY", "")), "color": cal.get("color", "#1a73e8")}
                if not isinstance(s, datetime):  # all-day
                    e = e or s + timedelta(days=1)
                    if e <= today:
                        continue
                    item.update(allDay=True, date=max(s, today).isoformat())
                else:
                    s = s.astimezone(TZ) if s.tzinfo else s.replace(tzinfo=TZ)
                    e = (e.astimezone(TZ) if e.tzinfo else e.replace(tzinfo=TZ)) if e else s
                    if e <= now:
                        continue
                    item.update(allDay=False, date=s.date().isoformat(),
                                start=s.isoformat(), when=time_range(s, e),
                                now=s <= now < e)
                events.append(item)
        except Exception as ex:
            log.warning("calendar %s failed: %s", cal.get("name", "?"), ex)
            errors.append(cal.get("name", "calendar"))
    events.sort(key=lambda x: (x["date"], not x["allDay"], x.get("start", "")))
    data = {"events": events[:CFG.get("calendar_max", 30)], "errors": errors,
            "today": today.isoformat()}
    _calendar_cache.update(at=time.time(), data=data)
    return data


# --- Home status --------------------------------------------------------

def plex_get(path):
    token = ET.parse(PLEX_PREFS).getroot().get("PlexOnlineToken", "")
    req = urllib.request.Request(
        "http://127.0.0.1:32400" + path,
        headers={"Accept": "application/json", "X-Plex-Token": token})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r).get("MediaContainer", {})


def plex_summary():
    out = {"playing": [], "recent": []}
    try:
        for m in plex_get("/status/sessions").get("Metadata", []):
            title = m.get("title", "")
            if m.get("grandparentTitle"):
                title = "%s – %s" % (m["grandparentTitle"], title)
            dur = m.get("duration") or 0
            out["playing"].append({
                "title": title,
                "user": (m.get("User") or {}).get("title", ""),
                "device": (m.get("Player") or {}).get("title", ""),
                "progress": round(100 * m.get("viewOffset", 0) / dur) if dur else 0,
            })
        recent = plex_get("/library/recentlyAdded?X-Plex-Container-Start=0"
                          "&X-Plex-Container-Size=6")
        for m in recent.get("Metadata", []):
            title = m.get("title", "")
            if m.get("type") == "season":
                title = "%s – %s" % (m.get("parentTitle", ""), title)
            out["recent"].append(title)
    except Exception as e:
        out["error"] = str(e)
    return out


def vpn_summary():
    try:
        text = subprocess.run(["nordvpn", "status"], capture_output=True,
                              text=True, timeout=5).stdout
    except Exception:
        return {"state": "unknown"}
    state = re.search(r"Status:\s*(\w+)", text)
    country = re.search(r"Country:\s*(.+)", text)
    return {"state": state.group(1) if state else "unknown",
            "country": country.group(1).strip() if country else ""}


def status():
    services = []
    for label, unit in SERVICES:
        r = subprocess.run(["systemctl", "is-active", unit],
                           capture_output=True, text=True)
        services.append({"name": label, "ok": r.stdout.strip() == "active"})
    try:
        du = shutil.disk_usage(MEDIA_MOUNT)
        drive = {"free_gb": du.free // 2**30, "total_gb": du.total // 2**30}
    except OSError:
        drive = None
    with open("/sys/class/thermal/thermal_zone0/temp") as f:
        temp_c = int(f.read()) / 1000
    return {
        "services": services,
        "vpn": vpn_summary(),
        "drive": drive,
        "pi": {"temp_f": round(temp_c * 9 / 5 + 32),
               "load": round(os.getloadavg()[0], 2)},
        "plex": plex_summary(),
    }


# --- HTTP ---------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(HERE, "static"), **kw)

    def log_message(self, fmt, *args):
        pass

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/api/weather":
                return self.send_json(weather())
            if self.path == "/api/status":
                return self.send_json(status())
            if self.path == "/api/calendar":
                return self.send_json(calendar_events())
            if self.path == "/api/apps":
                return self.send_json(CFG["apps"])
        except Exception as e:
            log.warning("%s failed: %s", self.path, e)
            return self.send_json({"error": str(e)}, 500)
        return super().do_GET()

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        try:
            if self.path == "/api/launch":
                app = next(a for a in CFG["apps"]
                           if a.get("id") and a["id"] == body.get("id"))
                tv_call(lambda tv: tv.run_app(app["id"]))
                log.info("launched %s", app["name"])
                return self.send_json({"ok": True})
            if self.path == "/api/log":
                log.info("client: %s", json.dumps(body))
                return self.send_json({"ok": True})
            if self.path == "/api/open-dashboard":
                open_dashboard()
                return self.send_json({"ok": True})
        except StopIteration:
            return self.send_json({"error": "unknown app"}, 404)
        except Exception as e:
            log.warning("%s failed: %s", self.path, e)
            return self.send_json({"error": str(e)}, 500)
        self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    threading.Thread(target=watcher, daemon=True).start()
    port = CFG.get("port", 8080)
    log.info("serving on :%d", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
