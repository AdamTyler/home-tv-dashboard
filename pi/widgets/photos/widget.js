// Slideshow of random photos from the Pi, crossfading every few seconds.
// display: {
//   "seconds": 12,
//   "fit": "blur"     whole photo over a blurred copy of itself (default)
//          "contain"  whole photo on black
//          "cover"    fill the card, cropping the edges
// }
Dashboard.register("photos", {
  render: function (el, data, display, ctx) {
    var st = el._photos;
    if (!st) {
      var fit = display.fit || "blur";
      el.className = "photos-stage photos-fit-" + fit;
      var layer = '<div class="photos-layer"><img class="photos-bg"><img class="photos-fg"></div>';
      el.innerHTML = layer + layer + '<div class="photos-empty"></div>';
      var layers = el.getElementsByClassName("photos-layer");
      st = el._photos = { front: layers[0], back: layers[1], queue: [], timer: null,
                          empty: el.lastChild, base: ctx.base, blur: fit === "blur" };
    }
    st.list = data.photos || [];

    if (!st.list.length) {
      var pickUrl = location.protocol + "//" + location.host + st.base + "/pick";
      st.empty.innerHTML = "No photos yet.<br>Add some from your phone:<br><b>" +
        Dashboard.esc(pickUrl) + "</b>";
      st.empty.style.display = "block";
      return;
    }
    st.empty.style.display = "none";
    if (st.timer) return;  // already running; new list is used as the queue empties

    function shuffled() {
      var a = st.list.slice();
      for (var i = a.length - 1; i > 0; i--) {
        var j = Math.floor(Math.random() * (i + 1)), t = a[i];
        a[i] = a[j];
        a[j] = t;
      }
      return a;
    }
    function next() {
      if (!st.queue.length) st.queue = shuffled();
      var layer = st.back, id = st.queue.pop();
      var fg = layer.lastChild, bg = layer.firstChild;
      var pending = st.blur ? 2 : 1;
      function loaded() {
        if (--pending) return;
        // Crossfade: the loaded back layer fades in over the front one.
        layer.className = "photos-layer show";
        st.front.className = "photos-layer";
        st.back = st.front;
        st.front = layer;
      }
      fg.onload = fg.onerror = loaded;
      fg.src = st.base + "/photo/" + id;
      if (st.blur) {
        bg.onload = bg.onerror = loaded;
        bg.src = st.base + "/photo/" + id + "?size=small";
      }
    }
    next();
    st.timer = setInterval(next, (display.seconds || 12) * 1000);
  }
});
