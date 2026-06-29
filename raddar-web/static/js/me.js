// "Your Raddar" — manage saved events and your own hosted pins (unsave / edit / delete).
// All mutations carry the CSRF token from the session, like bookmark.js / host.js.
(function () {
  const root = document.querySelector(".me");
  if (!root) return;

  async function csrfToken() {
    return (await (await fetch("/api/session")).json()).csrf_token;
  }
  const card = (id) => root.querySelector(`.me-card[data-id="${CSS.escape(id)}"]`);

  // Drop a card and keep the section's count + empty state honest.
  function removeCard(el) {
    if (!el) return;
    const section = el.closest(".me-section");
    const list = el.closest(".me-list");
    el.remove();
    const count = list.children.length;
    section.querySelector("h2 small").textContent = count;
    if (count === 0) {
      list.remove();
      const p = document.createElement("p");
      p.className = "empty";
      p.textContent = section.dataset.empty || "Nothing here yet.";
      section.appendChild(p);
    }
  }

  root.addEventListener("click", async (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    const id = btn.dataset.id;

    if (btn.classList.contains("unsave")) {
      const res = await fetch(`/api/bookmarks/${id}`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": await csrfToken() },
      });
      if (res.ok) removeCard(card(id));
    } else if (btn.classList.contains("delete")) {
      if (!confirm("Delete this pin? People will stop seeing it on the map.")) return;
      const res = await fetch(`/api/events/${id}`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": await csrfToken() },
      });
      if (res.ok) removeCard(card(id));
    } else if (btn.classList.contains("edit")) {
      const form = card(id).querySelector(".me-edit");
      form.hidden = !form.hidden;
    } else if (btn.classList.contains("cancel-edit")) {
      btn.closest(".me-edit").hidden = true;
    }
  });

  root.addEventListener("submit", async (e) => {
    const form = e.target.closest(".me-edit");
    if (!form) return;
    e.preventDefault();
    const id = form.dataset.id;

    const body = {
      title: form.title.value,
      category: form.category.value,
      cost_tier: form.cost_tier.value,
    };
    // empty = "keep current length" → omit so the server leaves the end time alone
    if (form.duration_minutes.value) {
      body.duration_minutes = parseInt(form.duration_minutes.value, 10);
    }

    const res = await fetch(`/api/events/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": await csrfToken() },
      body: JSON.stringify(body),
    });
    if (!res.ok) return;

    const ev = await res.json();
    const c = card(id);
    c.querySelector(".me-card-body a").textContent = ev.title;
    c.querySelector(".me-card-body small").textContent =
      `${ev.category} · ${ev.cost_tier} · ends in ${ev.minutes_until_end} min`;
    c.className =
      "me-card cat-" + String(ev.category).toLowerCase() + (ev.is_ending_soon ? " ending-soon" : "");
    form.hidden = true;
  });
})();
