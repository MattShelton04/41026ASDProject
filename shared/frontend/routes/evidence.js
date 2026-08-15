import { append, badge, cell, el, formatDate, formatNumber, humanise, link, notice, pageHeader, panel, researchAreaLabel, requestJson, table } from "../core.js";

export function acceptedReleaseReferences(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return items.filter((item) => item.target_feature === "feature-1").map((item) => ({
    id: item.id,
    dataset: item.dataset_id || "Unnamed dataset",
    area: researchAreaLabel(item.target_feature),
    version: item.release_version || "Unknown",
    records: item.record_count,
    acceptedAt: item.accepted_at,
    coverage: item.coverage_json?.complete === true ? "confirmed" : item.coverage_json ? "partial" : "unknown",
    hash: item.content_sha256 || "",
  }));
}

export function agentRunReferences(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  const productFeatures = new Set(["student-1-propertyscope-data-platform", "feature-1", "feature-2", "feature-3", "feature-4", "feature-5"]);
  return items.filter((item) => productFeatures.has(item.feature_key)).map((item) => ({
    id: item.id,
    area: researchAreaLabel(item.feature_key),
    objective: item.objective_preview || "Objective hidden by policy",
    status: item.status || "unknown",
    updatedAt: item.updated_at,
  }));
}

function statusTone(value) {
  if (["accepted", "succeeded", "confirmed"].includes(value)) return "confirmed";
  if (["failed", "partial", "review_required"].includes(value)) return "partial";
  return "unknown";
}

export function createEvidenceRoute({ config, announce }) {
  return async function renderEvidence(root) {
    append(root, pageHeader("About the data", "Evidence ledger", "Open the published datasets and recorded activity behind PropertyScope without losing source, date or status context.", [link("Open property data", config.dataOperations, "ps-button")]));
    const state = el("div", "dashboard-state", "Loading current evidence references…");
    state.setAttribute("role", "status");
    const releasePanel = panel("Published datasets", "The versions currently available to property research.");
    const agentPanel = panel("Recorded assisted activity", "Read-only links to plans, tool observations and review states.");
    const languagePanel = panel("Evidence language", "The same vocabulary applies across the product; data absence is never inferred from missing evidence.");
    append(root, state, el("div", "ps-grid ps-grid-2 evidence-grid"));
    const grid = root.querySelector(".evidence-grid");
    append(grid, releasePanel.card, agentPanel.card);
    append(root, languagePanel.card);
    const definitions = el("dl", "evidence-definitions");
    for (const [label, tone, detail] of [
      ["Confirmed", "confirmed", "Supported by the selected accepted source and release."],
      ["Partial", "partial", "Some bounded evidence is available; limitations remain visible."],
      ["Stale", "partial", "Evidence has an observed or effective date that needs attention."],
      ["Unknown", "unknown", "No supported conclusion can be made from current evidence."],
    ]) {
      const item = el("div");
      append(item, el("dt", "", ""), badge(label, tone), el("dd", "", detail));
      append(definitions, item);
    }
    append(languagePanel.body, definitions);

    const [releasesResult, runsResult] = await Promise.allSettled([
      requestJson("/api/data-platform/v1/dataset-releases?status=accepted&limit=20"),
      requestJson("/api/ai-mode/agent-runs?limit=10"),
    ]);
    const failures = [releasesResult, runsResult].filter((item) => item.status === "rejected");
    state.replaceChildren(notice(failures.length ? "warning" : "success", failures.length ? "Evidence index is partial" : "Evidence references loaded", failures.length ? "Available sections are preserved. Retry later for unavailable providers; missing references do not confirm a negative." : `Loaded from ${[releasesResult.value.requestId, runsResult.value.requestId].filter(Boolean).length} correlated public requests.`));

    if (releasesResult.status === "fulfilled") {
      const releases = acceptedReleaseReferences(releasesResult.value.body);
      if (releases.length) append(releasePanel.body, table(["Dataset", "Research area", "Accepted version", "Records", "Coverage", "Accepted"], releases, (item) => {
        const tr = el("tr");
        const dataset = el("div", "table-primary");
        append(dataset, link(item.dataset, `${config.releaseDetail}${encodeURIComponent(item.id)}`), el("code", "table-secondary mono", item.hash ? `${item.hash.slice(0, 12)}…` : "Hash unknown"));
        append(tr, cell(dataset), cell(item.area), cell(item.version, "mono"), cell(formatNumber(item.records), "numeric"), cell(badge(humanise(item.coverage), statusTone(item.coverage))), cell(formatDate(item.acceptedAt)));
        return tr;
      }, "Published dataset references"));
      else append(releasePanel.body, notice("info", "No published references", "No conclusion about source data can be made from this empty index."));
    } else append(releasePanel.body, notice("warning", "Published data index unavailable", `Open Property data operations for the current record. Request ID: ${releasesResult.reason.requestId || "not supplied"}.`));

    if (runsResult.status === "fulfilled") {
      const runs = agentRunReferences(runsResult.value.body);
      if (runs.length) append(agentPanel.body, table(["Run", "Area", "Objective", "State", "Updated"], runs, (item) => {
        const tr = el("tr");
        append(tr, cell(link(item.id.slice(0, 8), `${config.agentRuns}?run=${encodeURIComponent(item.id)}`, "mono"), "primary-cell"), cell(item.area), cell(item.objective), cell(badge(humanise(item.status), statusTone(item.status))), cell(formatDate(item.updatedAt)));
        return tr;
      }, "Durable agent-run references"));
      else append(agentPanel.body, notice("info", "No assisted activity", "Property search and data operations remain available without model activity."));
    } else append(agentPanel.body, notice("warning", "Activity index unavailable", `Published data references remain visible. Request ID: ${runsResult.reason.requestId || "not supplied"}.`));
    announce(failures.length ? "The shared evidence index loaded with unavailable providers." : "The shared evidence index loaded current references.");
  };
}
