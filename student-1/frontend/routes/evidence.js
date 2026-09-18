import { collection, requestIdSuffix } from "../core/api.js";
import { append, el, link } from "../core/dom.js";
import { displayName, formatBytes, formatDate, formatNumber, humanise, researchAreaLabel } from "../core/formats.js";
import { badge, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

export function createEvidenceRoutes({ view, request, loading, generationGuard, rerender }) {
  function evidenceNavigation(kind, runId = "") {
    const nav = el("nav", "evidence-navigation state-tabs");
    nav.setAttribute("aria-label", "Evidence pages");
    for (const [route, label] of [["quality", "Data checks"], ["artifacts", "Files & history"], ["coverage", "Published coverage"]]) {
      const target = route === "coverage" || !runId ? `#${route}` : `#${route}/${encodeURIComponent(runId)}`;
      const item = link(label, target, "state-tab");
      if (route === kind) item.setAttribute("aria-current", "page");
      append(nav, item);
    }
    return nav;
  }
  async function renderEvidenceExplorer(kind, runId = "") {
    const routeEpoch = generationGuard.capture();
    loading(kind === "quality" ? "Loading data checks" : "Loading files");
    try {
      if (!runId) return await renderRunPicker(kind, routeEpoch);
      const [runResult, evidenceResult] = await Promise.allSettled([
        request(`ingestion-runs/${runId}`),
        request(`ingestion-runs/${runId}/${kind === "quality" ? "quality-results" : "artifacts"}?limit=100`),
      ]);
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren();
      append(view, pageHeading("Update details", kind === "quality" ? "Data checks" : "Files and history", kind === "quality" ? "Review the checks and samples recorded for one data update." : "Review the files, checksums and source history recorded for one data update.", [link("Choose another update", `#${kind}`, "button secondary")]));
      append(view, evidenceNavigation(kind, runId), link("← Back to this update", `#runs/${encodeURIComponent(runId)}`, "text-button"));
      if (runResult.status === "fulfilled") {
        const run = runResult.value.body.run || runResult.value.body;
        append(view, el("div", "notice", `Update ${run.id || runId} · ${humanise(run.status)} · started ${formatDate(run.requested_at || run.created_at)}.`));
      } else append(view, el("div", "notice warning", `The update summary is temporarily unavailable. Existing details are unchanged.${requestIdSuffix(runResult.reason)}`));
      if (evidenceResult.status === "rejected") { append(view, errorState(evidenceResult.reason, rerender)); return; }
      const items = collection(evidenceResult.value.body);
      if (!items.length) { append(view, emptyState(kind === "quality" ? "No data checks recorded" : "No files recorded", `The selected update has no recorded ${kind === "quality" ? "check results" : "file details"}.`)); return; }
      append(view, panel(`${formatNumber(items.length)} ${kind === "quality" ? "checks" : "files"}`, "Recorded for the selected update", kind === "quality" ? qualityTable(items) : artifactTable(items)));
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren(errorState(error, rerender));
    }
  }

  async function renderRunPicker(kind, routeEpoch) {
    const result = await request("ingestion-runs?limit=50");
    if (!routeEpoch.isCurrent()) return;
    const runs = collection(result.body);
    view.replaceChildren();
    append(view, pageHeading("Update details", kind === "quality" ? "Data checks" : "Files and history", `Choose a data update to inspect its ${kind === "quality" ? "check results" : "files"}.`));
    append(view, evidenceNavigation(kind));
    if (!runs.length) { append(view, emptyState("No data updates", `There are no updates with ${kind === "quality" ? "data checks" : "files"} yet.`)); return; }
    append(view, panel("Choose a data update", `${runs.length} recent updates`, makeTable(
      [{ label: "Update" }, { label: "State" }, { label: "Step" }, { label: "Started" }, { label: "Details" }], runs,
      (run) => { const row = el("tr"); append(row, cell(primaryCell(run.job_name || run.job_id || "Data update", run.id)), cell(badge(run.status)), cell(humanise(run.current_phase)), cell(formatDate(run.requested_at || run.created_at)), cell(link(kind === "quality" ? "View checks" : "View files", `#${kind}/${run.id}`, "button secondary small"), "actions-cell")); return row; },
    )));
  }

  async function renderCoverage() {
    const routeEpoch = generationGuard.capture();
    loading("Loading coverage matrix");
    try {
      const result = await request("dataset-releases?limit=100");
      if (!routeEpoch.isCurrent()) return;
      const rows = collection(result.body).filter((item) => ["accepted", "superseded"].includes(item.status)).map((release) => {
        const coverage = release.coverage_json || {};
        return { dataset_id: release.dataset_id, locality: coverage.locality || coverage.area || coverage.state || "NSW", coverage_status: coverage.status || (coverage.complete === false ? "partial" : "supported"), target_feature: release.target_feature, release_version: release.release_version, accepted_at: release.accepted_at, release_state: release.status, description: coverage.profile, limitations: coverage.limitations || coverage.known_limitations };
      });
      view.replaceChildren();
      append(view, pageHeading("Published data", "Data coverage", "See where each published dataset applies and whether its coverage is complete, partial, stale or unavailable."));
      append(view, evidenceNavigation("coverage"));
      append(view, el("div", "notice", `Coverage comes from published dataset details. Request ID ${result.requestId}. Missing entries mean coverage has not been recorded.`));
      if (!rows.length) { append(view, emptyState("No published coverage details", "Coverage appears after a dataset version is published.")); return; }
      append(view, panel(`${rows.length} coverage entries`, "Every colour is paired with a written status", makeTable(
        [{ label: "Dataset" }, { label: "Area" }, { label: "Research area" }, { label: "Coverage" }, { label: "Publication state" }, { label: "Published version" }, { label: "As at" }, { label: "Limitations" }], rows,
        (item) => { const row = el("tr"); append(row, cell(primaryCell(displayName(item.dataset_id), displayName(item.description))), cell(item.locality), cell(researchAreaLabel(item.target_feature)), cell(badge(item.coverage_status)), cell(badge(item.release_state)), cell(item.release_version, "mono"), cell(formatDate(item.accepted_at)), cell(item.limitations ? technicalDetails(item.limitations, "Inspect") : "None recorded")); return row; },
      )));
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren(errorState(error, rerender));
    }
  }

  return { renderEvidenceExplorer, renderCoverage };
}

function qualityTable(items) {
  return makeTable([{ label: "Rule" }, { label: "Dimension" }, { label: "Severity" }, { label: "Outcome" }, { label: "Observed / expected" }, { label: "Message" }, { label: "Sample" }], items,
    (item) => { const row = el("tr"); append(row, cell(primaryCell(item.rule_key, item.rule_version)), cell(humanise(item.dimension)), cell(badge(item.severity)), cell(badge(item.status)), cell(technicalDetails({ observed: item.observed_value_json, expected: item.expected_value_json }, "Compare")), cell(item.message || "No message recorded"), cell(item.sample_json ? technicalDetails(item.sample_json, "Inspect") : "No sample recorded")); return row; });
}

function artifactTable(items) {
  return makeTable([{ label: "Artifact" }, { label: "Type" }, { label: "Size" }, { label: "SHA-256" }, { label: "Retention" }, { label: "Created" }, { label: "Lineage" }], items,
    (item) => { const row = el("tr"); append(row, cell(primaryCell(item.logical_key, item.id)), cell(`${humanise(item.artifact_kind)} · ${item.media_type || "media type unknown"}`), cell(formatBytes(item.bytes), "numeric"), cell(String(item.content_sha256 || "Not recorded").slice(0, 24), "mono"), cell(badge(item.retention_class || "unknown")), cell(formatDate(item.created_at)), cell(technicalDetails({ ingestion_run_id: item.ingestion_run_id, task_id: item.ingestion_task_id, dataset_release_id: item.dataset_release_id }, "Inspect"))); return row; });
}
