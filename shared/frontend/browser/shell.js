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
  const layout = root.documentElement;
  const measure = () => {
    if (header && layout) layout.style.setProperty("--ps-feature-header-height", `${header.getBoundingClientRect().height}px`);
    if (layout) layout.style.setProperty("--ps-feature-strip-height", `${strip?.getBoundingClientRect().height || 0}px`);
  };
  measure();
  const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
  if (header) observer?.observe(header);
  if (strip) observer?.observe(strip);
  return () => observer?.disconnect();
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
