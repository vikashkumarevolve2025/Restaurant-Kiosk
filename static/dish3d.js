/* 3D-style dish illustrations, drawn as SVG from a menu item's name, category and hue.
   No images to download: every dish is built in code, so new menu items get a picture too.
   Dish3D.svg(item) -> SVG markup; Dish3D.tilt(root, selector) -> cards lean toward the pointer. */
(function (global) {
  var uid = 0;

  function hash(s) { var h = 2166136261; for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; }
  // Seeded random numbers, so a dish looks the same every time it is drawn.
  function rng(seed) {
    return function () {
      seed = (seed + 0x6D2B79F5) | 0;
      var t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hsl(h, s, l, a) { return "hsl(" + h + " " + s + "% " + l + "%" + (a == null ? "" : " / " + a) + ")"; }
  function f(n) { return Math.round(n * 10) / 10; }

  function kind(item) {
    var n = (item.name || "").toLowerCase(), c = (item.cat || item.category || "").toLowerCase();
    // Whole words only: "steamed" must not read as "tea".
    if (/\b(soft drink|cola|coke|pepsi|soda|lime|juice|lassi|mojito|shake|drink|water|chaas|buttermilk|tea|chai|coffee)\b/.test(n)) return "drink";
    if (/naan|roti|kulcha|paratha|chapati|bread/.test(n)) return "bread";
    if (/raita|curd|salad/.test(n)) return "raita";
    if (/jamun|rasgulla|kheer|halwa|dessert|ice cream|payasam/.test(n)) return "dessert";
    if (/biryani|pulao/.test(n) || /biryani/.test(c)) return "biryani";
    if (/rice/.test(n)) return "rice";
    if (/curry|masala|dal|gravy|korma|kadai|butter chicken|sambar|makhani/.test(n) || /curr|gravy/.test(c)) return "curry";
    if (/lollipop|drumstick|wings/.test(n)) return "lollipop";
    return "plate";
  }

  // ---------- small builders ----------
  function radial(id, stops, cx, cy, r) {
    return '<radialGradient id="' + id + '" cx="' + (cx || "50%") + '" cy="' + (cy || "50%") + '" r="' + (r || "60%") + '">' +
      stops.map(function (s) { return '<stop offset="' + s[0] + '" stop-color="' + s[1] + '"/>'; }).join("") + "</radialGradient>";
  }
  function linear(id, stops, x2, y2) {
    return '<linearGradient id="' + id + '" x1="0" y1="0" x2="' + (x2 == null ? 0 : x2) + '" y2="' + (y2 == null ? 1 : y2) + '">' +
      stops.map(function (s) { return '<stop offset="' + s[0] + '" stop-color="' + s[1] + '"/>'; }).join("") + "</linearGradient>";
  }
  // An organic lump (a fried piece, a chunk in gravy, a naan): a wobbly ellipse with smooth curves.
  function blob(cx, cy, rx, ry, r, wobble, rot) {
    var n = 9, pts = [], a0 = (rot || 0) * Math.PI / 180;
    for (var i = 0; i < n; i++) {
      var a = (i / n) * Math.PI * 2, k = 1 - wobble / 2 + r() * wobble;
      var x = Math.cos(a) * rx * k, y = Math.sin(a) * ry * k;
      pts.push([cx + x * Math.cos(a0) - y * Math.sin(a0), cy + x * Math.sin(a0) + y * Math.cos(a0)]);
    }
    var d = "", m = function (p, q) { return [(p[0] + q[0]) / 2, (p[1] + q[1]) / 2]; }, s = m(pts[n - 1], pts[0]);
    d = "M" + f(s[0]) + " " + f(s[1]);
    for (var j = 0; j < n; j++) { var e = m(pts[j], pts[(j + 1) % n]); d += " Q" + f(pts[j][0]) + " " + f(pts[j][1]) + " " + f(e[0]) + " " + f(e[1]); }
    return d + "Z";
  }
  function leaf(x, y, size, rot, color) {
    return '<path d="M0 0 C' + f(size * 0.4) + " " + f(-size * 0.45) + " " + f(size) + " " + f(-size * 0.3) + " " + f(size * 1.2) + ' 0 C' +
      f(size) + " " + f(size * 0.3) + " " + f(size * 0.4) + " " + f(size * 0.45) + ' 0 0Z" fill="' + color + '" transform="translate(' + f(x) + " " + f(y) + ") rotate(" + f(rot) + ')"/>';
  }
  function steam(xs, top) {
    return xs.map(function (x, i) {
      return '<path class="d3-steam" style="animation-delay:' + (i * 0.9) + 's" d="M' + x + " " + top + " c-7 -8 7 -15 0 -24 c-7 -8 7 -15 0 -24" +
        '" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/>';
    }).join("");
  }

  // ---------- vessels ----------
  function plate(p, small) {
    var rx = small ? 88 : 104, ry = small ? 32 : 38;
    return '<ellipse cx="120" cy="124" rx="' + rx + '" ry="' + ry + '" fill="#bdb2a6"/>' +
      '<ellipse cx="120" cy="118" rx="' + rx + '" ry="' + ry + '" fill="url(#' + p + 'pl)"/>' +
      '<ellipse cx="120" cy="118" rx="' + (rx - 26) + '" ry="' + (ry - 11) + '" fill="url(#' + p + 'pw)"/>' +
      '<ellipse cx="120" cy="117" rx="' + (rx - 4) + '" ry="' + (ry - 2) + '" fill="none" stroke="#fff" stroke-opacity=".7" stroke-width="1.5"/>';
  }
  function plateDefs(p) {
    return radial(p + "pl", [[0, "#ffffff"], [0.7, "#f1ece6"], [1, "#d6cdc2"]], "40%", "30%", "75%") +
      radial(p + "pw", [[0, "#faf7f3"], [0.8, "#ece5dc"], [1, "#d9cfc3"]], "50%", "35%", "70%");
  }
  function bowl(p, top, ceramic) {
    // Body first, then the rim; the food goes on top of the rim ellipse.
    var body = "M30 " + top + " C34 " + (top + 48) + " 78 " + (top + 66) + " 120 " + (top + 66) + " C162 " + (top + 66) + " 206 " + (top + 48) + " 210 " + top + "Z";
    return '<path d="' + body + '" fill="url(#' + p + 'bw)"/>' +
      '<path d="' + body + '" fill="url(#' + p + 'bs)" opacity=".55"/>' +
      '<ellipse cx="120" cy="' + top + '" rx="90" ry="25" fill="' + (ceramic ? "#f7f2ec" : "#e7a46c") + '"/>' +
      '<ellipse cx="120" cy="' + (top + 2) + '" rx="81" ry="20" fill="' + (ceramic ? "#d9cfc4" : "#7a3712") + '"/>';
  }
  function bowlDefs(p, ceramic) {
    var body = ceramic
      ? [[0, "#ffffff"], [0.55, "#ece5dd"], [1, "#b9ada0"]]
      : [[0, "#f0a46a"], [0.45, "#c46a2c"], [1, "#5e290b"]];
    return linear(p + "bw", body) +
      // A soft highlight down the left side gives the bowl its roundness.
      linear(p + "bs", [[0, "#000"], [0.18, "#fff"], [0.3, "rgba(255,255,255,0)"], [0.8, "rgba(0,0,0,0)"], [1, "#000"]], 1, 0);
  }

  // ---------- food ----------
  function friedPieces(p, r, n, h, opts) {
    var out = [], pieces = [];
    for (var i = 0; i < n; i++) pieces.push({ x: 120 + (r() - 0.5) * 112, y: 110 + (r() - 0.5) * 22, rx: 18 + r() * 9, ry: 12 + r() * 6, rot: (r() - 0.5) * 60 });
    // A second layer heaped in the middle gives the plate some height.
    if (!(opts && opts.bone)) for (var j = 0; j < 3; j++) pieces.push({ x: 104 + j * 16 + (r() - 0.5) * 8, y: 96 + (r() - 0.5) * 6, rx: 17 + r() * 6, ry: 11 + r() * 4, rot: (r() - 0.5) * 50 });
    pieces.sort(function (a, b) { return a.y - b.y; });
    pieces.forEach(function (q) {
      out.push('<ellipse cx="' + f(q.x + 3) + '" cy="' + f(q.y + q.ry * 0.8) + '" rx="' + f(q.rx) + '" ry="' + f(q.ry * 0.45) + '" fill="#3b1a0a" opacity=".25"/>');
      out.push('<path d="' + blob(q.x, q.y, q.rx, q.ry, r, 0.35, q.rot) + '" fill="url(#' + p + 'fd)"/>');
      out.push('<ellipse cx="' + f(q.x - q.rx * 0.3) + '" cy="' + f(q.y - q.ry * 0.4) + '" rx="' + f(q.rx * 0.35) + '" ry="' + f(q.ry * 0.22) + '" fill="#fff" opacity=".35"/>');
      for (var k = 0; k < 4; k++) {
        out.push('<circle cx="' + f(q.x + (r() - 0.5) * q.rx * 1.3) + '" cy="' + f(q.y + (r() - 0.5) * q.ry) + '" r="' + f(0.8 + r() * 1.4) + '" fill="' +
          (r() < 0.5 ? hsl(h, 60, 18) : hsl(h, 80, 62)) + '" opacity=".8"/>');
      }
      if (opts && opts.bone) {
        var dx = q.x < 120 ? -1 : 1;
        out.push('<path d="M' + f(q.x + dx * q.rx * 0.6) + " " + f(q.y - 2) + " l" + f(dx * 16) + ' -8" stroke="#f3ead8" stroke-width="5.5" stroke-linecap="round"/>' +
          '<circle cx="' + f(q.x + dx * (q.rx * 0.6 + 17)) + '" cy="' + f(q.y - 11) + '" r="4" fill="#fbf4e6"/><circle cx="' + f(q.x + dx * (q.rx * 0.6 + 19)) + '" cy="' + f(q.y - 7) + '" r="3.5" fill="#efe4cf"/>');
      }
    });
    return out.join("");
  }
  function garnish(name, r) {
    var g = [];
    if (/lemon/.test(name)) {
      g.push('<path d="M172 120 a16 12 0 0 1 32 0z" fill="#f6d43c" transform="rotate(-18 188 120)"/><path d="M175 120 a13 9 0 0 1 26 0z" fill="#fff6c2" transform="rotate(-18 188 120)"/>');
      g.push('<path d="M40 112 a14 10 0 0 1 28 0z" fill="#f6d43c" transform="rotate(14 54 112)"/>');
    }
    if (/chilly|chilli|65|nati|andhra/.test(name)) {
      [[60, 128, -20], [168, 100, 25], [150, 130, -5]].forEach(function (c) {
        g.push('<path d="M0 0 q12 -6 26 2" fill="none" stroke="#2f8f3a" stroke-width="5" stroke-linecap="round" transform="translate(' + c[0] + " " + c[1] + ") rotate(" + c[2] + ')"/>' +
          '<path d="M0 0 l-5 -2" stroke="#1f5e26" stroke-width="3" stroke-linecap="round" transform="translate(' + c[0] + " " + c[1] + ") rotate(" + c[2] + ')"/>');
      });
    }
    if (/pepper/.test(name)) for (var i = 0; i < 26; i++) g.push('<circle cx="' + f(70 + r() * 100) + '" cy="' + f(96 + r() * 26) + '" r="' + f(0.8 + r()) + '" fill="#1c1410"/>');
    if (!g.length || /kabab|fry|mushroom|gobi|paneer/.test(name)) {
      g.push('<ellipse cx="62" cy="126" rx="13" ry="5" fill="none" stroke="#c98bb0" stroke-width="2.5"/><ellipse cx="178" cy="124" rx="11" ry="4.5" fill="none" stroke="#c98bb0" stroke-width="2.5"/>');
    }
    for (var j = 0; j < 4; j++) g.push(leaf(60 + r() * 120, 92 + r() * 34, 9 + r() * 4, r() * 360, j % 2 ? "#2f7d32" : "#3f9b45"));
    return g.join("");
  }
  function grains(r, n, region, palette) {
    var out = [];
    for (var i = 0; i < n; i++) {
      var x = region.x0 + r() * (region.x1 - region.x0), top = region.top(x), y = top + r() * (region.base - top);
      var c = palette[Math.floor(r() * palette.length)];
      out.push('<ellipse cx="' + f(x) + '" cy="' + f(y) + '" rx="3.6" ry="1.3" fill="' + c + '" transform="rotate(' + f(r() * 180) + " " + f(x) + " " + f(y) + ')"/>');
    }
    return out.join("");
  }

  // ---------- one dish ----------
  function svg(item) {
    var p = "d3" + (++uid) + "_", name = (item.name || "").toLowerCase(), h = item.hue == null ? 20 : item.hue;
    var r = rng(hash(String(item.id || name))), k = kind(item), defs = "", body = "", hot = true, steamTop = 84, steamX = [100, 122, 144];
    var foodStops = /paneer/.test(name) && k !== "curry" && k !== "biryani"
      ? [[0, hsl(42, 70, 90)], [0.55, hsl(38, 55, 74)], [1, hsl(30, 55, 48)]]
      : [[0, hsl(h, 85, 62)], [0.5, hsl(h, 72, 40)], [1, hsl(h, 65, 21)]];
    defs += radial(p + "fd", foodStops, "35%", "30%", "70%");
    defs += '<filter id="' + p + 'bl" x="-20%" y="-80%" width="140%" height="260%"><feGaussianBlur stdDeviation="6"/></filter>';
    var shadow = '<ellipse cx="120" cy="164" rx="96" ry="10" fill="#2a1408" opacity=".28" filter="url(#' + p + 'bl)"/>';

    if (k === "plate" || k === "lollipop") {
      defs += plateDefs(p);
      body = plate(p) + friedPieces(p, r, k === "lollipop" ? 5 : 7, h, { bone: k === "lollipop" }) + garnish(name, r);
    } else if (k === "curry") {
      defs += bowlDefs(p, true) + radial(p + "gv", [[0, hsl(h, 88, 58)], [0.6, hsl(h, 80, 43)], [1, hsl(h, 70, 28)]], "45%", "40%", "65%");
      var dal = /dal/.test(name);
      body = bowl(p, 98, true) + '<ellipse cx="120" cy="101" rx="75" ry="17" fill="url(#' + p + 'gv)"/>';
      for (var c = 0; c < (dal ? 0 : 5); c++) {
        var cx = 82 + r() * 76, cy = 97 + r() * 8, pal = /paneer/.test(name);
        body += '<path d="' + blob(cx, cy, 10 + r() * 5, 6 + r() * 2, r, 0.4, r() * 40) + '" fill="' + (pal ? hsl(40, 60, 84) : hsl(h, 60, 30)) + '"/>' +
          '<ellipse cx="' + f(cx - 3) + '" cy="' + f(cy - 2) + '" rx="3.5" ry="1.5" fill="#fff" opacity=".4"/>';
      }
      for (var o = 0; o < 6; o++) body += '<ellipse cx="' + f(70 + r() * 100) + '" cy="' + f(95 + r() * 12) + '" rx="' + f(2 + r() * 3) + '" ry="1.2" fill="' + hsl(h, 95, 68) + '" opacity=".6"/>';
      if (/butter|paneer|malai|makhani|korma/.test(name)) body += '<path d="M96 101 q24 -12 48 -1 q-22 9 -38 2 q12 -5 22 -1" fill="none" stroke="#fffaf0" stroke-width="3.5" stroke-linecap="round" opacity=".95"/>';
      if (dal) {
        body += '<path d="M104 96 q8 -4 16 1" stroke="#b5261a" stroke-width="4" stroke-linecap="round" fill="none"/><path d="M128 103 q7 -5 15 -1" stroke="#b5261a" stroke-width="4" stroke-linecap="round" fill="none"/>';
        for (var d = 0; d < 18; d++) body += '<ellipse cx="' + f(84 + r() * 72) + '" cy="' + f(95 + r() * 12) + '" rx="1.8" ry="0.8" fill="#5a3a1a"/>';
      }
      for (var l = 0; l < 5; l++) body += leaf(84 + r() * 70, 95 + r() * 10, 6 + r() * 3, r() * 360, l % 2 ? "#2f7d32" : "#46a24b");
      steamTop = 78;
    } else if (k === "biryani" || k === "rice") {
      var copper = k === "biryani";
      defs += bowlDefs(p, !copper);
      body = bowl(p, 104, !copper);
      var top = function (x) { var t = (x - 120) / 74; return 104 - 50 * Math.max(0, 1 - t * t); };
      body += '<path d="M46 104 C58 46 182 46 194 104 A74 20 0 0 1 46 104Z" fill="' + (copper ? "#f4e6c8" : "#f8f4ec") + '"/>';
      body += grains(r, copper ? 170 : 150, { x0: 50, x1: 190, top: top, base: 110 },
        copper ? ["#fffaf0", "#fffaf0", "#fffaf0", hsl(40, 95, 62), hsl(36, 95, 58), hsl(24, 90, 55)] : ["#ffffff", "#fbf7ef", "#f1eadc"]);
      if (copper) {
        if (/egg/.test(name)) [[100, 66], [140, 70]].forEach(function (e) {
          body += '<ellipse cx="' + e[0] + '" cy="' + e[1] + '" rx="15" ry="10" fill="#fffdf7" stroke="#e8e0cf"/><circle cx="' + e[0] + '" cy="' + (e[1] - 1) + '" r="6" fill="' + hsl(44, 95, 55) + '"/>';
        });
        else if (/veg/.test(name)) for (var v = 0; v < 22; v++) body += '<circle cx="' + f(64 + r() * 112) + '" cy="' + f(top(64 + r() * 112) + 6 + r() * 20) + '" r="' + f(2 + r() * 2) + '" fill="' + ["#43a047", "#ef6c00", "#f9a825", "#2e7d32"][v % 4] + '"/>';
        else if (/paneer/.test(name)) for (var q = 0; q < 5; q++) { var px = 78 + r() * 84; body += '<rect x="' + f(px) + '" y="' + f(top(px) + 4 + r() * 10) + '" width="13" height="10" rx="2.5" fill="' + hsl(40, 60, 82) + '" stroke="' + hsl(30, 50, 55) + '"/>'; }
        else for (var mt = 0; mt < 3; mt++) { var mx = 86 + mt * 34 + (r() - 0.5) * 10; body += '<path d="' + blob(mx, top(mx) + 10, 15, 10, r, 0.35, r() * 50) + '" fill="url(#' + p + 'fd)"/>'; }
        for (var fo = 0; fo < 12; fo++) { var fx = 62 + r() * 116; body += '<path d="M' + f(fx) + " " + f(top(fx) + 4 + r() * 14) + ' q4 -3 9 0" stroke="#7a3d14" stroke-width="2" fill="none" stroke-linecap="round"/>'; }
        for (var mi = 0; mi < 3; mi++) { var lx = 90 + r() * 60; body += leaf(lx, top(lx) + 2, 9, r() * 360, "#2e8b3d"); }
      }
      steamTop = 52; steamX = [104, 124, 144];
    } else if (k === "bread") {
      defs += plateDefs(p) + radial(p + "nn", [[0, hsl(42, 85, 82)], [0.6, hsl(36, 72, 66)], [1, hsl(28, 60, 46)]], "40%", "35%", "70%");
      body = plate(p, true);
      body += '<path d="' + blob(112, 106, 72, 26, r, 0.18, -8) + '" fill="url(#' + p + 'nn)"/>';
      body += '<path d="' + blob(128, 116, 64, 22, r, 0.2, 6) + '" fill="url(#' + p + 'nn)" stroke="' + hsl(30, 55, 52) + '" stroke-width="1"/>';
      for (var s = 0; s < 16; s++) body += '<ellipse cx="' + f(76 + r() * 104) + '" cy="' + f(102 + r() * 22) + '" rx="' + f(2 + r() * 4) + '" ry="' + f(1.2 + r() * 2) + '" fill="#6b3410" opacity="' + f(0.4 + r() * 0.4) + '"/>';
      body += '<ellipse cx="116" cy="110" rx="30" ry="6" fill="#fff8d8" opacity=".45"/>';
      for (var cl = 0; cl < 6; cl++) body += '<circle cx="' + f(90 + r() * 70) + '" cy="' + f(106 + r() * 14) + '" r="1.6" fill="#2f7d32"/>';
      steamTop = 88;
    } else if (k === "raita") {
      defs += bowlDefs(p, true) + radial(p + "rt", [[0, "#ffffff"], [1, "#e9e2d6"]]);
      body = bowl(p, 100, true) + '<ellipse cx="120" cy="103" rx="75" ry="17" fill="url(#' + p + 'rt)"/>';
      for (var t = 0; t < 26; t++) {
        var tx = 64 + r() * 112, ty = 96 + r() * 14, col = ["#5aa64a", "#9d4f8f", "#b5261a"][t % 3];
        body += t % 3 === 2 ? '<circle cx="' + f(tx) + '" cy="' + f(ty) + '" r=".9" fill="' + col + '"/>' : '<rect x="' + f(tx) + '" y="' + f(ty) + '" width="4" height="2.5" rx="1" fill="' + col + '" transform="rotate(' + f(r() * 90) + " " + f(tx) + " " + f(ty) + ')"/>';
      }
      body += leaf(118, 98, 12, -30, "#2e8b3d") + leaf(120, 99, 10, 200, "#46a24b");
      hot = false;
    } else if (k === "dessert") {
      defs += bowlDefs(p, true) + radial(p + "gj", [[0, "#c4682c"], [0.55, "#7a2e0c"], [1, "#3e1404"]], "35%", "30%", "70%");
      body = bowl(p, 104, true) + '<ellipse cx="120" cy="107" rx="75" ry="17" fill="' + hsl(36, 90, 55, 0.9) + '"/>';
      [[98, 92], [142, 94]].forEach(function (b) {
        body += '<ellipse cx="' + b[0] + '" cy="' + (b[1] + 14) + '" rx="22" ry="5" fill="#5a2a08" opacity=".35"/><circle cx="' + b[0] + '" cy="' + b[1] + '" r="22" fill="url(#' + p + 'gj)"/>' +
          '<ellipse cx="' + (b[0] - 8) + '" cy="' + (b[1] - 9) + '" rx="7" ry="4" fill="#fff" opacity=".45"/>';
      });
      for (var ps = 0; ps < 6; ps++) body += '<rect x="' + f(84 + r() * 70) + '" y="' + f(76 + r() * 18) + '" width="5" height="2" rx="1" fill="#7cb342" transform="rotate(' + f(r() * 180) + ' 120 90)"/>';
      steamTop = 64; steamX = [110, 132];
    } else {
      // Drink: a glass with ice, bubbles and a straw.
      var liquid = /soft drink|cola|coke|pepsi/.test(name) ? ["#7a3815", "#2c0f04"] : /lime|soda|mojito/.test(name) ? ["#d9f2a8", "#9ccc65"] :
        /lassi|shake|buttermilk|chaas/.test(name) ? ["#fffaf0", "#eadcc4"] : [hsl(h, 70, 55), hsl(h, 70, 32)];
      defs += linear(p + "lq", [[0, liquid[0]], [1, liquid[1]]]);
      body = '<path d="M150 36 L196 6" stroke="#e53935" stroke-width="7" stroke-linecap="round"/><path d="M150 36 L196 6" stroke="#fff" stroke-width="7" stroke-dasharray="6 6" stroke-linecap="butt" opacity=".9"/>' +
        '<path d="M84 64 L156 64 L149 156 Q120 164 91 156Z" fill="url(#' + p + 'lq)" opacity=".94"/>' +
        '<ellipse cx="120" cy="64" rx="36" ry="7" fill="' + liquid[0] + '" opacity=".9"/>';
      [[100, 62, 12], [128, 60, -18], [114, 74, 30]].forEach(function (ic) {
        body += '<rect x="' + (ic[0] - 9) + '" y="' + (ic[1] - 9) + '" width="18" height="18" rx="4" fill="#fff" fill-opacity=".35" stroke="#fff" stroke-opacity=".8" transform="rotate(' + ic[2] + " " + ic[0] + " " + ic[1] + ')"/>';
      });
      for (var bb = 0; bb < 12; bb++) body += '<circle cx="' + f(94 + r() * 50) + '" cy="' + f(84 + r() * 66) + '" r="' + f(1 + r() * 2) + '" fill="none" stroke="#fff" stroke-opacity=".6"/>';
      body += '<path d="M80 34 L160 34 L150 158 Q120 168 90 158Z" fill="#fff" fill-opacity=".12" stroke="#9fb3bf" stroke-width="2"/>' +
        '<ellipse cx="120" cy="34" rx="40" ry="8" fill="none" stroke="#9fb3bf" stroke-width="2"/>' +
        '<path d="M88 44 L96 150" stroke="#fff" stroke-width="5" stroke-linecap="round" opacity=".45"/>' +
        '<path d="M154 30 a14 14 0 0 1 22 10 l-11 2z" fill="#9ccc65" stroke="#689f38"/>';
      hot = false;
    }
    var label = item.name ? ' role="img" aria-label="' + String(item.name).replace(/"/g, "&quot;") + '"' : ' aria-hidden="true"';
    return '<svg class="d3" viewBox="0 0 240 180"' + label + ' xmlns="http://www.w3.org/2000/svg"><defs>' + defs + "</defs>" +
      shadow + '<g class="d3-dish">' + body + (hot ? steam(steamX, steamTop) : "") + "</g></svg>";
  }

  // Cards lean toward the mouse. Touch screens skip it (the dish still floats and steams).
  function tilt(root, selector) {
    if (!root || (global.matchMedia && global.matchMedia("(prefers-reduced-motion: reduce)").matches)) return;
    root.addEventListener("pointermove", function (e) {
      if (e.pointerType === "touch") return;
      var t = e.target.closest && e.target.closest(selector); if (!t) return;
      var b = t.getBoundingClientRect(), x = (e.clientX - b.left) / b.width - 0.5, y = (e.clientY - b.top) / b.height - 0.5;
      t.style.setProperty("--rx", (-y * 9).toFixed(2) + "deg"); t.style.setProperty("--ry", (x * 12).toFixed(2) + "deg");
    });
    root.addEventListener("pointerout", function (e) {
      var t = e.target.closest && e.target.closest(selector);
      if (t && !t.contains(e.relatedTarget)) { t.style.removeProperty("--rx"); t.style.removeProperty("--ry"); }
    });
  }

  // Shared animation styles, added once.
  if (global.document && !document.getElementById("d3-style")) {
    var st = document.createElement("style"); st.id = "d3-style";
    st.textContent = ".d3{display:block;width:100%;height:100%;overflow:visible}" +
      ".d3-dish{animation:d3float 5s ease-in-out infinite}" +
      ".d3-steam{opacity:0;animation:d3steam 3.4s ease-in-out infinite}" +
      "@keyframes d3float{50%{transform:translateY(-3px)}}" +
      "@keyframes d3steam{0%{opacity:0;transform:translateY(10px)}35%{opacity:.5}100%{opacity:0;transform:translateY(-16px)}}" +
      "@media (prefers-reduced-motion: reduce){.d3-dish,.d3-steam{animation:none}.d3-steam{opacity:.3}}";
    document.head.appendChild(st);
  }

  global.Dish3D = { svg: svg, tilt: tilt, kind: kind };
})(window);
