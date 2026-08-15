(() => {
  "use strict";

  const defaults = Object.freeze({
    propertyDiscovery: "http://localhost:5200/#properties",
    dataOperations: "http://localhost:5200/#overview",
    agentRuns: "http://localhost:5005/operations/ai-mode/",
  });
  const config = Object.freeze({ ...defaults, ...(window.PROPERTYSCOPE_CONFIG || {}) });

  document.querySelectorAll("[data-config-link]").forEach((link) => {
    const key = link.dataset.configLink;
    if (config[key]) link.href = config[key];
  });

  const toast = document.querySelector("#toast");
  let toastTimer = 0;
  function showToast(message) {
    if (!toast) return;
    window.clearTimeout(toastTimer);
    toast.textContent = message;
    toast.dataset.visible = "true";
    toastTimer = window.setTimeout(() => { toast.dataset.visible = "false"; }, 3600);
  }

  document.querySelectorAll("[data-planned]").forEach((button) => {
    button.addEventListener("click", () => {
      showToast(button.dataset.planned || "This capability is planned for a later implementation slice.");
      document.querySelector("#research-areas")?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  });

  document.querySelector("#property-search-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    const query = String(document.querySelector("#property-search")?.value || "").trim();
    const target = new URL(config.propertyDiscovery, window.location.href);
    if (query) {
      const hashBase = target.hash.split("?")[0] || "#properties";
      target.hash = `${hashBase}?q=${encodeURIComponent(query)}`;
    }
    window.location.assign(target.toString());
  });
})();
