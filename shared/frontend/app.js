import { append, el, link, notice, parseShellRoute } from "./core.js";
import { createEvidenceRoute } from "./routes/evidence.js?v=9";
import { createFeaturesRoute } from "./routes/features.js?v=9";
import { createRoadmapRoute } from "./routes/roadmap.js?v=9";
import { createStatusRoute } from "./routes/status.js?v=9";
import { featureRegistry } from "./features.js?v=9";

const defaults = Object.freeze({
  propertyDiscovery: "/features/data-platform/#properties",
  dataOperations: "/features/data-platform/#overview",
  releaseDetail: "/features/data-platform/#releases/",
  agentRuns: "/operations/ai-mode/?feature_key=student-1-propertyscope-data-platform",
});
const config = Object.freeze({ ...defaults, ...(window.PROPERTYSCOPE_CONFIG || {}) });
const main = document.querySelector("#main-content");
const homeMarkup = main.innerHTML;
const homeRail = main.querySelector(".product-rail")?.cloneNode(true);
const toast = document.querySelector("#toast");
const announcement = document.querySelector("#route-announcement");
const navToggle = document.querySelector("#nav-toggle");
const primaryNav = document.querySelector("#primary-navigation");
let toastTimer = 0;
let renderGeneration = 0;

function announce(message) {
  if (announcement) announcement.textContent = message;
}

function showToast(message) {
  if (!toast) return;
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.dataset.visible = "true";
  toastTimer = window.setTimeout(() => { toast.dataset.visible = "false"; }, 3600);
}

function applyConfigLinks(root = document) {
  root.querySelectorAll("[data-config-link]").forEach((item) => {
    const target = config[item.dataset.configLink];
    if (target) item.href = target;
  });
}

function openPropertySearch(query = "") {
  const target = new URL(config.propertyDiscovery, window.location.href);
  if (query) {
    const hashBase = target.hash.split("?")[0] || "#properties";
    target.hash = `${hashBase}?q=${encodeURIComponent(query)}`;
  }
  window.location.assign(target.toString());
}

function bindHomeInteractions() {
  applyConfigLinks(main);
  renderHomeFeatures();
  main.querySelectorAll("[data-planned]").forEach((button) => {
    button.addEventListener("click", () => {
      showToast(button.dataset.planned || "This capability is planned for a later implementation slice.");
      main.querySelector("#research-areas")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });
  main.querySelector("#property-search-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    openPropertySearch(String(main.querySelector("#property-search")?.value || "").trim());
  });
}

function homeFeatureRow(feature) {
  const article = el("article", `area-row${feature.href ? " area-row--available" : ""}`);
  const icon = el("div", "area-icon", feature.icon);
  icon.setAttribute("aria-hidden", "true");
  const copy = el("div");
  append(copy, el("span", "area-kicker", feature.href ? "Available now" : "Planned"), el("h3", "", feature.label), el("p", "", feature.summary));
  append(article, icon, copy);
  if (feature.href) append(article, link("Open research area", feature.href, "ps-button ps-button--primary"));
  else append(article, el("span", "area-state", "Not available yet"));
  return article;
}

function renderHomeFeatures() {
  const list = main.querySelector("#feature-area-list");
  if (list) list.replaceChildren(...featureRegistry(config).map(homeFeatureRow));
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
  features: createFeaturesRoute({ config }),
  "system-status": createStatusRoute({ config, announce }),
  evidence: createEvidenceRoute({ config, announce }),
  "release-roadmap": createRoadmapRoute({ config }),
};

async function renderRoute() {
  const generation = ++renderGeneration;
  const route = parseShellRoute(location.hash);
  updateNavigation(route);
  if (route === "home") {
    if (!main.querySelector("#top")) main.innerHTML = homeMarkup;
    bindHomeInteractions();
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
    await routes[route](dashboard);
    if (generation !== renderGeneration) return;
    applyConfigLinks(dashboard);
    const routeTitle = route === "features" ? "Research areas" : route === "system-status" ? "Data status" : route === "evidence" ? "Sources and history" : "What’s available";
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
  openPropertySearch(String(document.querySelector("#header-search")?.value || "").trim());
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && navToggle?.getAttribute("aria-expanded") === "true") closeNavigation({ restoreFocus: true });
});
window.addEventListener("hashchange", renderRoute);
applyConfigLinks();
renderRoute();
