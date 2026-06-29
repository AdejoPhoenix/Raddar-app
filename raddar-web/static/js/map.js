// MapLibre map: renders the geofenced, Now-and-Next events as gradient pins.
// First paint uses server-embedded data; geolocation + live re-fetch refine it.
(function () {
  const cfg = window.RADAR_CONFIG;

  // Default the map to the user's location: prefer their last known spot (cached from a
  // previous visit) so the map opens where they are instead of flashing the city anchor.
  // The anchor is only the true first-ever fallback (and when geolocation is denied).
  const LAST_CENTER_KEY = "radar:lastCenter";
  function loadLastCenter() {
    try {
      const v = JSON.parse(localStorage.getItem(LAST_CENTER_KEY));
      if (Array.isArray(v) && v.length === 2 && v.every((n) => typeof n === "number")) return v;
    } catch (_) {}
    return null;
  }
  function saveLastCenter(center) {
    try {
      localStorage.setItem(LAST_CENTER_KEY, JSON.stringify(center));
    } catch (_) {}
  }

  const startCenter = loadLastCenter() || cfg.anchor; // [lng, lat]
  let userCenter = startCenter;
  // shared so the host form can drop a pin at the map's current viewport center
  window.RADAR_STATE = { center: startCenter };

  const map = new maplibregl.Map({
    container: "map",
    // Free OSM raster style — no API key required. Swap for a vector style later.
    style: {
      version: 8,
      sources: {
        osm: {
          type: "raster",
          tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
          tileSize: 256,
          attribution: "© OpenStreetMap contributors",
        },
      },
      layers: [{ id: "osm", type: "raster", source: "osm" }],
    },
    center: startCenter,
    zoom: 14,
  });

  // keep the host pin location in sync with where the map is looking
  map.on("moveend", () => {
    const c = map.getCenter();
    window.RADAR_STATE.center = [c.lng, c.lat];
  });

  const markers = new Map(); // event_id → maplibregl.Marker

  function bootstrapEvents() {
    const el = document.getElementById("bootstrap-data");
    try {
      return JSON.parse(el.textContent);
    } catch (_) {
      return [];
    }
  }

  function renderMarkers(events) {
    const seen = new Set();
    for (const e of events) {
      seen.add(e.event_id);
      const color = window.radarColorFor(e.category);
      if (markers.has(e.event_id)) {
        const existing = markers.get(e.event_id).getElement();
        existing.style.setProperty("--pin", color);
        existing.classList.toggle("pulsing", !!e.is_ending_soon);
        continue;
      }
      const elPin = document.createElement("a");
      elPin.className = "pin" + (e.is_ending_soon ? " pulsing" : "");
      elPin.href = "/event/" + e.event_id;
      elPin.title = e.title;
      // category color drives the gradient + glow entirely in CSS (see .pin)
      elPin.style.setProperty("--pin", color);
      // category glyph: the second Vibe-First layer, so type reads by shape too (not colour alone)
      elPin.innerHTML = window.radarGlyphFor(e.category);
      elPin.dataset.id = e.event_id;
      const marker = new maplibregl.Marker({ element: elPin })
        .setLngLat([e.lng, e.lat])
        .addTo(map);
      markers.set(e.event_id, marker);
    }
    // remove markers no longer in window
    for (const [id, m] of markers) {
      if (!seen.has(id)) {
        m.remove();
        markers.delete(id);
      }
    }
    window.dispatchEvent(new CustomEvent("radar:events", { detail: events }));
  }

  async function fetchEvents() {
    const [lng, lat] = userCenter;
    const res = await fetch(`/api/events?lat=${lat}&lng=${lng}`);
    if (!res.ok) throw new Error(`api ${res.status}`);
    return res.json();
  }

  async function refresh() {
    window.dispatchEvent(new CustomEvent("radar:loading"));
    try {
      const events = await fetchEvents();
      renderMarkers(events); // fires radar:events
    } catch (_) {
      // network/API failure → keep last known pins, flag the data as stale
      window.dispatchEvent(new CustomEvent("radar:stale"));
    }
  }

  // let other scripts (e.g. host form) trigger a refresh after creating an event
  window.radarRefresh = refresh;

  // 1) instant paint from embedded data
  renderMarkers(bootstrapEvents());

  // 2) ask for precise location; fall back silently to last-known / anchor
  map.on("load", () => {
    if (navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          userCenter = [pos.coords.longitude, pos.coords.latitude];
          saveLastCenter(userCenter); // remember for next visit
          map.flyTo({ center: userCenter, zoom: 15 }); // moveend keeps RADAR_STATE.center in sync
          refresh();
        },
        () => refresh(), // denied/unavailable → keep last-known / anchor, still refresh
        { enableHighAccuracy: true, timeout: 4000 }
      );
    } else {
      refresh();
    }

    // 3) live re-fetch so urgency stays current
    setInterval(refresh, cfg.refetchSeconds * 1000);
  });
})();
