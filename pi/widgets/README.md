# Widgets

The bottom row of the dashboard is built from widgets. Each widget is a folder here:

```
pi/widgets/<type>/
  widget.py    data(options) -> dict        runs on the Pi (optional)
  widget.js    Dashboard.register(...)      runs on the TV
  widget.css   optional styles              runs on the TV
  *.svg|png|jpg|webp                        optional images, served at /widgets/<type>/<file>
```

`<type>` is lowercase letters, digits and dashes (for example `home-server`). A widget without
`widget.py` is display-only and gets `{}` as its data; see `logo/`.

## Showing a widget

Add it to `"widgets"` in `pi/config.json`, or in the Pi's `config.local.json` to keep it private
(a `"widgets"` key there replaces the whole list):

```json
{"type": "plex", "title": "Plex", "width": 1.6, "refresh": 15,
 "options": {"recent": 6},
 "display": {}}
```

| Key | Meaning |
|---|---|
| `type` | Folder name in `pi/widgets/` |
| `title` | Card heading; `""` hides it |
| `width` | Relative width in the row (fr units) |
| `refresh` | Seconds between data refreshes (default 15); `0` loads once |
| `options` | Passed to `widget.py` only. **Never sent to the TV**, so secrets and API keys belong here |
| `display` | Passed to `render()` on the TV, for presentation-only settings |

To keep a widget's options private (paths, API keys), put them in the Pi's git-ignored
`config.local.json` under `"widget_options"`, keyed by type. They're merged over the
widget's `options`:

```json
"widget_options": {"photos": {"folder": "/mnt/usb-drive/Photos"}}
```

The same type can appear more than once with different options. `config.json` parks widgets
that aren't shown under `"_unused_widgets"`, so you can swap them back in.

Included: `home-server`, `plex`, `system`, `logo` (an SVG with a slow color shift;
`display.src` and `display.seconds`), and `logo-3d` (the logo extruded and rotating in WebGL
with a bundled Three.js r128, the last version that runs on the TV's engine; `display.seconds`,
`display.depth`, `display.fallback` for a flat logo when WebGL isn't available), and `photos`
(a crossfading slideshow of a folder on the Pi, filled from Google Photos with a pick page;
`display.fit`: `blur` (default), `contain` or `cover`; see the main README), and `ecobee`
(thermostats and room sensors read locally over HomeKit; see the main README).

To screenshot a widget, open `http://<pi>:8080/?demo=1`. It shows sample data from
`pi/static/demo.json`; add a sample entry for your widget type there.

## widget.py

```python
def data(options):
    # Gather whatever the widget shows. Return JSON-serialisable data.
    return {"rows": [{"name": "Example", "state": "ok", "value": "42"}]}
```

Raise or return `{"error": "..."}` on failure. The server calls `data()` each time the TV asks
(every `refresh` seconds), so cache anything slow or rate-limited yourself.

A widget can also serve its own URLs under `/api/widget/<index>/...` by defining:

```python
def route(options, method, subpath, query, body):
    # Return a dict/list (JSON), (content_type, bytes), (content_type, bytes, status), or None (404).
```

In `render()`, the fourth argument `ctx.base` is that prefix (for example `/api/widget/1`).
`photos` uses this for resized images and its pick page.

## widget.js

The TV runs an old browser engine (Tizen 5.0): **no optional chaining, `??`, flex `gap` or
`aspect-ratio`**. Stick to ES5-style code like the existing widgets and check with `node --check`.

```js
Dashboard.register("my-widget", {
  render: function (el, data, display, ctx) {
    el.innerHTML = data.rows.map(function (r) {
      return Dashboard.row(r.state, r.name, r.value);  // "ok" | "warn" | "bad"
    }).join("");
  }
});
```

Helpers: `Dashboard.esc(text)` escapes HTML; `Dashboard.row(state, label, value)` renders a
status-dot row. CSS variables from the page (`--muted`, `--line`, `--ok`, ...) are available.
Prefix your CSS classes with the widget type to avoid clashes. Cards have a fixed height, so
design for a few rows.

Deploy with `scripts/deploy-pi.sh`; the TV picks up changes the next time the dashboard loads.
