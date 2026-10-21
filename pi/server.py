#!/usr/bin/env python3
"""TV dashboard for a Samsung Tizen TV, served from a Raspberry Pi.

- Serves index.html and a small JSON API (weather, calendar, home status,
  app launching).
- Watches the TV's power state and opens the dashboard app whenever the TV
  turns on.
"""
import importlib.util
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request
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


# --- Widgets ------------------------------------------------------------
# Each widget is a folder in pi/widgets/<type>/ with:
#   widget.py   data(options) -> dict   (runs here, on the Pi)
#   widget.js   Dashboard.register("<type>", {render: ...})   (runs on the TV)
#   widget.css  optional styles
# config.json "widgets" lists which ones the dashboard shows, in order.

WIDGETS_DIR = os.path.join(HERE, "widgets")
WIDGET_TYPE = re.compile(r"^[a-z0-9-]+$")
_widget_modules = {}


def widget_module(kind):
    """Load (once) the widget.py for a widget type."""
    if kind not in _widget_modules:
        path = os.path.join(WIDGETS_DIR, kind, "widget.py")
        if not WIDGET_TYPE.match(kind) or not os.path.isfile(path):
            raise KeyError("unknown widget type: %s" % kind)
        spec = importlib.util.spec_from_file_location("widget_" + kind.replace("-", "_"), path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _widget_modules[kind] = mod
    return _widget_modules[kind]


def widget_list():
    """What the dashboard needs to lay out and mount each configured widget.

    Only "display" settings go to the TV; "options" stay on the Pi (they may
    hold things like API keys) and are only passed to widget.py.
    """
    out = []
    for w in CFG.get("widgets", []):
        out.append({"type": w["type"], "title": w.get("title", w["type"]),
                    "width": w.get("width", 1), "refresh": w.get("refresh", 15),
                    "display": w.get("display", {})})
    return out


def widget_data(index):
    w = CFG.get("widgets", [])[index]
    return widget_module(w["type"]).data(w.get("options", {}))


# --- HTTP ---------------------------------------------------------------

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(HERE, "static"), **kw)

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        # The TV's browser caches aggressively; make it revalidate every file
        # so deploys show up without reinstalling the app.
        if not self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_widget_file(self, kind, name):
        path = os.path.join(WIDGETS_DIR, kind, name)
        if not os.path.isfile(path):
            # widget.css is optional
            body, code = b"", (200 if name.endswith(".css") else 404)
        else:
            with open(path, "rb") as f:
                body, code = f.read(), 200
        self.send_response(code)
        self.send_header("Content-Type", "text/css" if name.endswith(".css")
                         else "application/javascript")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            if self.path == "/api/weather":
                return self.send_json(weather())
            if self.path == "/api/widgets":
                return self.send_json(widget_list())
            m = re.match(r"^/api/widget/(\d+)$", self.path)
            if m:
                return self.send_json(widget_data(int(m.group(1))))
            m = re.match(r"^/widgets/([a-z0-9-]+)/(widget\.(?:js|css))$", self.path)
            if m:
                return self.send_widget_file(m.group(1), m.group(2))
            if self.path == "/api/calendar":
                return self.send_json(calendar_events())
            if self.path == "/api/apps":
                return self.send_json(CFG["apps"])
        except (KeyError, IndexError) as e:
            return self.send_json({"error": "not found: %s" % e}, 404)
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
        except (StopIteration, KeyError, IndexError):
            return self.send_json({"error": "not found"}, 404)
        except Exception as e:
            log.warning("%s failed: %s", self.path, e)
            return self.send_json({"error": str(e)}, 500)
        self.send_json({"error": "not found"}, 404)


if __name__ == "__main__":
    threading.Thread(target=watcher, daemon=True).start()
    port = CFG.get("port", 8080)
    log.info("serving on :%d", port)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
