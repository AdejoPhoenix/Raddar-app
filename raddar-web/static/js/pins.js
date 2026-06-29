// Vibe-First pin styling: category → gradient color. Single source of truth for the map
// and the side panel dots. Keep in sync with the CSS .cat-* classes.
window.RADAR_CATEGORY_COLORS = {
  music: "#e23a3a",      // red
  food: "#2faa55",       // green
  market: "#e8862a",     // orange
  art: "#8b48c9",        // purple
  nightlife: "#3a5bd9",  // indigo
  sports: "#1aa7a0",     // teal
  community: "#d9a521",  // amber
};

window.radarColorFor = function (category) {
  return window.RADAR_CATEGORY_COLORS[String(category).toLowerCase()] || "#888";
};

// The second Vibe-First layer: category → a white line-glyph rendered inside the orb.
// Shape + color encode the event type *redundantly*, so the map reads at a glance and
// survives red/green colour-blindness (Music=red and Food=green are our two busiest
// categories). Closed 7-item set — keep the keys in lock-step with the colours above.
// Each value is the inner markup of a 24×24 stroke icon (no fill); the renderer wraps it.
window.RADAR_CATEGORY_ICONS = {
  music: '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
  food: '<path d="M3 2v7c0 1.1.9 2 2 2h0a2 2 0 0 0 2-2V2"/><path d="M5 2v20"/><path d="M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3Zm0 0v7"/>',
  market: '<path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/>',
  art: '<path d="m9.06 11.9 8.07-8.06a2.85 2.85 0 1 1 4.03 4.03l-8.06 8.08"/><path d="M7.07 14.94c-1.66 0-3 1.35-3 3.02 0 1.33-2.5 1.52-2 2.02 1.08 1.1 2.49 2.02 4 2.02 2.2 0 4-1.8 4-4.04a3.01 3.01 0 0 0-3-3.02z"/>',
  nightlife: '<path d="M8 22h8"/><path d="M12 11v11"/><path d="m19 3-7 8-7-8Z"/>',
  sports: '<circle cx="12" cy="12" r="10"/><path d="M19.13 5.09C15.22 9.14 10 10.44 2.25 10.94"/><path d="M21.75 12.84c-6.62-1.41-12.14 1-16.38 6.32"/><path d="M8.56 2.75c4.37 6 6 9.42 8 17.72"/>',
  community: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
};

// White stroke glyph, sized/positioned by the .pin-glyph CSS. Empty string for unknown
// categories so the pin gracefully falls back to a plain colour orb.
window.radarGlyphFor = function (category) {
  const inner = window.RADAR_CATEGORY_ICONS[String(category).toLowerCase()];
  if (!inner) return "";
  return (
    '<svg class="pin-glyph" viewBox="0 0 24 24" fill="none" stroke="#fff" ' +
    'stroke-width="2.25" stroke-linecap="round" stroke-linejoin="round" ' +
    'aria-hidden="true">' + inner + "</svg>"
  );
};
