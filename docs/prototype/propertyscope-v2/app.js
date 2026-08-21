import { icon, escapeHtml, badge } from "./components.js";
import { screenDefinitions } from "./screens.js";

const app = document.querySelector("#app");

const navGroups = [
  {
    label: "Shared workspace",
    links: [
      ["home", "Home", "home"],
      ["explore", "Explore properties", "search"],
      ["property", "Property research", "house"],
      ["evidence", "Evidence ledger", "link"],
      ["system-status", "System status", "activity"],
    ],
  },
  {
    label: "Feature 1 · Data",
    links: [
      ["data-overview", "Overview", "database"],
      ["sources", "Sources", "database"],
      ["jobs", "Jobs", "workflow"],
      ["runs", "Runs", "activity"],
      ["releases", "Releases", "bookmark"],
      ["quality", "Quality", "shield"],
      ["artifacts", "Artifacts", "box"],
      ["coverage", "Coverage", "layers"],
      ["discovery", "Discovery", "search"],
      ["ai-diagnosis", "AI diagnosis", "sparkles"],
    ],
  },
  {
    label: "Features 2–5",
    links: [
      ["market-cases", "Market intelligence", "trend", "Planned"],
      ["suburb-comparison", "Suburb context", "map", "Planned"],
      ["site-reviews", "Site due diligence", "layers", "Planned"],
      ["buyer-workspace", "Buyer workspace", "briefcase", "Planned"],
    ],
  },
  {
    label: "AI & releases",
    links: [
      ["agent-runs", "Agent runs", "bot"],
      ["grounded-answer", "Grounded answer", "book", "R1"],
      ["multi-agent-review", "Multi-agent review", "users", "R2"],
      ["release-roadmap", "Release roadmap", "calendar"],
    ],
  },
];

function currentRoute() {
  const raw = window.location.hash.replace(/^#\/?/, "").split(/[?&]/)[0];
  return screenDefinitions[raw] ? raw : "home";
}

function brand() {
  return `<a class="brand" href="#/home" data-route="home" aria-label="PropertyScope NSW home">
    <span class="brand-mark">${icon("layers")}</span>
    <span class="brand-copy"><strong>PropertyScope NSW</strong><span>Evidence-first property research</span></span>
  </a>`;
}

function topbar() {
  return `<header class="topbar">
    ${brand()}
    <form class="global-search" id="global-search-form" role="search">
      ${icon("search")}
      <input id="global-search-input" type="search" aria-label="Search properties" placeholder="Search address, suburb or PropertyScope reference">
      <span class="search-shortcut">⌘ K</span>
    </form>
    <div class="topbar-actions">
      <button class="release-switcher" type="button" data-prototype-action="release-switcher"><span class="dot"></span>Release 0<span aria-hidden="true">⌄</span></button>
      <button class="top-action" type="button" aria-label="Notifications" data-prototype-action="notifications">${icon("bell")}</button>
      <button class="avatar-button" type="button" aria-label="User menu" data-prototype-action="profile">MS</button>
      <button class="mobile-menu" type="button" aria-label="Open navigation" aria-expanded="false" id="mobile-menu">${icon("menu")}</button>
    </div>
  </header>`;
}

function releaseStrip() {
  return `<div class="release-strip" role="status">
    <span class="strip-status"><strong>Local prototype</strong></span><span class="separator">•</span>
    <span>Release 0 architecture</span><span class="separator">•</span>
    <span>OpenAI API · GPT-5.6 Luna</span><span class="separator">•</span>
    <span>MCP / RAG / multi-agent are release-gated</span>
  </div>`;
}

function rail(routeName) {
  const def = screenDefinitions[routeName];
  const contextIcon = def.feature === "Feature 1" ? "database" : def.feature === "Feature 2" ? "trend" : def.feature === "Feature 3" ? "map" : def.feature === "Feature 4" ? "layers" : def.feature === "Feature 5" ? "briefcase" : def.feature === "Release 1" ? "book" : def.feature === "Release 2" ? "users" : "home";
  const contextDetail = def.feature === "Shared" ? "Integrated application" : def.feature === "Feature 1" ? "Implemented priority feature" : def.feature.startsWith("Feature") ? "Full-scale product scope" : `${def.feature} capability`;
  const groups = navGroups.map((group) => `<section class="rail-section"><p class="rail-label">${escapeHtml(group.label)}</p><nav class="rail-nav" aria-label="${escapeHtml(group.label)}">${group.links.map(([path, label, iconName, navBadge]) => `<a class="rail-link" href="#/${path}" data-route="${path}" ${path === routeName ? 'aria-current="page"' : ""}>${icon(iconName)}<span>${escapeHtml(label)}</span>${navBadge ? `<span class="nav-badge ${navBadge === "Planned" ? "future" : ""}">${escapeHtml(navBadge)}</span>` : ""}</a>`).join("")}</nav></section>`).join("");
  return `<aside class="rail" id="primary-navigation">
    <div class="rail-context"><span class="rail-context-icon">${icon(contextIcon)}</span><span><strong>${escapeHtml(def.feature)}</strong><span>${escapeHtml(contextDetail)}</span></span></div>
    ${groups}
    <div class="rail-footer"><strong>Non-government research tool</strong>Source coverage and uncertainty are shown throughout. Verify material decisions with the relevant authority or qualified adviser.</div>
  </aside>`;
}

function shell(routeName) {
  const definition = screenDefinitions[routeName];
  return `${topbar()}${releaseStrip()}<div class="shell">${rail(routeName)}<main class="main" id="main-content" tabindex="-1"><div class="main-inner">${definition.render()}</div></main></div><div class="prototype-note">Interactive product prototype · static showcase data</div><div id="toast-region" class="toast-region" aria-live="polite"></div>`;
}

function render() {
  const routeName = currentRoute();
  const definition = screenDefinitions[routeName];
  app.innerHTML = shell(routeName);
  document.title = `${definition.title} — PropertyScope NSW`;
  document.body.dataset.screen = routeName;
  document.body.classList.remove("nav-open");
  window.scrollTo({ top: 0, behavior: "instant" });
  bindPageEvents();
}

function toast(message) {
  const region = document.querySelector("#toast-region");
  if (!region) return;
  const item = document.createElement("div");
  item.className = "toast";
  item.innerHTML = `${icon("check")}<span>${escapeHtml(message)}</span>`;
  region.append(item);
  requestAnimationFrame(() => item.classList.add("visible"));
  window.setTimeout(() => {
    item.classList.remove("visible");
    window.setTimeout(() => item.remove(), 220);
  }, 2400);
}

function bindPageEvents() {
  const mobileMenu = document.querySelector("#mobile-menu");
  mobileMenu?.addEventListener("click", () => {
    const open = document.body.classList.toggle("nav-open");
    mobileMenu.setAttribute("aria-expanded", String(open));
  });

  document.querySelectorAll("[data-route]").forEach((link) => {
    link.addEventListener("click", () => document.body.classList.remove("nav-open"));
  });

  const searchForm = document.querySelector("#global-search-form");
  searchForm?.addEventListener("submit", (event) => {
    event.preventDefault();
    window.location.hash = "#/explore";
  });

  document.querySelectorAll("button:not([disabled]):not(#mobile-menu)").forEach((control) => {
    if (control.closest("#global-search-form")) return;
    control.addEventListener("click", () => {
      if (control.dataset.prototypeAction === "release-switcher") {
        toast("Release capabilities are shown on the roadmap screen.");
      } else if (control.dataset.prototypeAction === "notifications") {
        toast("No unread prototype notifications.");
      } else if (control.dataset.prototypeAction === "profile") {
        toast("Profile and authentication are outside the semester scope.");
      } else if (!control.closest("a") && !control.hasAttribute("data-route")) {
        const label = control.textContent.trim() || control.getAttribute("aria-label") || "Action";
        toast(`${label} is represented as a prototype interaction.`);
      }
    });
  });
}

window.addEventListener("hashchange", render);
window.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    document.querySelector("#global-search-input")?.focus();
  }
  if (event.key === "Escape") document.body.classList.remove("nav-open");
});

if (!window.location.hash) window.location.hash = "#/home";
else render();
