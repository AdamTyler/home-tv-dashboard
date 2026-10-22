"""Photos widget: a slideshow of random photos from a folder on the Pi, plus a
page for adding photos from Google Photos with Google's Photos Picker.

Since March 2025 Google only lets apps read photos the user picks, so the Pi
downloads picked photos into the folder and the slideshow shows the folder.

options (set your own in config.local.json under "widget_options": {"photos": {...}}):
  folder: photos folder, searched recursively (default: photos/ next to server.py)
  google_folder: where picked Google Photos go (default <folder>/Google Photos)
  credentials: Google sign-in file from scripts/google-photos-auth.py
               (default /opt/tv-dashboard/google-photos.json, never committed)
  max_size: longest side of the copies sent to the TV, in px (default 1280)
  albums: shared Google Photos albums to keep in sync (UNOFFICIAL: reads Google's
          public album page, which Google may change at any time). Keep these in
          config.local.json; anyone with a link can see the album.
          [{"url": "https://photos.app.goo.gl/...", "name": "optional"}]
  album_sync_hours: how often to re-check albums (default 6)

routes (under /api/widget/<index>/):
  photo/<id>          a resized photo (?size=small: 96px, for blurred backgrounds)
  pick                page to open on your phone to choose photos
  pick/start (POST)   create a picker session
  pick/status         progress of the current pick
  albums/status       shared-album sync status
  albums/sync (POST)  sync shared albums now
"""
import hashlib
import html
import io
import json
import logging
import os
import random
import re
import threading
import time
import urllib.parse
import urllib.request

try:
    from PIL import Image, ImageOps
except ImportError:  # still works, just sends originals
    Image = None

log = logging.getLogger("tv-dashboard")
HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.normpath(os.path.join(HERE, "..", ".."))
CACHE = os.path.join(APP_DIR, "cache", "photos")
EXTS = (".jpg", ".jpeg", ".png", ".webp")
PICKER = "https://photospicker.googleapis.com/v1/"


def _folder(options):
    return os.path.expanduser(options.get("folder", os.path.join(APP_DIR, "photos")))


# --- Slideshow ------------------------------------------------------------

_listing = {"at": 0, "folder": None, "by_id": {}}
_listing_lock = threading.Lock()


def _photo_id(relpath):
    return hashlib.sha1(relpath.encode()).hexdigest()[:16]


def _scan(options):
    """Map id -> path for every photo in the folder (re-scanned every 5 min)."""
    folder = _folder(options)
    with _listing_lock:
        if _listing["folder"] == folder and time.time() - _listing["at"] < 300:
            return _listing["by_id"]
        by_id = {}
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for name in files:
                if name.lower().endswith(EXTS) and not name.startswith("."):
                    path = os.path.join(root, name)
                    by_id[_photo_id(os.path.relpath(path, folder))] = path
        _listing.update(at=time.time(), folder=folder, by_id=by_id)
        return by_id


def data(options):
    _start_album_scheduler(options)
    by_id = _scan(options)
    ids = list(by_id)
    random.shuffle(ids)
    return {"photos": ids[:300], "count": len(ids)}


def _resized(options, photo_id, small=False):
    """A copy sized for the TV; small=True is a tiny one for blurred backgrounds."""
    path = _scan(options).get(photo_id)
    if not path:
        return None
    if Image is None:
        with open(path, "rb") as f:
            return f.read()
    os.makedirs(CACHE, exist_ok=True)
    cached = os.path.join(CACHE, photo_id + ("-s" if small else "") + ".jpg")
    if not os.path.exists(cached) or os.path.getmtime(cached) < os.path.getmtime(path):
        size = 96 if small else options.get("max_size", 1280)
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((size, size))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=70 if small else 85)
        tmp = cached + ".tmp"
        with open(tmp, "wb") as f:
            f.write(out.getvalue())
        os.replace(tmp, cached)
    with open(cached, "rb") as f:
        return f.read()


# --- Google Photos Picker -------------------------------------------------

_token = {"value": None, "expires": 0}
_pick = {"state": "idle", "pickerUri": None, "done": 0, "total": 0, "error": None}
_pick_lock = threading.Lock()


def _access_token(options):
    if _token["value"] and time.time() < _token["expires"] - 60:
        return _token["value"]
    path = options.get("credentials", "/opt/tv-dashboard/google-photos.json")
    with open(path) as f:
        creds = json.load(f)
    body = urllib.parse.urlencode({
        "client_id": creds["client_id"], "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen("https://oauth2.googleapis.com/token", body, timeout=15) as r:
        tok = json.load(r)
    _token.update(value=tok["access_token"], expires=time.time() + tok.get("expires_in", 3600))
    return _token["value"]


def _api(options, method, path, payload=None):
    req = urllib.request.Request(
        PICKER + path, method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": "Bearer " + _access_token(options),
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else {}


def _seconds(duration, default):
    """Google durations look like "5s" or "1.5s"."""
    try:
        return float(str(duration).rstrip("s"))
    except ValueError:
        return default


def _sync(options, session):
    """Wait for the user to finish picking, then download the picked photos."""
    sid = session["id"]
    poll = session.get("pollingConfig", {})
    interval = max(_seconds(poll.get("pollInterval"), 5), 2)
    deadline = time.time() + _seconds(poll.get("timeoutIn"), 1800)
    try:
        while time.time() < deadline:
            if _api(options, "GET", "sessions/" + sid).get("mediaItemsSet"):
                break
            time.sleep(interval)
        else:
            _pick.update(state="expired")
            return

        items, page = [], None
        while True:
            q = {"sessionId": sid, "pageSize": 100}
            if page:
                q["pageToken"] = page
            res = _api(options, "GET", "mediaItems?" + urllib.parse.urlencode(q))
            items += [i for i in res.get("mediaItems", []) if i.get("type") == "PHOTO"]
            page = res.get("nextPageToken")
            if not page:
                break

        dest = options.get("google_folder", os.path.join(_folder(options), "Google Photos"))
        os.makedirs(dest, exist_ok=True)
        _pick.update(state="downloading", total=len(items), done=0)
        for item in items:
            name = re.sub(r"[^A-Za-z0-9_-]", "", item["id"])[:40] + ".jpg"
            target = os.path.join(dest, name)
            if not os.path.exists(target):
                # "=w2048-h2048" asks Google for a JPEG at most 2048px on a side.
                req = urllib.request.Request(
                    item["mediaFile"]["baseUrl"] + "=w2048-h2048",
                    headers={"Authorization": "Bearer " + _access_token(options)})
                with urllib.request.urlopen(req, timeout=60) as r:
                    content = r.read()
                with open(target + ".tmp", "wb") as f:
                    f.write(content)
                os.replace(target + ".tmp", target)
            _pick["done"] += 1
        _listing["at"] = 0  # rescan the folder
        _pick.update(state="done")
        log.info("photos: added %d picked photos", len(items))
    except Exception as e:
        log.warning("photos: pick failed: %s", e)
        _pick.update(state="error", error=str(e))
    finally:
        try:
            _api(options, "DELETE", "sessions/" + sid)
        except Exception:
            pass


def _start_pick(options):
    with _pick_lock:
        if _pick["state"] in ("waiting", "downloading"):
            return dict(_pick)
        session = _api(options, "POST", "sessions", {})
        _pick.update(state="waiting", pickerUri=session["pickerUri"], done=0, total=0, error=None)
        threading.Thread(target=_sync, args=(options, session), daemon=True).start()
        return dict(_pick)


# --- Shared albums (unofficial) -------------------------------------------
# A shared album's public page embeds its photos' URLs. This is not a Google
# API and only covers the photos in the page's first batch (often a few
# hundred), but it keeps whole albums in sync without picking.

ALBUM_PHOTO = re.compile(r'\["(https://lh3\.googleusercontent\.com/pw/[A-Za-z0-9_-]+)",\d+,\d+')
ALBUM_TITLE = re.compile(r'<meta property="og:title" content="([^"]*)"')
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_albums = {"state": "idle", "last": None, "error": None, "albums": []}
_albums_lock = threading.Lock()
_albums_scheduler = []


def _album_page(url):
    if "goo.gl/" in url:
        # Short links serve a JavaScript page to browsers but a plain redirect
        # (to photos.google.com/share/...?key=...) to other clients.
        req = urllib.request.Request(url, headers={"User-Agent": "tv-dashboard"})
        with urllib.request.urlopen(req, timeout=30) as r:
            url = r.geturl()
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    urls = []
    for m in ALBUM_PHOTO.finditer(page):
        if m.group(1) not in urls:
            urls.append(m.group(1))
    title = ALBUM_TITLE.search(page)
    # Titles look like "Name · Nov 14, 2022 – Dec 1, 2024 📸"; keep the name.
    name = html.unescape(title.group(1)).split(" - Google Photos")[0].split(" · ")[0] if title else ""
    return name.strip(), urls


def _sync_albums(options):
    if not _albums_lock.acquire(blocking=False):
        return  # already syncing
    try:
        _albums.update(state="syncing", error=None)
        results = []
        for album in options.get("albums", []):
            info = {"name": album.get("name", ""), "photos": 0, "added": 0, "error": None}
            try:
                title, urls = _album_page(album["url"])
                info["name"] = info["name"] or title or "Album"
                safe = re.sub(r"[^\w .&'-]", "", info["name"]).strip() or "Album"
                dest = os.path.join(_folder(options), "Albums", safe)
                os.makedirs(dest, exist_ok=True)
                info["photos"] = len(urls)
                for url in urls:
                    target = os.path.join(dest, hashlib.sha1(url.encode()).hexdigest()[:16] + ".jpg")
                    if os.path.exists(target):
                        continue
                    req = urllib.request.Request(url + "=w2048-h2048",
                                                 headers={"User-Agent": BROWSER_UA})
                    with urllib.request.urlopen(req, timeout=60) as r:
                        content = r.read()
                    with open(target + ".tmp", "wb") as f:
                        f.write(content)
                    os.replace(target + ".tmp", target)
                    info["added"] += 1
            except Exception as e:
                log.warning("photos: album sync failed for %s: %s", info["name"] or "album", e)
                info["error"] = str(e)
            results.append(info)
        _listing["at"] = 0  # rescan the folder
        _albums.update(state="idle", last=time.time(), albums=results)
        added = sum(a["added"] for a in results)
        if added:
            log.info("photos: added %d photos from shared albums", added)
    finally:
        _albums_lock.release()


def _start_album_scheduler(options):
    """Re-sync shared albums every album_sync_hours, in the background."""
    if _albums_scheduler or not options.get("albums"):
        return
    def loop():
        while True:
            _sync_albums(options)
            time.sleep(options.get("album_sync_hours", 6) * 3600)
    t = threading.Thread(target=loop, daemon=True)
    _albums_scheduler.append(t)
    t.start()


# --- Routes ---------------------------------------------------------------

def route(options, method, subpath, query, body):
    if subpath.startswith("photo/") and method == "GET":
        content = _resized(options, subpath[len("photo/"):], small=query.get("size") == "small")
        return ("image/jpeg", content) if content is not None else None
    if subpath == "pick" and method == "GET":
        with open(os.path.join(HERE, "pick.html"), "rb") as f:
            return ("text/html; charset=utf-8", f.read())
    if subpath == "pick/start" and method == "POST":
        try:
            return _start_pick(options)
        except FileNotFoundError:
            return {"state": "error", "error": "Google sign-in not set up on the Pi "
                                               "(run scripts/google-photos-auth.py)"}
        except Exception as e:
            return {"state": "error", "error": str(e)}
    if subpath == "pick/status" and method == "GET":
        return dict(_pick, photos=len(_scan(options)))
    if subpath == "albums/status" and method == "GET":
        _start_album_scheduler(options)
        return dict(_albums, configured=len(options.get("albums", [])))
    if subpath == "albums/sync" and method == "POST":
        threading.Thread(target=_sync_albums, args=(options,), daemon=True).start()
        return {"state": "syncing"}
    return None
