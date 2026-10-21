Dashboard.register("home-server", {
  render: function (el, data) {
    el.innerHTML = data.services.map(function (s) {
      return Dashboard.row(s.state, s.name, s.value);
    }).join("");
  }
});
