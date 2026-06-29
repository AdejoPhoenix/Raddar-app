// "Host an event" — a user drops a pin at their current location.
// High-intent action → triggers the Lazy Wall (OAuth) if anonymous, like bookmarking.
(function () {
  const btn = document.getElementById("host-btn");
  const modal = document.getElementById("host-modal");
  const form = document.getElementById("host-form");
  const cancel = document.getElementById("host-cancel");
  const statusEl = document.getElementById("host-status");
  const quotaEl = document.getElementById("host-quota");
  if (!btn) return;

  const open = () => {
    if (btn.disabled) return;
    statusEl.textContent = "";
    modal.hidden = false;
  };
  const close = () => (modal.hidden = true);

  btn.addEventListener("click", open);
  cancel.addEventListener("click", close);
  modal.addEventListener("click", (e) => {
    if (e.target === modal) close();
  });

  async function fetchSession() {
    return (await fetch("/api/session")).json();
  }

  // Generic accessible radiogroup: builds a button per option, wires click + roving-tabindex
  // arrow/Home/End/Space/Enter selection, and mirrors the chosen option's value into `hidden`.
  // `render(btn, opt)` decorates each button (chip text, swatch orb, …). Used by both the
  // category swatch picker and the cost chip picker.
  function wireRadioGroup(grid, hidden, options, render) {
    if (!grid || !hidden || grid.children.length) return;
    options.forEach((opt, i) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.setAttribute("role", "radio");
      btn.setAttribute("aria-checked", "false");
      btn.dataset.value = opt.value;
      btn.tabIndex = i === 0 ? 0 : -1;
      render(btn, opt);
      grid.appendChild(btn);
    });

    const select = (btn, focus) => {
      if (!btn) return;
      for (const b of grid.children) {
        const on = b === btn;
        b.setAttribute("aria-checked", on ? "true" : "false");
        b.classList.toggle("selected", on);
        b.tabIndex = on ? 0 : -1;
      }
      hidden.value = btn.dataset.value;
      if (focus) btn.focus();
    };

    grid.addEventListener("click", (e) => {
      const btn = e.target.closest("[role=radio]");
      if (btn) select(btn, true);
    });
    grid.addEventListener("keydown", (e) => {
      const items = [...grid.children];
      const cur = items.indexOf(e.target.closest("[role=radio]"));
      if (cur < 0) return;
      let next = null;
      if (e.key === "ArrowRight" || e.key === "ArrowDown") next = items[(cur + 1) % items.length];
      else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
        next = items[(cur - 1 + items.length) % items.length];
      else if (e.key === "Home") next = items[0];
      else if (e.key === "End") next = items[items.length - 1];
      else if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        select(items[cur], true);
        return;
      }
      if (next) {
        e.preventDefault();
        select(next, true);
      }
    });

    // initial selection matches the hidden input's server-rendered default
    const initial =
      [...grid.children].find((b) => b.dataset.value === hidden.value) || grid.firstElementChild;
    select(initial, false);
  }

  // Category picker as orb+glyph swatches — the same Vibe-First rendering as the live pins,
  // so the host previews exactly what others will see. Driven by the shared pins.js maps.
  function buildCategoryPicker() {
    const apiValue = (c) => c.charAt(0).toUpperCase() + c.slice(1); // enum form, e.g. "Music"
    const options = Object.keys(window.RADAR_CATEGORY_COLORS).map((c) => ({
      value: apiValue(c),
      cat: c,
    }));
    wireRadioGroup(
      document.getElementById("h-category-swatches"),
      document.getElementById("h-category"),
      options,
      (btn, opt) => {
        btn.className = "swatch";
        // --pin on the button: the orb inherits it, and the selected ring reuses it
        btn.style.setProperty("--pin", window.radarColorFor(opt.cat));
        const orb = document.createElement("span");
        orb.className = "pin swatch-orb";
        orb.innerHTML = window.radarGlyphFor(opt.cat);
        const label = document.createElement("span");
        label.className = "swatch-label";
        label.textContent = opt.value;
        btn.append(orb, label);
      }
    );
  }

  // Cost picker as Free / € / €€ / €€€ tap chips — same accessible radiogroup, text-only.
  function buildCostPicker() {
    const options = ["Free", "€", "€€", "€€€"].map((v) => ({ value: v }));
    wireRadioGroup(
      document.getElementById("h-cost-chips"),
      document.getElementById("h-cost"),
      options,
      (btn, opt) => {
        btn.className = "chip";
        btn.textContent = opt.value;
      }
    );
  }

  // Reflect the per-user pin quota on the button proactively ("4 of 5 used"; disabled at limit).
  function applyQuota(hosting) {
    if (!hosting) {
      // anonymous: leave the button active so tapping it triggers the Lazy Wall on submit
      quotaEl.hidden = true;
      btn.disabled = false;
      btn.title = "";
      return;
    }
    const { used, limit } = hosting;
    const full = used >= limit;
    quotaEl.textContent = `${used} of ${limit} used`;
    quotaEl.hidden = false;
    quotaEl.classList.toggle("full", full);
    btn.disabled = full;
    btn.title = full ? "You've reached your active pin limit" : "";
  }

  async function refreshQuota() {
    try {
      applyQuota((await fetchSession()).hosting);
    } catch (_) {}
  }

  // The server requires the pin to be within ~70m of the user's live GPS, so grab a fresh fix.
  function liveLocation() {
    return new Promise((resolve, reject) => {
      if (!navigator.geolocation) return reject(new Error("no-geolocation"));
      navigator.geolocation.getCurrentPosition(
        (pos) => resolve([pos.coords.longitude, pos.coords.latitude]),
        () => reject(new Error("denied")),
        { enableHighAccuracy: true, timeout: 8000 }
      );
    });
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const center =
      (window.RADAR_STATE && window.RADAR_STATE.center) || window.RADAR_CONFIG.anchor;
    const [lng, lat] = center;

    statusEl.textContent = "Locating…";
    let userLng, userLat;
    try {
      [userLng, userLat] = await liveLocation();
    } catch (_) {
      statusEl.textContent = "Enable location to host an event here.";
      return;
    }
    statusEl.textContent = "Posting…";

    const body = {
      title: document.getElementById("h-title").value,
      category: document.getElementById("h-category").value,
      cost_tier: document.getElementById("h-cost").value,
      duration_minutes: parseInt(document.getElementById("h-duration").value, 10),
      lat,
      lng,
      user_lat: userLat,
      user_lng: userLng,
    };

    const res = await fetch("/api/events", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": (await fetchSession()).csrf_token,
      },
      body: JSON.stringify(body),
    });

    if (res.status === 401) {
      // Lazy Wall → sign in, then come back to the map
      window.location.href = `/auth/login?next=${encodeURIComponent(location.pathname)}`;
      return;
    }
    if (res.status === 422 || res.status === 429) {
      // 422 = too far from your location; 429 = per-user pin quota reached
      const d = await res.json();
      statusEl.textContent = d.detail || "Couldn't host here.";
      return;
    }
    if (res.ok) {
      close();
      form.reset();
      refreshQuota(); // the count just went up — update the button
      if (window.radarRefresh) window.radarRefresh(); // show the new pin immediately
    } else {
      statusEl.textContent = "Couldn't post — please try again.";
    }
  });

  buildCategoryPicker(); // render the orb+glyph swatches once
  buildCostPicker(); // render the cost chips once
  refreshQuota(); // reflect current usage on page load
  // re-poll on the map's refetch interval so the count self-heals as pins expire
  const everyMs = ((window.RADAR_CONFIG && window.RADAR_CONFIG.refetchSeconds) || 90) * 1000;
  setInterval(refreshQuota, everyMs);
})();
