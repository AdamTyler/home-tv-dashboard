# CLAUDE.md

Context for working on this project. See README.md for the setup guide.
Household-specific details (addresses, devices, Pi state) are in **CLAUDE.local.md**, which is
git-ignored. Never put personal values or secrets in tracked files (see "Local config and secrets").

## What this is

A home-screen dashboard for a 2019 Samsung Q70R TV (Tizen 5.0, armv7) that opens automatically
when the TV turns on. A Raspberry Pi serves the dashboard and watches the TV's power state; a
small sideloaded Tizen app on the TV displays it.

## Repo layout

- `pi/` deployed to `/opt/tv-dashboard/` on the Pi
  - `server.py`: stdlib `ThreadingHTTPServer` plus a watcher thread
  - `config.json`: public defaults (tiles, services, placeholders)
  - `config.local.example.json`: template for the Pi-only `config.local.json`, whose
    top-level keys replace those in `config.json` (TV IP, dashboard URL, timezone, location)
  - `calendars.example.json`: template for the Pi-only `calendars.json` (private iCal links)
  - `static/index.html`: the dashboard page (also works in a normal browser)
  - `widgets/<type>/`: bottom-row widgets (`widget.py` data on the Pi, `widget.js` render on
    the TV, optional `widget.css`), listed in config `"widgets"`. See `pi/widgets/README.md`.
    Current: `home-server`, `photos`, `logo-3d` (Three.js r128 vendored as `three-r128.js`; newer
    Three.js needs syntax the TV can't run), parked in `_unused_widgets`: `plex`, `system`, `logo`.
    Widgets may define `route()` for URLs under `/api/widget/<i>/`; `render()` gets `ctx.base`.
    Private per-widget options: `config.local.json` `"widget_options": {"<type>": {...}}`.
  - `photos`: slideshow of a folder (Pillow-resized copies cached in `cache/photos/`), filled via
    the Google Photos **Picker API** (full-library read access ended March 2025). OAuth uses a
    Desktop client and loopback sign-in on the Mac (`scripts/google-photos-auth.py`); the device
    flow doesn't allow the picker scope. Credentials: `google-photos.json` on the Pi (git-ignored).
    Shared-album sync (unofficial): parses `lh3.googleusercontent.com/pw/...` URLs from the public
    album page. `photos.app.goo.gl` short links must be resolved **without** a browser User-Agent
    (browsers get a JS page; other clients get a 302 to `share/...?key=`), then the album page is
    fetched **with** one. Links without `?key=` return 404.
  - `static/demo.json`: sample data for `?demo=1` (weather, calendar, widgets), used for
    `docs/screenshot.png` (headless Chrome at 1920x1080). Never screenshot real data for the repo.
  - `tv-dashboard.service`: systemd unit (User=pi, venv python)
- `tizen-app/`: the TV app (`HmDash0001.HomeDash`), an iframe wrapper around the Pi page.
  Its `index.html` has a `__DASHBOARD_URL__` placeholder filled in at build time.
- `scripts/deploy-pi.sh`: rsync `pi/` → Pi (never overwrites the local-only files), restart service
- `scripts/install-tv-app.sh`: fill in the URL, package in a temp dir, install via sdb, relaunch
- `local.env.example`: template for the Mac-side `local.env` used by both scripts

## How it works

- **Power-on launch:** `watcher()` polls `http://TV:8001/api/v2/` every 3 s (`PowerState`,
  or unreachable = off). On a transition to `on` it waits `launch_delay_seconds`, then
  `run_app(dashboard_app_id)`. Without `dashboard_app_id` it falls back to the TV browser
  (`org.tizen.browser` NATIVE_LAUNCH with the URL).
- **TV control** uses `samsungtvws` (in `/opt/tv-dashboard/venv`) as client name `PiDashboard`,
  token in `/opt/tv-dashboard/tv-token.txt`. One connection at a time (`_tv_lock`).
- **Tiles:** normal tiles POST `/api/launch {id}` → Pi → `ed.apps.launch` DEEP_LINK. Tiles with
  `"local"` are opened by the TV app itself via `tizen.application.launch`
  (postMessage `{launch: appId}` from the page to the wrapper).
- **Live preview tile** (`"preview": true`): the page sends the tile's 16:9 video rect to the
  wrapper (`{preview: {x,y,w,h}}`, re-sent every 1 s if the layout moves), and the wrapper calls
  `tizen.tvwindow.show(..., "MAIN")` and mutes via `tizen.tvaudiocontrol`. It hides and unmutes on
  `visibilitychange`, on exit, and before launching another app.
- **Back key** (10009): the page posts `"exit"` to the wrapper, which exits the app.
- **APIs:** `/api/weather` (Open-Meteo, cached 10 min), `/api/calendar` (iCal feeds via
  `icalendar` + `recurring-ical-events`, 45 days, cached 10 min), `/api/apps`, `/api/log` (debug),
  `/api/widgets` (widget list without `options`), `/api/widget/<index>` (that widget's `data()`),
  `/widgets/<type>/widget.js|css` (served from `pi/widgets/`).
- **Widgets:** the page fetches `/api/widgets`, loads each type's JS/CSS once, then mounts one card
  per entry and polls `/api/widget/<i>` every `refresh` seconds. Widget `options` stay on the Pi
  (safe for API keys); only `display` reaches the TV. The Plex widget reads its token from Plex's
  Preferences.xml at runtime.
- **Layout:** `sizeTiles()` computes column width so a 2-wide tile is exactly 16:9 and fits the
  space; labels scale via `--tile-font`. Arrow keys use position-based nearest-tile navigation.

## Hard-won findings about this TV (don't re-learn these)

- Tizen 5.0 browser engine is old: **no optional chaining, `??`, flex `gap`, `aspect-ratio`**.
  Check page JS with `node --check` before deploying.
- **Live video (`tvwindow`) is drawn above all web content**, including the wrapper's top layer.
  Overlays, labels and rounded-corner masks over the video are impossible. The preview is a dark card
  with the label bar below the video.
- Samsung TV Plus (`com.samsung.tv.tvPlusDeeplinker`, `com.samsung.tv.tvplus`) and `KEY_TV` do
  nothing when sent over the remote API. `org.tizen.tv-viewer` works **only when launched on the
  TV** (sdb `0 execute` or `tizen.application.launch`); remotely it shows "server under maintenance".
- Full system app list: `sdb -s <tv-ip>:26101 shell 0 applist`. The remote API's
  `ed.installedApp.get` only lists user apps.
- The remote REST app endpoints (`/api/v2/applications/<id>`) return 404 / no-op on this model.
- Port 8001 ws refuses connections; use 8002 wss with the token.
- Restart the TV app to pick up page changes: `sdb ... shell 0 kill HmDash0001` then
  `shell 0 execute HmDash0001.HomeDash`. `execute` alone just foregrounds the running app.
- Deleting the TV's Internet app breaks browser launches ("Not available"). Smart Hub reset restores
  it but signs you out of apps and wipes the app list; tiles fail until their apps are reinstalled.
- App privileges: internet, tv.inputdevice, application.launch, tv.window, tv.audio.

## Power-on sequence (took many iterations; don't simplify without testing several power-ons)

- TV settings must be **Autorun Smart Hub = Off, Autorun Samsung TV Plus = Off, Autorun Last
  App = Off** (Settings → General → Smart Features). Otherwise the Home hub / TV Plus race the
  dashboard, cover it without the app being told, and reset mute.
- On wake the TV resumes live TV with sound and spends ~10 s restoring its channel. App launches
  in that window are ignored or pushed aside, so the Pi waits `launch_delay_seconds` (10).
- Mute: the remote's KEY_MUTE only toggles. The Pi uses the TV's **UPnP RenderingControl**
  (`http://<tv>:9197/dmr` → `/upnp/control/RenderingControl1`, GetMute/SetMute) to set mute
  exactly and re-checks every 0.5 s (`hold_mute`) until the dashboard has settled, because the
  channel restore and the switch to the app both unmute. If the dashboard never opens, it unmutes.
- The Pi verifies launches: the TV app POSTs `/api/tvapp {visible, intentional}`; `ensure_dashboard`
  relaunches if it doesn't show within 8 s or is pushed aside within 15 s (`settle`).
- **The live preview (`tvwindow.show`) must wait ~20 s after the app (re)starts** (`PREVIEW_DELAY`
  in the TV app). Starting it while the TV is still waking makes the TV switch to full-screen live
  TV and push the dashboard aside.
- The TV app mutes on load, keeps mute if pushed aside during start-up (15 s grace, reset after
  being hidden > 30 s, i.e. a wake from standby), and restores sound only when the user leaves on
  purpose (tile, Samsung TV, Back; the page posts `{leaving: true}` before Pi-launched tiles).
- The TV's own mute icon appears whenever an app mutes; it can't be hidden.

## Local config and secrets: never commit

Git-ignored, local-only: `local.env`, `pi/config.local.json`, `pi/calendars.json` (private Google
iCal links), `tv-token.txt`, `CLAUDE.local.md`, `*.wgt`, certificate files (`*.p12`, `*.pri`,
`*.crt`, `*.csr`, `profiles.xml`, `device-profile.xml`) and signature XMLs. The Plex token is read at
runtime and never stored. Before committing, grep staged files for private IPs, coordinates,
`private-` links, tokens and MAC addresses.

## Common commands

```bash
scripts/deploy-pi.sh          # push pi/ changes and restart the service
scripts/install-tv-app.sh     # rebuild and reinstall the TV app
```
