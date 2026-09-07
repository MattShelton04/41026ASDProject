import { createDrawerController } from "./interactions.js";

/** Product navigation is shared; each feature retains its own work area and routes. */
export function resolveProductHome(location, configured = "") {
  const current = new URL(location.href);
  if (configured) {
    const target = new URL(configured, current);
    if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) {
      throw new TypeError("Product home must be an HTTP(S) URL without credentials.");
    }
    return target.href;
  }
  if (!current.pathname.startsWith("/features/") && ["localhost", "127.0.0.1", "[::1]"].includes(current.hostname)) {
    current.port = "5100";
  }
  current.pathname = "/";
  current.search = "";
  current.hash = "";
  return current.href;
}

/** Returns a disposer for embedding/tests; has no feature-domain dependencies. */
export function initialiseFeatureShell({ root = document, location = globalThis.location, homeUrl = globalThis.PROPERTYSCOPE_HOME_URL || "" } = {}) {
  const home = resolveProductHome(location, homeUrl);
  for (const link of root.querySelectorAll("[data-product-home]")) link.href = home;
  for (const link of root.querySelectorAll("[data-product-path]")) {
    link.href = new URL(link.dataset.productPath, home).href;
  }
  const header = root.querySelector(".ps-feature-header");
  const strip = root.querySelector(".workspace-strip");
  const nav = root.querySelector(".ps-product-nav");
  // Progressive enhancement: without JS, the ordinary product links still wrap visibly.
  let navigation = null;
  let toggle = null;
  let scrim = null;
  if (header && nav && root.createElement && globalThis.matchMedia) {
    nav.id ||= "ps-product-navigation";
    toggle = root.createElement("button");
    toggle.type = "button";
    toggle.className = "ps-product-menu-toggle";
    toggle.textContent = "Navigate";
    toggle.setAttribute("aria-controls", nav.id);
    toggle.setAttribute("aria-expanded", "false");
    header.insertBefore(toggle, nav);
    scrim = root.createElement("button");
    scrim.type = "button";
    scrim.className = "ps-product-menu-scrim";
    scrim.tabIndex = -1;
    scrim.hidden = true;
    scrim.setAttribute("aria-label", "Close product navigation");
    header.append(scrim);
    header.dataset.navigationEnhanced = "true";
    navigation = createDrawerController({
      drawer: nav, toggle, scrim,
      mediaQuery: globalThis.matchMedia("(max-width: 1100px)"),
      openClass: "ps-product-nav--open", lockClass: "ps-product-menu-open",
      openLabel: "Open product navigation", closeLabel: "Close product navigation",
    });
  }
  const layout = root.documentElement;
  const measure = () => {
    if (header && layout) layout.style.setProperty("--ps-feature-header-height", `${header.getBoundingClientRect().height}px`);
    if (layout) layout.style.setProperty("--ps-feature-strip-height", `${strip?.getBoundingClientRect().height || 0}px`);
  };
  measure();
  const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
  if (header) observer?.observe(header);
  if (strip) observer?.observe(strip);
  return () => {
    observer?.disconnect();
    navigation?.destroy();
    toggle?.remove();
    scrim?.remove();
    if (header) delete header.dataset.navigationEnhanced;
  };
}

/** Isolated entry point for feature HTML; the public barrel stays side-effect free. */
export function mountFeatureShell(options) {
  const dispose = initialiseFeatureShell(options);
  globalThis.addEventListener?.("pagehide", dispose, { once: true });
  return () => {
    globalThis.removeEventListener?.("pagehide", dispose);
    dispose();
  };
}
