// Bookmark button → the Lazy Wall in action.
// Anonymous click returns 401 with a login_url; we send the user to single-tap OAuth and
// bring them right back to this event (next=).
(function () {
  const btn = document.getElementById("bookmark-btn");
  if (!btn) return;

  async function getSession() {
    const res = await fetch("/api/session");
    return res.json();
  }

  async function reflectState() {
    const s = await getSession();
    if (!s.authenticated) return;
    const res = await fetch("/api/bookmarks");
    if (!res.ok) return;
    const { event_ids } = await res.json();
    if (event_ids.includes(btn.dataset.eventId)) {
      btn.textContent = "★ Bookmarked";
      btn.classList.add("active");
    }
  }

  btn.addEventListener("click", async () => {
    const s = await getSession();
    const res = await fetch("/api/bookmarks", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": s.csrf_token },
      body: JSON.stringify({ event_id: btn.dataset.eventId }),
    });

    if (res.status === 401) {
      // Send to single-tap OAuth, returning to *this* event page (not the API path).
      window.location.href = `/auth/login?next=${encodeURIComponent(location.pathname)}`;
      return;
    }
    if (res.ok) {
      btn.textContent = "★ Bookmarked";
      btn.classList.add("active");
    }
  });

  reflectState();
})();
