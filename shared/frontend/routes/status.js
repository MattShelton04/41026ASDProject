import { append, badge, cell, el, formatDate, link, notice, pageHeader, panel, requestJson, table } from "../core.js";

export function classifyHealth(payload) {
  const raw = String(payload?.status || "unknown").toLowerCase();
  if (["healthy", "ready", "ok"].includes(raw)) return { readiness: "ready", label: "Ready", tone: "confirmed" };
  if (["degraded", "partial"].includes(raw)) return { readiness: "degraded", label: "Degraded", tone: "partial" };
  if (["unhealthy", "failed", "error"].includes(raw)) return { readiness: "unavailable", label: "Unavailable", tone: "partial" };
  return { readiness: "unknown", label: "Unknown", tone: "unknown" };
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
  for (const [term, value] of [["Owner", component.owner], ["Response", component.latency === null ? "Not observed" : `${component.latency} ms`], ["Request ID", component.requestId || "Not supplied"]]) {
    const row = el("div");
    append(row, el("dt", "", term), el("dd", term === "Request ID" ? "mono" : "", value));
    append(facts, row);
  }
  append(body, facts);
  if (component.href) append(body, link("Open operational detail", component.href, "ps-button ps-button--quiet health-card__link"));
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

async function check(name, kind, owner, path, detail, href = "") {
  const started = performance.now();
  try {
    const result = await requestJson(path);
    const health = classifyHealth(result.body);
    return { name, kind, owner, detail, href, enabled: true, latency: Math.round(performance.now() - started), requestId: result.requestId, ...health, payload: result.body };
  } catch (error) {
    return { name, kind, owner, detail: `${detail} The live check failed: ${error.message}.`, href, enabled: true, latency: null, requestId: error.requestId, readiness: "unavailable", label: "Unavailable", tone: "partial", error };
  }
}

export function createStatusRoute({ config, announce }) {
  return async function renderStatus(root) {
    const refresh = el("button", "ps-button ps-button--primary", "Refresh status");
    refresh.type = "button";
    append(root, pageHeader("Shared operations", "System status", "Live readiness for implemented shared and Property records services, kept separate from data coverage and future capability availability.", [refresh]));
    const summary = el("section", "status-summary");
    const cards = el("div", "ps-grid ps-grid-3 health-grid");
    const contracts = panel("Service boundaries", "Only public browser-facing projections are listed. Planned services remain unavailable by design.");
    append(root, summary, cards, contracts.card);

    async function load() {
      root.setAttribute("aria-busy", "true");
      refresh.disabled = true;
      cards.replaceChildren();
      append(cards, ...["Shared product shell", "Property records", "Property data store", "Agent activity", "Local model"].map((name) => {
        const card = el("div", "ps-card health-card health-card--loading");
        append(card, el("div", "ps-card__body", `Checking ${name}…`));
        return card;
      }));
      const shellStarted = performance.now();
      const shellCheck = fetch("/healthz", { headers: { Accept: "text/plain" } }).then(async (response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        await response.text();
        return { name: "Shared product shell", kind: "Frontend", owner: "Shared platform", detail: "This navigation and operational dashboard service is responding.", href: "#home", enabled: true, latency: Math.round(performance.now() - shellStarted), requestId: "Browser-local check", readiness: "ready", label: "Ready", tone: "confirmed" };
      }).catch((error) => ({ name: "Shared product shell", kind: "Frontend", owner: "Shared platform", detail: `The shell health check failed: ${error.message}.`, href: "#home", enabled: true, latency: null, requestId: "Browser-local check", readiness: "unavailable", label: "Unavailable", tone: "partial" }));
      const primaryComponents = await Promise.all([
        shellCheck,
        check("Property records", "Public API", "Property data service", "/api/shared-health/data-platform", "Deterministic property reads and operations remain available without AI.", config.dataOperations),
        check("Agent activity", "Shared API", "Shared platform", "/api/shared-health/ai-mode", "Durable agent evidence and its configured model dependency.", config.agentRuns),
      ]);
      const propertyApi = primaryComponents[1];
      const agentApi = primaryComponents[2];
      const components = [
        primaryComponents[0],
        propertyApi,
        dependencyComponent(propertyApi, {
          name: "Property data store",
          kind: "Owned dependency",
          owner: "Property data service",
          rawStatus: propertyApi.payload?.dependencies?.database,
          detail: propertyApi.payload?.dependencies?.database === true ? "The public Property records API reports its owned database dependency ready." : "The owned data-store readiness check did not pass.",
        }),
        agentApi,
        dependencyComponent(agentApi, {
          name: "Local model",
          kind: "AI dependency",
          owner: "Shared platform",
          rawStatus: agentApi.payload?.checks?.ollama?.status,
          detail: agentApi.payload?.checks?.ollama?.detail,
        }),
      ];
      const overall = overallReadiness(components);
      const checkedAt = new Date().toISOString();
      summary.replaceChildren(notice(overall === "ready" ? "success" : "warning", overall === "ready" ? "Implemented services are ready" : "Some implemented services need attention", `Checked ${formatDate(checkedAt)}. Planned student services are excluded from the health calculation.`));
      cards.replaceChildren(...components.map(healthCard));

      const planned = [
        ["Sales and market", "Student-owned service", "Planned", "No live route or readiness claim"],
        ["Suburb context", "Student-owned service", "Planned", "No live route or readiness claim"],
        ["Site and planning", "Student-owned service", "Planned", "No live route or readiness claim"],
        ["Buyer workspace", "Student-owned service", "Planned", "No live route or readiness claim"],
        ["MCP / RAG", "Shared platform", "Release-gated", "Not required for foundation CRUD"],
        ["Multi-agent", "Shared platform", "Release-gated", "Not active in this deployment"],
      ];
      contracts.body.querySelector(".dashboard-table-wrap")?.remove();
      append(contracts.body, table(["Capability", "Owner", "Availability", "Failure behaviour"], planned, (row) => {
        const tr = el("tr");
        append(tr, cell(row[0], "primary-cell"), cell(row[1]), cell(badge(row[2], "planned")), cell(row[3]));
        return tr;
      }, "Planned and release-gated service boundaries"));
      root.setAttribute("aria-busy", "false");
      refresh.disabled = false;
      announce(`Status refreshed. Implemented services are ${overall}.`);
    }

    refresh.addEventListener("click", load);
    await load();
  };
}
