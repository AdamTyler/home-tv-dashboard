// Slideshow of random photos from the Pi, crossfading every few seconds.
// display: { "seconds": 12 }
Dashboard.register("photos", {
  render: function (el, data, display, ctx) {
    var st = el._photos;
    if (!st) {
      el.className = "photos-stage";
      el.innerHTML = '<img class="photos-img"><img class="photos-img"><div class="photos-empty"></div>';
      var imgs = el.getElementsByTagName("img");
      st = el._photos = { front: imgs[0], back: imgs[1], queue: [], timer: null,
                          empty: el.lastChild, base: ctx.base };
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
      var img = st.back;
      img.onload = function () {
        // Crossfade: the loaded back image fades in over the front one.
        img.className = "photos-img show";
        st.front.className = "photos-img";
        st.back = st.front;
        st.front = img;
      };
      img.src = st.base + "/photo/" + st.queue.pop();
    }
    next();
    st.timer = setInterval(next, (display.seconds || 12) * 1000);
  }
});
