// Slideshow of random photos from the Pi, crossfading every few seconds.
// Portrait photos are shown two at a time, side by side.
// display: {
//   "seconds": 12,
//   "fit": "blur"     whole photo over a blurred copy of itself (default)
//          "contain"  whole photo on black
//          "cover"    fill the space, cropping the edges
//   "pair_portraits": true,  show portrait photos two at a time
//   "pair_fit": "cover"      how each half of a pair is filled (same choices as fit)
// }
Dashboard.register("photos", {
  render: function (el, data, display, ctx) {
    var st = el._photos;
    if (!st) {
      var fit = display.fit || "blur", pairFit = display.pair_fit || "cover";
      el.className = "photos-stage photos-fit-" + fit + " photos-pairfit-" + pairFit;
      var slot = '<div class="photos-slot"><img class="photos-bg"><img class="photos-fg"></div>';
      var layer = '<div class="photos-layer">' + slot + slot + "</div>";
      el.innerHTML = layer + layer + '<div class="photos-empty"></div>';
      var layers = el.getElementsByClassName("photos-layer");
      st = el._photos = { front: layers[0], back: layers[1], queue: [], timer: null,
                          empty: el.lastChild, base: ctx.base,
                          blur: fit === "blur", pairBlur: pairFit === "blur",
                          pair: display.pair_portraits !== false, portrait: {} };
    }
    st.list = data.photos || [];
    // Keep what we've learned: the queue can still hold photos from an
    // earlier refresh, and they should still pair correctly.
    (data.portrait || []).forEach(function (id) { st.portrait[id] = true; });

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
    // Next slide: one photo, or two portraits side by side.
    function nextIds() {
      if (!st.queue.length) st.queue = shuffled();
      var first = st.queue.pop();
      if (!st.pair || !st.portrait[first]) return [first];
      for (var i = st.queue.length - 1; i >= 0; i--) {
        if (st.portrait[st.queue[i]]) return [first, st.queue.splice(i, 1)[0]];
      }
      return [first];  // no other portrait left this round
    }
    function next() {
      var layer = st.back, ids = nextIds();
      var slots = layer.getElementsByClassName("photos-slot");
      var blur = ids.length > 1 ? st.pairBlur : st.blur;
      var pending = ids.length * (blur ? 2 : 1);
      function loaded() {
        if (--pending) return;
        // Crossfade: the loaded back layer fades in over the front one.
        layer.className = "photos-layer show" + (ids.length > 1 ? " pair" : "");
        st.front.className = st.front.className.replace(" show", "");
        st.back = st.front;
        st.front = layer;
      }
      ids.forEach(function (id, n) {
        var bg = slots[n].firstChild, fg = slots[n].lastChild;
        fg.onload = fg.onerror = loaded;
        fg.src = st.base + "/photo/" + id;
        if (blur) {
          bg.onload = bg.onerror = loaded;
          bg.src = st.base + "/photo/" + id + "?size=small";
        }
      });
    }
    next();
    st.timer = setInterval(next, (display.seconds || 12) * 1000);
  }
});
