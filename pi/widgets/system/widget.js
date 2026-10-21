Dashboard.register("system", {
  render: function (el, data) {
    el.innerHTML = data.rows.map(function (r) {
      return Dashboard.row(r.state, r.name, r.value);
    }).join("");
  }
});
