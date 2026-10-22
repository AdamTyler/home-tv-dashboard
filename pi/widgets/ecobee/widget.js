// Thermostats and their room sensors: temperature, humidity, what the HVAC is
// doing, and which rooms are occupied.
Dashboard.register("ecobee", {
  render: function (el, data) {
    var esc = Dashboard.esc;
    if (data.loading) {
      el.innerHTML = '<span class="muted">' + (data.error ? "Can't reach the thermostats" : "Connecting…") + "</span>";
      return;
    }
    var u = "°";
    var html = data.thermostats.map(function (t) {
      var detail = t.humidity != null ? t.humidity + "% humidity" : "";
      var setpoint = t.mode === "auto" ? t.heat_to + "–" + t.cool_to + u
        : t.mode === "heat" ? "heat to " + t.heat_to + u
        : t.mode === "cool" ? "cool to " + t.cool_to + u : "off";
      var action = t.action === "idle" ? "" :
        '<span class="eco-' + t.action + '">' + (t.action === "heating" ? "Heating" : "Cooling") + "</span> · ";
      return '<div class="eco-stat">' +
        '<div class="eco-main"><span class="eco-name">' + esc(t.name) + "</span>" +
        '<span class="eco-temp">' + t.temp + u + "</span></div>" +
        '<div class="eco-sub">' + action + esc(setpoint) + (detail ? " · " + detail : "") + "</div>" +
        t.sensors.map(function (s) {
          return '<div class="eco-room"><span class="dot ' + (s.occupied ? "ok" : "") + '"></span>' +
            "<span>" + esc(s.name) + '</span><span class="val">' + s.temp + u + "</span></div>";
        }).join("") + "</div>";
    }).join("");
    if (data.error) html += '<div class="eco-stale muted">Last update ' + Math.round(data.age / 60) + " min ago</div>";
    el.innerHTML = html;
  }
});
