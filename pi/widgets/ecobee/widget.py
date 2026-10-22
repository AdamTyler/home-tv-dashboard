"""ecobee widget: thermostat and room-sensor temperatures, read locally over HomeKit.

ecobee stopped issuing developer API keys in 2024, but its thermostats speak
HomeKit on the home network. Pair each thermostat once with
scripts/homekit-pair.py (its HomeKit code is under Settings → HomeKit on the
thermostat); the keys go in a git-ignored file on the Pi. Read-only: nothing
here changes thermostat settings.

options:
  pairings: HomeKit pairing file (default /opt/tv-dashboard/homekit-pairings.json)
  poll_seconds: how often to read the thermostats (default 60)
  units: "F" or "C" (default: the thermostat's own display setting)
"""
import asyncio
import logging
import threading
import time

log = logging.getLogger("tv-dashboard")

# HomeKit characteristic short types (the full ids end in -0000-1000-8000-0026BB765291).
NAME, TEMP, TARGET, HUMIDITY = "23", "11", "35", "10"
OCCUPIED, HVAC_NOW, HVAC_MODE, UNITS = "71", "F", "33", "36"
HEAT_TO, COOL_TO = "12", "D"
MODES = {0: "off", 1: "heat", 2: "cool", 3: "auto"}
ACTIONS = {0: "idle", 1: "heating", 2: "cooling"}

_state = {"data": None, "error": None, "at": 0}
_started = []


def _short(uuid):
    return uuid.split("-")[0].lstrip("0").upper() or "0"


def _values(accessory):
    vals = {}
    for service in accessory["services"]:
        for ch in service["characteristics"]:
            key = _short(ch["type"])
            if "value" in ch and key not in vals:
                vals[key] = ch["value"]
    return vals


def _summarize(alias, accessories):
    """One thermostat (aid 1) plus its room sensors (the other accessories)."""
    thermostat, sensors = None, []
    for acc in accessories:
        v = _values(acc)
        if acc["aid"] == 1:
            thermostat = {
                "name": v.get(NAME, alias), "temp_c": v.get(TEMP), "humidity": v.get(HUMIDITY),
                "mode": MODES.get(v.get(HVAC_MODE), "?"), "action": ACTIONS.get(v.get(HVAC_NOW), "idle"),
                "target_c": v.get(TARGET), "heat_to_c": v.get(HEAT_TO), "cool_to_c": v.get(COOL_TO),
                "fahrenheit": v.get(UNITS) == 1,
            }
        elif TEMP in v:
            sensors.append({"name": v.get(NAME, "Sensor"), "temp_c": v.get(TEMP),
                            "occupied": bool(v.get(OCCUPIED))})
    if thermostat:
        thermostat["sensors"] = sorted(sensors, key=lambda s: s["name"])
    return thermostat


async def _poll_forever(options):
    from aiohomekit import Controller
    from zeroconf.asyncio import AsyncServiceBrowser, AsyncZeroconf

    zc = AsyncZeroconf()
    async with zc:
        # aiohomekit's controller expects browsers for both HomeKit service types.
        browser = AsyncServiceBrowser(zc.zeroconf, ["_hap._tcp.local.", "_hap._udp.local."],
                                      handlers=[lambda **kw: None])
        controller = Controller(async_zeroconf_instance=zc)
        async with controller:
            controller.load_data(options.get("pairings", "/opt/tv-dashboard/homekit-pairings.json"))
            while True:
                try:
                    thermostats = []
                    for alias, pairing in sorted(controller.aliases.items()):
                        accessories = await pairing.list_accessories_and_characteristics()
                        t = _summarize(alias, accessories)
                        if t:
                            thermostats.append(t)
                    _state.update(data=thermostats, error=None, at=time.time())
                except Exception as e:
                    log.warning("ecobee: read failed: %s", e)
                    _state.update(error=str(e))
                await asyncio.sleep(options.get("poll_seconds", 60))
        await browser.async_cancel()


def _start(options):
    if _started:
        return
    def run():
        try:
            asyncio.run(_poll_forever(options))
        except Exception as e:
            log.warning("ecobee: HomeKit connection stopped: %s", e)
            _state.update(error=str(e))
            _started.clear()  # let the next request try again
    t = threading.Thread(target=run, daemon=True)
    _started.append(t)
    t.start()


def _temp(c, fahrenheit):
    if c is None:
        return None
    return round(c * 9 / 5 + 32) if fahrenheit else round(c, 1)


def data(options):
    _start(options)
    if _state["data"] is None:
        return {"loading": True, "error": _state["error"]}
    # Units: the option if set, otherwise the first thermostat's display setting.
    thermostats = _state["data"]
    default = "F" if (not thermostats or thermostats[0]["fahrenheit"]) else "C"
    f = (options.get("units") or default).upper() == "F"
    out = []
    for t in thermostats:
        out.append({
            "name": t["name"], "temp": _temp(t["temp_c"], f),
            "humidity": round(t["humidity"]) if t["humidity"] is not None else None,
            "mode": t["mode"], "action": t["action"],
            "heat_to": _temp(t["heat_to_c"], f), "cool_to": _temp(t["cool_to_c"], f),
            "target": _temp(t["target_c"], f),
            "sensors": [{"name": s["name"], "temp": _temp(s["temp_c"], f), "occupied": s["occupied"]}
                        for s in t["sensors"]],
        })
    return {"thermostats": out, "unit": "°F" if f else "°C",
            "age": round(time.time() - _state["at"]), "error": _state["error"]}
