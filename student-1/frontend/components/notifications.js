import { collection } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatDate } from "../core/formats.js";
import { notificationLink, notificationTitle, reconcileNotifications } from "../core/notifications.js";

const VISIBLE_POLL_MS = 15_000;
const HIDDEN_POLL_MS = 30_000;

export function mountNotifications(host, request, announce) {
  const storageKey = "propertyscope.data-notifications.v1";
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(storageKey)); } catch { /* Storage is optional. */ }
  if (!saved || !Array.isArray(saved.items) || typeof saved.seen !== "object") saved = null;
  let timer = null;
  let pending = false;
  const inbox = el("details", "notification-inbox");
  const summary = el("summary", "button secondary small", "Notifications");
  const body = el("div", "notification-body stack");
  append(inbox, summary, body); append(host, inbox);
  const close = ({ restoreFocus = false } = {}) => {
    inbox.open = false;
    if (restoreFocus) summary.focus();
  };
  const updateSummary = () => {
    const unread = saved?.items.filter((item) => !item.read).length || 0;
    summary.textContent = `Notifications${unread ? ` (${unread})` : ""}`;
  };
  const persist = () => { try { localStorage.setItem(storageKey, JSON.stringify(saved)); } catch { /* In-memory operation remains available. */ } };
  const render = (warning = "") => {
    updateSummary();
    const heading = el("div", "notification-heading");
    const dismiss = button("×", "button secondary small", () => close({ restoreFocus: true }));
    dismiss.setAttribute("aria-label", "Close notifications");
    append(heading, el("h2", "", "Data updates"), dismiss);
    body.replaceChildren(heading);
    append(body, el("p", "", `Updates observed on this browser. Checked every ${VISIBLE_POLL_MS / 1000} seconds while the app is open; read state is saved on this device.`));
    if (warning) append(body, el("p", "notice warning", warning));
    if (saved?.items.length) append(body, button("Mark all as read", "button secondary small", () => {
      saved.items = saved.items.map((item) => ({ ...item, read: true })); persist(); render();
    }));
    const list = el("ul", "notification-list");
    for (const item of saved?.items || []) {
      const entry = el("li", item.read ? "is-read" : "is-unread");
      const target = link(notificationTitle(item), notificationLink(item));
      target.addEventListener("click", () => { item.read = true; persist(); inbox.open = false; render(); });
      append(entry, target, el("small", "", formatDate(item.at))); append(list, entry);
    }
    append(body, list);
    if (!saved?.items.length) append(body, el("p", "", "No new update notifications. Existing history is available in Update history."));
    if ("Notification" in window && Notification.permission === "default") {
      append(body, button("Enable desktop notifications", "button secondary small", async () => { await Notification.requestPermission(); render(); }));
    } else if ("Notification" in window) append(body, el("small", "", Notification.permission === "granted" ? "Desktop notifications enabled while this app is open." : "Desktop notifications are blocked in browser settings."));
  };
  const poll = async () => {
    if (pending) return;
    clearTimeout(timer); pending = true;
    try {
      const recent = await request("notifications");
      const runs = collection(recent.body);
      const result = reconcileNotifications(saved, runs); saved = result.state; persist();
      // Keep an open inbox stable so polling cannot steal keyboard focus.
      if (!inbox.open) render();
      else updateSummary();
      for (const item of result.added) {
        announce(notificationTitle(item));
        if ("Notification" in window && Notification.permission === "granted") {
          try {
            const notification = new Notification(notificationTitle(item), { tag: item.key });
            notification.onclick = () => { location.hash = notificationLink(item); window.focus(); notification.close(); };
          } catch { /* Some browsers require a service worker for desktop delivery. */ }
        }
      }
    } catch { if (!inbox.open) render("Notifications could not refresh. Retrying automatically."); }
    finally { pending = false; timer = setTimeout(poll, document.hidden ? HIDDEN_POLL_MS : VISIBLE_POLL_MS); }
  };
  inbox.addEventListener("toggle", () => { if (inbox.open) render(); });
  document.addEventListener("pointerdown", (event) => {
    if (inbox.open && !inbox.contains(event.target)) close();
  }, true);
  inbox.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !inbox.open) return;
    event.preventDefault();
    close({ restoreFocus: true });
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
  window.addEventListener("storage", (event) => {
    if (event.key !== storageKey) return;
    try { const incoming = JSON.parse(event.newValue); if (incoming?.items && incoming?.seen) saved = incoming; } catch { /* Ignore invalid external storage. */ }
    if (!inbox.open) render();
  });
  render(); poll();
}
