// Keeps the side panel in sync with the live event set and drives the empty state.
// The pulsing animation itself is CSS (.pin.pulsing / .event-item.ending-soon); this just
// rebuilds the list when the map re-fetches.
(function () {
  const listEl = document.getElementById("event-list");
  const countEl = document.getElementById("count");
  const emptyEl = document.getElementById("empty");
  const skeletonEl = document.getElementById("skeleton");
  const staleEl = document.getElementById("stale-banner");
  const cfg = window.RADAR_CONFIG;

  let hasData = listEl.children.length > 0; // server-rendered first paint counts as data

  // Loading: only show skeletons if we have nothing to show yet (avoid flicker on refetch).
  window.addEventListener("radar:loading", () => {
    if (!hasData && skeletonEl) {
      skeletonEl.hidden = false;
      listEl.hidden = true;
    }
  });

  // Stale: a refetch failed — keep the last known list, surface a reconnecting banner.
  window.addEventListener("radar:stale", () => {
    if (staleEl) staleEl.hidden = false;
  });

  window.addEventListener("radar:events", (ev) => {
    const events = ev.detail || [];
    if (staleEl) staleEl.hidden = true;
    if (skeletonEl) skeletonEl.hidden = true;
    listEl.hidden = false;
    hasData = true;
    countEl.textContent = `${events.length} within ${cfg.geofenceMiles} mi`;

    if (!events.length) {
      hasData = false;
      listEl.innerHTML = "";
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;

    listEl.innerHTML = events
      .map((e) => {
        const soon = e.is_ending_soon ? " ending-soon" : "";
        const color = window.radarColorFor(e.category);
        return `<li class="event-item cat-${String(e.category).toLowerCase()}${soon}" data-id="${e.event_id}">
            <span class="dot" style="color:${color}"></span>
            <div>
              <a href="/event/${e.event_id}">${e.title}</a>
              <small>${e.category} · ${e.cost_tier} · ends in ${e.minutes_until_end} min</small>
            </div>
          </li>`;
      })
      .join("");
  });
})();
