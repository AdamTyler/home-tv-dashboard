# Widgets

The bottom row of the dashboard is built from widgets. Each widget is a folder here:

```
pi/widgets/<type>/
  widget.py    data(options) -> dict        runs on the Pi
  widget.js    Dashboard.register(...)      runs on the TV
  widget.css   optional styles              runs on the TV
```

`<type>` is lowercase letters, digits and dashes (for example `home-server`).

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
| `title` | Card heading |
| `width` | Relative width in the row (fr units) |
| `refresh` | Seconds between data refreshes (default 15) |
| `options` | Passed to `widget.py` only. **Never sent to the TV**, so secrets and API keys belong here |
| `display` | Passed to `render()` on the TV, for presentation-only settings |

The same type can appear more than once with different options.

## widget.py

```python
def data(options):
    # Gather whatever the widget shows. Return JSON-serialisable data.
    return {"rows": [{"name": "Example", "state": "ok", "value": "42"}]}
```

Raise or return `{"error": "..."}` on failure. The server calls `data()` each time the TV asks
(every `refresh` seconds), so cache anything slow or rate-limited yourself.

## widget.js

The TV runs an old browser engine (Tizen 5.0): **no optional chaining, `??`, flex `gap` or
`aspect-ratio`**. Stick to ES5-style code like the existing widgets and check with `node --check`.

```js
Dashboard.register("my-widget", {
  render: function (el, data, display) {
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
