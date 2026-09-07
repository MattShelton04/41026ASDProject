import { append, badge, cell, el, formatDate, link, notice, pageHeader, panel, requestJson, requestText, table } from "../core.js";
import { featureRegistry } from "../features.js";
import { capabilityManifest, capabilityState } from "../capabilities.js";

export function classifyHealth(payload) {
  const raw = String(payload?.status || "unknown").toLowerCase();
  if (["healthy", "ready", "ok"].includes(raw)) return { readiness: "ready", label: "Ready", tone: "confirmed" };
  if (["degraded", "partial"].includes(raw)) return { readiness: "degraded", label: "Degraded", tone: "partial" };
  if (["unhealthy", "failed", "error", "unavailable"].includes(raw)) return { readiness: "unavailable", label: "Unavailable", tone: "partial" };
  return { readiness: "unknown", label: "Unknown", tone: "unknown" };
}

export function researchServiceComponents(snapshot, config = {}) {
  return capabilityManifest(config, snapshot).services.filter((item) => ["mcp", "rag"].includes(item.id)).map((item) => {
    const state = capabilityState(item);
    return {
      name: item.label, kind: "Local research dependency", owner: "Shared platform",
      detail: item.detail, enabled: item.enabled !== false, latency: null, requestId: "Not supplied",
      readiness: item.enabled === false ? "disabled" : classifyHealth({ status: item.status }).readiness,
      ...state,
    };
  });
}

export function overallReadiness(components) {
  const enabled = components.filter((item) => item.enabled);
  if (enabled.some((item) => item.readiness === "unavailable")) return "unavailable";
  if (enabled.some((item) => ["degraded", "unknown"].includes(item.readiness))) return "degraded";
  return enabled.length ? "ready" : "unknown";
}

function healthCard(component) {
  const card = el("article", "ps-card health-card");
  const body = el("div", "ps-card__body");
  const top = el("div", "health-card__top");
  append(top, el("span", "health-card__kind", component.kind), badge(component.label, component.tone));
  append(body, top, el("h2", "", component.name), el("p", "", component.detail));
  const facts = el("dl", "health-card__facts");
  for (const [term, value] of [["Response time", component.latency === null ? "Not observed" : `${component.latency} ms`], ["Request ID", component.requestId || "Not supplied"]]) {
    const row = el("div");
    append(row, el("dt", "", term), el("dd", term === "Request ID" ? "mono" : "", value));
    append(facts, row);
  }
  append(body, facts);
  if (component.href) {
    const action = component.kind === "Feature API" ? `Open ${component.name}` : component.name === "AI review history" ? "Open Activity history" : "Open workspace";
    append(body, link(action, component.href, "ps-button ps-button--quiet health-card__link"));
  }
  append(card, body);
  return card;
}

function dependencyComponent(base, { name, kind, owner, rawStatus, detail }) {
  const health = rawStatus === true
    ? classifyHealth({ status: "healthy" })
    : rawStatus === false
      ? classifyHealth({ status: "unhealthy" })
      : rawStatus
        ? classifyHealth({ status: rawStatus })
        : { readiness: base.readiness === "unavailable" ? "unavailable" : "unknown", label: base.readiness === "unavailable" ? "Unavailable" : "Unknown", tone: base.readiness === "unavailable" ? "partial" : "unknown" };
  return {
    name,
    kind,
    owner,
    detail: detail || "Dependency readiness was not included in the public response.",
    enabled: true,
    latency: null,
    requestId: base.requestId,
    ...health,
  };
}

async function check(request, name, kind, owner, path, detail, href = "") {
  const started = performance.now();
  try {
    const result = await request(path);
    const health = classifyHealth(result.body);
    return { name, kind, owner, detail, href, enabled: true, latency: Math.round(performance.now() - started), requestId: result.requestId, ...health, payload: result.body };
  } catch (error) {
    if (error.name === "AbortError") throw error;
    return { name, kind, owner, detail: `${detail} The live check failed: ${error.message}.`, href, enabled: true, latency: null, requestId: error.requestId, readiness: "unavailable", label: "Unavailable", tone: "partial", error };
  }
}

export function createStatusRoute({
  config,
  getFeature1Adapter,
  announce,
  requestJson: requestJsonFn = requestJson,
  requestText: requestTextFn = requestText,
}) {
  return async function renderStatus(root) {
    const refresh = el("button", "ps-button ps-button--primary", "Refresh status");
    refresh.type = "button";
    append(root, pageHeader("PropertyScope", "Data status", "Check whether property search, published data and AI review history are available.", [refresh]));
    const summary = el("section", "status-summary");
    const cards = el("div", "ps-grid ps-grid-3 health-grid");
    const contracts = panel("Research area availability", "Planned areas stay unavailable until their data and workflows are ready.");
    append(root, summary, cards, contracts.card);

    async function load() {
      const features = featureRegistry(config);
      const enabledFeatures = features.filter((feature) => feature.implemented && feature.enabled);
      root.setAttribute("aria-busy", "true");
      root.dataset.loadState = "loading";
      refresh.disabled = true;
      cards.replaceChildren();
      append(cards, ...["Shared product shell", ...enabledFeatures.map((feature) => feature.label), "Agent activity"].map((name) => {
        const card = el("div", "ps-card health-card health-card--loading");
        append(card, el("div", "ps-card__body", `Checking ${name}…`));
        return card;
      }));
      const shellStarted = performance.now();
      const shellCheck = requestTextFn("/healthz").then(() => {
        return { name: "Shared product shell", kind: "Frontend", owner: "Shared platform", detail: "This navigation and operational dashboard service is responding.", href: "#home", enabled: true, latency: Math.round(performance.now() - shellStarted), requestId: "Browser-local check", readiness: "ready", label: "Ready", tone: "confirmed" };
      }).catch((error) => {
        if (error.name === "AbortError") throw error;
        return { name: "Shared product shell", kind: "Frontend", owner: "Shared platform", detail: `The shell health check failed: ${error.message}.`, href: "#home", enabled: true, latency: null, requestId: "Browser-local check", readiness: "unavailable", label: "Unavailable", tone: "partial" };
      });
      const capabilityCheck = requestJsonFn("/api/ai-mode/capabilities").then((result) => result.body).catch((error) => {
        if (error.name === "AbortError") throw error;
        return null;
      });
      const [primaryComponents, capabilitySnapshot] = await Promise.all([Promise.all([
        shellCheck,
        ...enabledFeatures.map((feature) => check(
          requestJsonFn,
          feature.label,
          "Feature API",
          feature.owner,
          feature.healthPath,
          `${feature.summary} Readiness is observed independently from its deployment gate.`,
          feature.href,
        )),
        check(requestJsonFn, "AI review history", "Shared API", "Shared platform", "/api/shared-health/ai-mode", "Recorded AI reviews and the configured model connection.", config.agentRuns),
      ]), capabilityCheck]);
      const shellApi = primaryComponents[0];
      const featureApis = primaryComponents.slice(1, 1 + enabledFeatures.length);
      const agentApi = primaryComponents.at(-1);
      const components = [shellApi, ...featureApis];
      const feature1Index = enabledFeatures.findIndex((feature) => feature.id === "property-records");
      const feature1Adapter = getFeature1Adapter();
      if (feature1Adapter && feature1Index >= 0) {
        for (const dependency of feature1Adapter.statusDependencies(featureApis[feature1Index])) {
          components.push(dependencyComponent(featureApis[feature1Index], dependency));
        }
      }
      components.push(
        agentApi,
        dependencyComponent(agentApi, {
          name: "AI provider",
          kind: "AI dependency",
          owner: "Shared platform",
          rawStatus: agentApi.payload?.checks?.llm_provider?.status,
          detail: agentApi.payload?.checks?.llm_provider?.detail,
        }),
      );
      components.push(...researchServiceComponents(capabilitySnapshot, config));
      const overall = overallReadiness(components);
      const checkedAt = new Date().toISOString();
      summary.replaceChildren(notice(overall === "ready" ? "success" : "warning", overall === "ready" ? "Checked services are ready" : "Some live services need attention", `Checked ${formatDate(checkedAt)}. Planned and deliberately disabled services are not counted as failures. Research dependency health is separate from ordinary feature access and evidence coverage.`));
      cards.replaceChildren(...components.map(healthCard));

      const planned = [
        ...features.filter((feature) => !feature.implemented || !feature.enabled).map((feature) => [
          feature.label,
          feature.implemented ? "Disabled" : "Planned",
          feature.implemented ? "Temporarily disabled" : "Coming later",
        ]),
        ["Coordinated research roles", "Planned", "Coming later"],
      ];
      contracts.body.querySelector(".dashboard-table-wrap")?.remove();
      append(contracts.body, table(["Research tool", "Availability", "Status"], planned, (row) => {
        const tr = el("tr");
        append(tr, cell(row[0], "primary-cell"), cell(badge(row[1], "planned")), cell(row[2]));
        return tr;
      }, "Planned research tools"));
      root.setAttribute("aria-busy", "false");
      root.dataset.loadState = "settled";
      refresh.disabled = false;
      announce(`Status refreshed. Implemented services are ${overall}.`);
    }

    refresh.addEventListener("click", load);
    await load();
  };
}
