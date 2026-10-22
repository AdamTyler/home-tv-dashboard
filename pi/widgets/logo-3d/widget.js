// Display-only widget: the logo extruded into 3D with Three.js, slowly
// rotating while its color drifts. Falls back to a flat logo without WebGL.
//
// display: {
//   "seconds": 16,        one full turn
//   "depth": 260,         extrusion depth, in logo units (the outline is ~2000 wide)
//   "fallback": "/widgets/logo/logo.svg"
// }
(function () {
  // The logo as a single outline (SVG coordinates, y down). The slash and the
  // bottom gap are channels cut in from the outer edge, so no holes are needed.
  var OUTLINE = [
    [997, 0], [1999, 1728], [1662, 1728], [1412, 1297], [585, 1293], [502, 1437],
    [1440, 1437], [1607, 1728], [0, 1728], [803, 336], [1092, 834], [849, 836],
    [752, 1004], [1241, 1004], [829, 290]
  ];
  var threeLoading = null;

  function loadThree() {
    if (window.THREE) return Promise.resolve();
    if (!threeLoading) {
      threeLoading = new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = "/widgets/logo-3d/three-r128.js";
        s.onload = resolve;
        s.onerror = reject;
        document.head.appendChild(s);
      });
    }
    return threeLoading;
  }

  function hasWebGL() {
    try {
      var c = document.createElement("canvas");
      return !!(c.getContext("webgl") || c.getContext("experimental-webgl"));
    } catch (e) {
      return false;
    }
  }

  function flatFallback(el, display) {
    var mark = document.createElement("div");
    mark.className = "logo3d-flat";
    var src = "url(" + (display.fallback || "/widgets/logo/logo.svg") + ")";
    mark.style.webkitMaskImage = mark.style.maskImage = src;
    el.appendChild(mark);
  }

  function build(el, display) {
    var THREE = window.THREE;
    var width = el.clientWidth, height = el.clientHeight;

    var renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    // The TV's GPU ignores `antialias`, so edges come out jagged. Render at a
    // higher resolution and let the browser scale it down (supersampling).
    renderer.setPixelRatio(display.supersample || 2);
    renderer.setSize(width, height);
    renderer.setClearColor(0x000000, 0);
    el.appendChild(renderer.domElement);

    var scene = new THREE.Scene();
    // A narrow lens from further away keeps perspective mild, so a corner
    // swinging toward the camera doesn't balloon.
    var camera = new THREE.PerspectiveCamera(18, width / height, 100, 20000);
    camera.position.set(0, 0, 7000);

    // Shape in three.js coordinates (y up), centered on the origin.
    var shape = new THREE.Shape();
    OUTLINE.forEach(function (p, i) {
      var x = p[0] - 1000, y = 864 - p[1];
      if (i === 0) shape.moveTo(x, y); else shape.lineTo(x, y);
    });
    shape.closePath();
    var depth = display.depth || 260;
    var geometry = new THREE.ExtrudeGeometry(shape, {
      depth: depth, bevelEnabled: true, bevelThickness: 24, bevelSize: 18, bevelSegments: 3
    });
    geometry.translate(0, 0, -depth / 2);

    var material = new THREE.MeshStandardMaterial({ metalness: 0.35, roughness: 0.35 });
    var logo = new THREE.Mesh(geometry, material);
    // A fixed tilt (on a parent, so it doesn't change with the spin) shows the
    // depth the same way for every corner.
    var tilt = new THREE.Group();
    tilt.rotation.x = display.tilt != null ? display.tilt : 0.12;
    tilt.add(logo);
    scene.add(tilt);

    scene.add(new THREE.AmbientLight(0xffffff, 0.45));
    var key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(1, 1.2, 2);
    scene.add(key);
    var rim = new THREE.DirectionalLight(0x88aaff, 0.5);
    rim.position.set(-2, -1, -1);
    scene.add(rim);

    // Fit: the largest scale at which the outline (front and back faces) stays
    // inside the card at every angle of the spin, with tilt and perspective.
    var half = depth / 2 + 24, corners = [];
    OUTLINE.forEach(function (p) {
      corners.push(new THREE.Vector3(p[0] - 1000, 864 - p[1], half));
      corners.push(new THREE.Vector3(p[0] - 1000, 864 - p[1], -half));
    });
    var margin = display.margin || 0.88, v = new THREE.Vector3();
    camera.updateMatrixWorld();  // projection needs the camera's position applied
    function fits(scale) {
      logo.scale.set(scale, scale, scale);
      for (var a = 0; a < 36; a++) {
        logo.rotation.y = a / 36 * Math.PI * 2;
        tilt.updateMatrixWorld(true);
        for (var i = 0; i < corners.length; i++) {
          v.copy(corners[i]).applyMatrix4(logo.matrixWorld).project(camera);
          if (Math.abs(v.x) > margin || Math.abs(v.y) > margin) return false;
        }
      }
      return true;
    }
    var lo = 0, hi = 4;
    for (var step = 0; step < 20; step++) {
      var mid = (lo + hi) / 2;
      if (fits(mid)) lo = mid; else hi = mid;
    }
    logo.scale.set(lo, lo, lo);

    var turn = (display.seconds || 16) * 1000;
    var start = Date.now();
    function frame() {
      requestAnimationFrame(frame);
      if (document.hidden) return;
      var t = (Date.now() - start) / turn;
      logo.rotation.y = t * Math.PI * 2;
      material.color.setHSL((t / 3) % 1, 0.65, 0.55);  // slow color drift
      renderer.render(scene, camera);
    }
    frame();
  }

  Dashboard.register("logo-3d", {
    render: function (el, data, display) {
      if (el.firstChild) return;  // static: build once
      el.className = "logo3d-stage";
      if (!hasWebGL()) return flatFallback(el, display);
      loadThree().then(function () {
        build(el, display);
      }).catch(function () {
        flatFallback(el, display);
      });
    }
  });
})();
