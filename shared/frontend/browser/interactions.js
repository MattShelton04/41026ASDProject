/** Domain-neutral interaction helpers for the controls that exist in PropertyScope. */

function ownerDocument(node) {
  return node?.ownerDocument || globalThis.document || null;
}

function resolveFocusTarget(root, target) {
  if (typeof target === "function") return target(root);
  if (typeof target === "string") return root.querySelector?.(target);
  return target || null;
}

/** Controls the one existing mobile navigation drawer without leaving hidden links tabbable. */
export function createDrawerController({
  drawer,
  toggle,
  mediaQuery,
  openClass = "open",
  lockClass = "ps-drawer-open",
  initialFocus = "a[href], button:not(:disabled)",
  scrim = null,
  openLabel = "Open navigation",
  closeLabel = "Close navigation",
}) {
  if (!drawer || !toggle || !mediaQuery) throw new TypeError("Drawer, toggle and media query are required.");
  const documentNode = ownerDocument(drawer);
  const focusableSelector = 'a[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';
  const isOpen = () => drawer.classList.contains(openClass);
  const setCompactState = () => {
    const compact = Boolean(mediaQuery.matches);
    drawer.inert = compact && !isOpen();
    drawer.setAttribute?.("aria-hidden", String(compact && !isOpen()));
    if (!compact) drawer.removeAttribute?.("aria-hidden");
  };
  const close = ({ restoreFocus = true } = {}) => {
    drawer.classList.remove(openClass);
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", openLabel);
    scrim?.setAttribute?.("hidden", "");
    documentNode?.body?.classList?.remove(lockClass);
    setCompactState();
    if (restoreFocus && mediaQuery.matches) toggle.focus?.();
  };
  const open = () => {
    if (!mediaQuery.matches) return;
    drawer.classList.add(openClass);
    drawer.inert = false;
    drawer.removeAttribute?.("aria-hidden");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", closeLabel);
    scrim?.removeAttribute?.("hidden");
    documentNode?.body?.classList?.add(lockClass);
    queueMicrotask(() => resolveFocusTarget(drawer, initialFocus)?.focus?.());
  };
  const toggleDrawer = () => { if (isOpen()) close(); else open(); };
  const keydown = (event) => {
    if (!mediaQuery.matches || !isOpen()) return;
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = [...drawer.querySelectorAll(focusableSelector)].filter((item) => !item.inert && !item.hidden);
    if (!focusable.length) {
      event.preventDefault();
      toggle.focus?.();
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1);
    if (event.shiftKey && documentNode.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && documentNode.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  const mediaChanged = () => {
    if (!mediaQuery.matches) close({ restoreFocus: false });
    else setCompactState();
  };

  toggle.addEventListener("click", toggleDrawer);
  drawer.addEventListener("click", (event) => { if (event.target.closest?.("a[href]")) close({ restoreFocus: false }); });
  scrim?.addEventListener?.("click", () => close());
  documentNode?.addEventListener?.("keydown", keydown);
  mediaQuery.addEventListener?.("change", mediaChanged);
  setCompactState();
  return { close, open, toggle: toggleDrawer, isOpen };
}

/** A status toast never takes focus and replaces, rather than stacks, repeated messages. */
export function createToastController(toast, { duration = 4200 } = {}) {
  let timer = 0;
  return {
    show(message, { tone = "info" } = {}) {
      if (!toast) return;
      clearTimeout(timer);
      toast.textContent = String(message);
      toast.dataset.tone = tone;
      toast.dataset.visible = "true";
      timer = setTimeout(() => {
        toast.dataset.visible = "false";
        toast.textContent = "";
      }, duration);
    },
    hide() {
      clearTimeout(timer);
      if (!toast) return;
      toast.dataset.visible = "false";
      toast.textContent = "";
    },
  };
}

/** Builds the common bounded, named horizontal-scroll region around a real table. */
export function createTableRegion(table, label, { className = "" } = {}) {
  const documentNode = ownerDocument(table);
  const region = documentNode.createElement("div");
  region.className = ["ps-table-region", className].filter(Boolean).join(" ");
  region.tabIndex = -1;
  region.setAttribute("role", "region");
  region.setAttribute("aria-label", `${label}. Scroll horizontally to compare all columns when needed.`);
  const hint = documentNode.createElement("p");
  hint.className = "ps-table-scroll-hint";
  hint.textContent = "Scroll horizontally to compare all columns.";
  hint.hidden = true;
  region.append(hint, table);
  const syncOverflow = () => {
    const overflows = Number(region.scrollWidth) > Number(region.clientWidth) + 1;
    region.tabIndex = overflows ? 0 : -1;
    region.dataset.overflow = String(overflows);
    hint.hidden = !overflows;
  };
  queueMicrotask(syncOverflow);
  if (globalThis.ResizeObserver) new ResizeObserver(syncOverflow).observe(region);
  return region;
}
