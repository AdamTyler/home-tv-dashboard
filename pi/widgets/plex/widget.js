Dashboard.register("plex", {
  render: function (el, p) {
    var esc = Dashboard.esc;
    if (p.error) {
      el.innerHTML = '<span class="muted">Plex unavailable</span>';
      return;
    }
    var html = "";
    p.playing.forEach(function (m) {
      html += '<div class="plex-playing"><div class="title">▶ ' + esc(m.title) + "</div>" +
        '<div class="who">' + esc(m.user + " · " + m.device) + "</div>" +
        '<div class="plex-bar"><i style="width:' + m.progress + '%"></i></div></div>';
    });
    if (!p.playing.length) html += '<div class="muted plex-idle">Nothing playing</div>';
    if (p.recent.length) {
      html += '<div class="muted plex-label">Recently added</div><ul class="plex-recent">';
      // Fewer recent items when something is playing, so it all fits.
      p.recent.slice(0, p.playing.length ? 2 : 5).forEach(function (t) {
        html += "<li>" + esc(t) + "</li>";
      });
      html += "</ul>";
    }
    el.innerHTML = html;
  }
});
