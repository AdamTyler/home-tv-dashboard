"""Plex widget: what's playing now and what was recently added.

The Plex token is read from Plex's own Preferences.xml at runtime and never
stored or sent to the TV.

options:
  url: Plex server URL (default http://127.0.0.1:32400)
  preferences: path to Plex's Preferences.xml
               (default ~/Library/Application Support/Plex Media Server/Preferences.xml)
  recent: how many recently added items to fetch (default 6)
"""
import json
import os
import urllib.request
import xml.etree.ElementTree as ET

DEFAULT_PREFS = "~/Library/Application Support/Plex Media Server/Preferences.xml"


def _get(options, path):
    prefs = os.path.expanduser(options.get("preferences", DEFAULT_PREFS))
    token = ET.parse(prefs).getroot().get("PlexOnlineToken", "")
    req = urllib.request.Request(
        options.get("url", "http://127.0.0.1:32400") + path,
        headers={"Accept": "application/json", "X-Plex-Token": token})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.load(r).get("MediaContainer", {})


def data(options):
    out = {"playing": [], "recent": []}
    try:
        for m in _get(options, "/status/sessions").get("Metadata", []):
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
        recent = _get(options, "/library/recentlyAdded?X-Plex-Container-Start=0"
                               "&X-Plex-Container-Size=%d" % options.get("recent", 6))
        for m in recent.get("Metadata", []):
            title = m.get("title", "")
            if m.get("type") == "season":
                title = "%s – %s" % (m.get("parentTitle", ""), title)
            out["recent"].append(title)
    except Exception as e:
        out["error"] = str(e)
    return out
