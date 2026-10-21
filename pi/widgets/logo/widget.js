// Display-only widget: a logo with slowly shifting colors.
// display: { "src": "/widgets/logo/logo.svg", "seconds": 20 }
Dashboard.register("logo", {
  render: function (el, data, display) {
    if (el.firstChild) return;  // static: draw once
    var src = display.src || "/widgets/logo/logo.svg";
    var seconds = display.seconds || 20;
    var mark = document.createElement("div");
    mark.className = "logo-mark";
    mark.style.webkitMaskImage = mark.style.maskImage = "url(" + src + ")";
    mark.style.animationDuration = seconds + "s, " + (seconds * 3) + "s";
    el.className = "logo-stage";
    el.appendChild(mark);
  }
});
