import { append, badge, cell, el, formatDate, formatNumber, humanise, link, notice, pageHeader, panel, requestJson, table } from "../core.js";

function statusTone(value) {
  if (["accepted", "succeeded", "confirmed"].includes(value)) return "confirmed";
  if (["failed", "partial", "review_required"].includes(value)) return "partial";
  return "unknown";
}

export function createEvidenceRoute({ config, getFeature1Adapter, announce, requestJson: request = requestJson }) {
  return async function renderEvidence(root) {
    const adapter = getFeature1Adapter();
    if (!adapter) {
      append(root, pageHeader("About the data", "Sources and history", "Feature evidence is temporarily unavailable while its public adapter loads."));
      append(root, notice("warning", "History unavailable", "Reload this page to retry if the feature connection remains unavailable."));
      announce("The shared evidence index is waiting for its feature provider.");
      return;
    }
    const { evidence } = adapter;
    const copy = evidence.copy;
    append(root, pageHeader("About the data", "Sources and history", copy.headerDescription, [link("Open Property data", config.dataOperations, "ps-button")]));
    const state = el("div", "dashboard-state", "Loading current records…");
    state.setAttribute("role", "status");
    state.dataset.loadState = "loading";
    const releasePanel = panel("Published datasets", copy.releasePanelDescription);
    const agentPanel = panel("AI review history", copy.agentPanelDescription);
    const languagePanel = panel("How statuses are used", "A missing record means that the answer is unknown, not that something is absent.");
    append(root, state, el("div", "ps-grid ps-grid-2 evidence-grid"));
    const grid = root.querySelector(".evidence-grid");
    append(grid, releasePanel.card, agentPanel.card);
    append(root, languagePanel.card);
    const definitions = el("dl", "evidence-definitions");
    for (const [label, tone, detail] of [
      ["Confirmed", "confirmed", "Supported by a published source and version."],
      ["Partial", "partial", "Some information is available, with limitations shown."],
      ["Stale", "partial", "Evidence has an observed or effective date that needs attention."],
      ["Unknown", "unknown", "No supported conclusion can be made from current evidence."],
    ]) {
      const item = el("div");
      append(item, el("dt", "", ""), badge(label, tone), el("dd", "", detail));
      append(definitions, item);
    }
    append(languagePanel.body, definitions);

    const [releasesResult, runsResult] = await Promise.allSettled([
      request(evidence.published.path),
      request(evidence.agentRuns.path),
    ]);
    const cancellation = [releasesResult, runsResult]
      .find((item) => item.status === "rejected" && item.reason?.name === "AbortError");
    if (cancellation) throw cancellation.reason;
    const failures = [releasesResult, runsResult].filter((item) => item.status === "rejected");
    state.replaceChildren(notice(failures.length ? "warning" : "success", failures.length ? "Some history is unavailable" : "Sources and history loaded", failures.length ? "Available sections are still shown. Try again later for anything missing." : "Current records loaded."));
    state.dataset.loadState = "settled";

    if (releasesResult.status === "fulfilled") {
      const releases = evidence.published.project(releasesResult.value.body);
      if (releases.length) append(releasePanel.body, table(["Dataset", "Research area", "Published version", "Records", "Coverage", "Published"], releases, (item) => {
        const tr = el("tr");
        const dataset = el("div", "table-primary");
        append(dataset, link(item.dataset, evidence.published.href(item.id, window.location.href)), el("span", "table-secondary area-transition-label", copy.transitionLabel), el("code", "table-secondary mono", item.hash ? `${item.hash.slice(0, 12)}…` : "Hash unknown"));
        append(tr, cell(dataset), cell(item.area), cell(item.version, "mono"), cell(formatNumber(item.records), "numeric"), cell(badge(humanise(item.coverage), statusTone(item.coverage))), cell(formatDate(item.acceptedAt)));
        return tr;
      }, "Published dataset references"));
      else append(releasePanel.body, notice("info", "No published references", copy.releaseEmpty));
    } else append(releasePanel.body, notice("warning", "Published data index unavailable", `${copy.releaseError} Request ID: ${releasesResult.reason.requestId || "not supplied"}.`));

    if (runsResult.status === "fulfilled") {
      const runs = evidence.agentRuns.project(runsResult.value.body);
      if (runs.length) append(agentPanel.body, table(["Run", "Area", "Objective", "State", "Updated"], runs, (item) => {
        const tr = el("tr");
        append(tr, cell(link(item.id.slice(0, 8), evidence.agentRuns.href(item.id, window.location.href), "mono"), "primary-cell"), cell(item.area), cell(item.objective), cell(badge(humanise(item.status), statusTone(item.status))), cell(formatDate(item.updatedAt)));
        return tr;
      }, "AI review references"));
      else append(agentPanel.body, notice("info", "No assisted activity", copy.agentEmpty));
    } else append(agentPanel.body, notice("warning", "Activity index unavailable", `${copy.agentError} Request ID: ${runsResult.reason.requestId || "not supplied"}.`));
    announce(failures.length ? "The shared evidence index loaded with unavailable providers." : "The shared evidence index loaded current references.");
  };
}
