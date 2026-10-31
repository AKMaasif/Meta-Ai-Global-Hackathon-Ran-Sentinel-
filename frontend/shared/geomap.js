const GeoMap = (() => {
  const US_BOUNDS = [[24.4, -125.0], [49.5, -66.9]];
  const TILES = { url: "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a> · States: US Census Bureau' };
  let states = null;
  const loadStates = () => states || (states = fetch("/shared/vendor/us-states-10m.json").then((r) => r.json())
    .then((t) => topojson.feature(t, t.objects.states)).catch(() => null));

  function create(opts = {}) {
    const el = document.createElement("div");
    el.className = "geomap";
    el.setAttribute("role", "application");
    el.setAttribute("aria-label", opts.label || "Network map");
    const map = L.map(el, { zoomControl: true, attributionControl: true, minZoom: opts.minZoom ?? 3, maxZoom: 17,
      maxBounds: opts.maxBounds || [[10, -170], [62, -50]], maxBoundsViscosity: 1.0, worldCopyJump: false, preferCanvas: false });
    let failed = 0;
    const tiles = L.tileLayer(TILES.url, { attribution: TILES.attribution, subdomains: "abcd", maxZoom: 19, crossOrigin: true })
      .on("tileerror", () => { if (++failed === 4) note.textContent = "Street map unavailable (offline). Showing state boundaries only."; })
      .on("tileload", () => { failed = 0; note.textContent = ""; })
      .addTo(map);
    const note = document.createElement("div");
    note.className = "geomap-note";
    el.appendChild(note);
    map.on("popupopen", () => { note.hidden = true; }).on("popupclose", () => { note.hidden = false; });
    loadStates().then((g) => {
      if (!g) return;
      L.geoJSON(g, { interactive: false, style: { color: "#7d9599", weight: 1, opacity: .9, fill: true, fillColor: "#ffffff", fillOpacity: .04 } }).addTo(map);
    });
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(el);
    return { el, map, tiles };
  }

  function mount(m, slot) {
    if (!slot) return;
    for (const c of [...slot.childNodes]) if (c !== m.el) c.remove();
    if (m.el.parentNode !== slot) slot.appendChild(m.el);
    requestAnimationFrame(() => m.map.invalidateSize());
  }

  function wedge(lat, lon, az, half = 30, km = 0.32) {
    const pts = [[lat, lon]];
    for (let a = az - half; a <= az + half; a += 6) {
      const r = (a * Math.PI) / 180;
      pts.push([lat + (km * Math.cos(r)) / 110.574, lon + (km * Math.sin(r)) / (111.32 * Math.cos((lat * Math.PI) / 180))]);
    }
    pts.push([lat, lon]);
    return pts;
  }

  return { create, mount, wedge, US_BOUNDS };
})();
