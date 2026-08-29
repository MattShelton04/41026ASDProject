import { append, el, link, notice, parseShellRoute } from "./core.js?v=10";
import { createEvidenceRoute } from "./routes/evidence.js?v=10";
import { createAssistantRoute } from "./routes/assistant.js?v=2";
import { createFeaturesRoute } from "./routes/features.js?v=10";
import { createRoadmapRoute } from "./routes/roadmap.js?v=10";
import { createStatusRoute } from "./routes/status.js?v=10";
import { findFeature } from "./features.js?v=10";
import { loadFeature1Bridge } from "./feature-1-bridge.js?v=12";
import { createToastController } from "./browser/index.js?v=3";

const externalConfig = Object.freeze({ ...(window.PROPERTYSCOPE_CONFIG || {}) });
const config = { ...externalConfig };
let feature1Adapter = null;
const main = document.querySelector("#main-content");
const homeMarkup = main.innerHTML;
const homeRail = main.querySelector(".product-rail")?.cloneNode(true);
const toast = document.querySelector("#toast");
const announcement = document.querySelector("#route-announcement");
const navToggle = document.querySelector("#nav-toggle");
const primaryNav = document.querySelector("#primary-navigation");
const toastController = createToastController(toast, { duration: 3600 });
let renderGeneration = 0;
let activeRouteController = null;
let researchAreaRetryRequested = false;

function announce(message) {
  if (announcement) announcement.textContent = message;
}

function showToast(message) {
  toastController.show(message);
}

function applyConfigLinks(root = document) {
  root.querySelectorAll("[data-config-link]").forEach((item) => {
    const target = config[item.dataset.configLink];
    if (target) item.href = target;
  });
}

function researchAreaRegion(detail) {
  if (detail?.target?.id === "feature-area-list") return detail.target;
  if (detail?.elt?.id === "feature-area-list") return detail.elt;
  return detail?.elt?.closest?.("#feature-area-list") || null;
}

function updateResearchAreaStatus(message) {
  const status = document.querySelector("#research-areas-status");
  if (status) status.textContent = message;
}

document.addEventListener("htmx:beforeRequest", (event) => {
  const region = researchAreaRegion(event.detail);
  if (!region) return;
  researchAreaRetryRequested = Boolean(event.detail?.elt?.matches?.("[data-research-area-retry]"));
  region.setAttribute("aria-busy", "true");
  updateResearchAreaStatus("");
});

document.addEventListener("htmx:afterRequest", (event) => {
  researchAreaRegion(event.detail)?.setAttribute("aria-busy", "false");
});

document.addEventListener("htmx:afterSwap", (event) => {
  const region = researchAreaRegion(event.detail);
  if (!region) return;
  applyConfigLinks(region);
  updateResearchAreaStatus("Research areas loaded.");
  if (researchAreaRetryRequested) region.focus({ preventScroll: true });
  researchAreaRetryRequested = false;
});

document.addEventListener("htmx:responseError", (event) => {
  const region = researchAreaRegion(event.detail);
  if (!region) return;
  region.setAttribute("aria-busy", "false");
  updateResearchAreaStatus(
    "The research-area directory could not be refreshed. The available Property data link remains usable; retry when ready.",
  );
  researchAreaRetryRequested = false;
});

function openPrimarySearch(query = "") {
  const target = feature1Adapter?.primarySearchHref(query, window.location.href)
    || new URL(findFeature("property-records").href, window.location.href).href;
  window.location.assign(target);
}

function bindHomeInteractions() {
  applyConfigLinks(main);
  main.querySelectorAll("[data-planned]").forEach((button) => {
    button.addEventListener("click", () => {
      showToast(button.dataset.planned || "This capability is planned for a later implementation slice.");
      main.querySelector("#research-areas")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  main.querySelector("#property-search-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    openPrimarySearch(String(main.querySelector("#property-search")?.value || "").trim());
  });
}

function closeNavigation({ restoreFocus = false } = {}) {
  navToggle?.setAttribute("aria-expanded", "false");
  primaryNav?.classList.remove("topbar__nav--open");
  if (restoreFocus) navToggle?.focus();
}

function updateNavigation(route) {
  document.querySelectorAll("[data-shell-route]").forEach((item) => {
    const selected = item.dataset.shellRoute === route;
    if (selected) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  closeNavigation();
}

const routes = {
  assistant: createAssistantRoute({ announce }),
  features: createFeaturesRoute({ config }),
  "system-status": createStatusRoute({ config, getFeature1Adapter: () => feature1Adapter, announce }),
  evidence: createEvidenceRoute({ config, getFeature1Adapter: () => feature1Adapter, announce }),
  "release-roadmap": createRoadmapRoute({ config }),
};

async function renderRoute() {
  const generation = ++renderGeneration;
  activeRouteController?.destroy?.();
  activeRouteController = null;
  const route = parseShellRoute(location.hash);
  updateNavigation(route);
  if (route === "home") {
    const restoredHome = !main.querySelector("#top");
    if (restoredHome) main.innerHTML = homeMarkup;
    bindHomeInteractions();
    if (restoredHome) window.htmx?.process(main);
    document.title = "PropertyScope NSW";
    const anchor = location.hash.replace(/^#/, "");
    if (["", "home", "top", "research-areas", "operations"].includes(anchor)) {
      requestAnimationFrame(() => (document.getElementById(anchor)?.scrollIntoView({ block: "start" }) || window.scrollTo({ top: 0 })));
    }
    return;
  }

  const dashboardShell = el("div", "product-layout product-layout--dashboard");
  const dashboard = el("div", "ps-container dashboard");
  const rail = homeRail?.cloneNode(true);
  if (rail) {
    rail.querySelectorAll("a").forEach((item) => item.classList.toggle("is-current", item.getAttribute("href") === `#${route}`));
    append(dashboardShell, rail);
  }
  append(dashboardShell, dashboard);
  main.replaceChildren(dashboardShell);
  main.setAttribute("tabindex", "-1");
  try {
    const renderedController = await routes[route](dashboard) || null;
    if (generation !== renderGeneration) {
      renderedController?.destroy?.();
      return;
    }
    activeRouteController = renderedController;
    applyConfigLinks(dashboard);
    const routeTitle = route === "assistant" ? "Ask PropertyScope" : route === "features" ? "Research areas" : route === "system-status" ? "Data status" : route === "evidence" ? "Sources and history" : "What’s available";
    document.title = `${routeTitle} | PropertyScope NSW`;
    announce(`${routeTitle} loaded.`);
    main.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "instant" });
  } catch (error) {
    if (generation !== renderGeneration) return;
    dashboard.replaceChildren(notice("warning", "This shared view could not be loaded", `${error.message}. Return home or retry the route.`));
    append(dashboard, Object.assign(el("a", "ps-button", "Return home"), { href: "#home" }));
    announce("The shared view could not be loaded.");
  }
}

navToggle?.addEventListener("click", () => {
  const open = navToggle.getAttribute("aria-expanded") !== "true";
  navToggle.setAttribute("aria-expanded", String(open));
  primaryNav?.classList.toggle("topbar__nav--open", open);
});
primaryNav?.addEventListener("click", (event) => {
  if (event.target.closest("a")) closeNavigation();
});
document.querySelector("#header-search-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  openPrimarySearch(String(document.querySelector("#header-search")?.value || "").trim());
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && navToggle?.getAttribute("aria-expanded") === "true") closeNavigation({ restoreFocus: true });
});
window.addEventListener("hashchange", renderRoute);
applyConfigLinks();
renderRoute();

function installFeature1Adapter(adapter) {
  if (!adapter) return;
  feature1Adapter = adapter;
  Object.assign(config, adapter.links, { featureHrefs: { "property-records": adapter.links.propertyDiscovery } });
  applyConfigLinks();
  if (["features", "system-status", "evidence"].includes(parseShellRoute(location.hash))) {
    renderRoute();
  }
}

loadFeature1Bridge({ overrides: externalConfig, onLateAdapter: installFeature1Adapter })
  .then(installFeature1Adapter)
  .catch(() => {});
