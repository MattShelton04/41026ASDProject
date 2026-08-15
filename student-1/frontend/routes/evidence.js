import { collection } from "../core/api.js";
import { append, el, link } from "../core/dom.js";
import { formatBytes, formatDate, formatNumber, humanise, researchAreaLabel } from "../core/formats.js";
import { badge, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

export function createEvidenceRoutes({ view, request, loading, rerender }) {
  async function renderEvidenceExplorer(kind, runId = "") {
    loading(`Loading ${kind} evidence`);
    try {
      if (!runId) return await renderRunPicker(kind);
      const [runResult, evidenceResult] = await Promise.allSettled([
        request(`ingestion-runs/${runId}`),
        request(`ingestion-runs/${runId}/${kind === "quality" ? "quality-results" : "artifacts"}?limit=100`),
      ]);
      view.replaceChildren();
      append(view, pageHeading("Run evidence", kind === "quality" ? "Quality checks" : "Files & lineage", kind === "quality" ? "Review the checks, expected values and samples recorded for one processing run." : "Review file metadata, checksums, retention and lineage recorded for one processing run.", [link("Choose another run", `#${kind}`, "button secondary")]));
      if (runResult.status === "fulfilled") {
        const run = runResult.value.body.run || runResult.value.body;
        append(view, el("div", "notice", `Exact run ${run.id || runId} · ${humanise(run.status)} · requested ${formatDate(run.requested_at || run.created_at)}.`));
      } else append(view, el("div", "notice warning", `Run summary is temporarily unavailable. Existing ${kind} evidence is retained.${problemSuffix(runResult.reason)}`));
      if (evidenceResult.status === "rejected") { append(view, errorState(evidenceResult.reason, rerender)); return; }
      const items = collection(evidenceResult.value.body);
      if (!items.length) { append(view, emptyState(`No ${kind} evidence recorded`, `The selected run has no ${kind === "quality" ? "quality results" : "artifact metadata"}. This is an unknown evidence state, not a confirmed negative.`)); return; }
      append(view, panel(`${formatNumber(items.length)} ${kind === "quality" ? "checks" : "file records"}`, "Evidence recorded by the selected run", kind === "quality" ? qualityTable(items) : artifactTable(items)));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  async function renderRunPicker(kind) {
    const result = await request("ingestion-runs?limit=50");
    const runs = collection(result.body);
    view.replaceChildren();
    append(view, pageHeading("Run evidence", kind === "quality" ? "Quality checks" : "Files & lineage", `Choose a processing run to inspect its ${kind === "quality" ? "quality results" : "file records"}. Evidence from different runs is kept separate.`));
    if (!runs.length) { append(view, emptyState("No ingestion runs", `No ${kind} evidence can be selected yet.`)); return; }
    append(view, panel("Choose a processing run", `${runs.length} recent runs`, makeTable(
      [{ label: "Run" }, { label: "State" }, { label: "Phase" }, { label: "Requested" }, { label: "Evidence" }], runs,
      (run) => { const row = el("tr"); append(row, cell(primaryCell(run.job_name || run.job_id || "Ingestion run", run.id)), cell(badge(run.status)), cell(humanise(run.current_phase)), cell(formatDate(run.requested_at || run.created_at)), cell(link(`Inspect ${kind}`, `#${kind}/${run.id}`, "button secondary small"), "actions-cell")); return row; },
    )));
  }

  async function renderCoverage() {
    loading("Loading coverage matrix");
    try {
      const result = await request("dataset-releases?limit=100");
      const rows = collection(result.body).filter((item) => ["accepted", "superseded"].includes(item.status)).map((release) => {
        const coverage = release.coverage_json || {};
        return { dataset_id: release.dataset_id, locality: coverage.locality || coverage.area || coverage.state || "NSW", coverage_status: coverage.status || (coverage.complete === false ? "partial" : "supported"), target_feature: release.target_feature, release_version: release.release_version, accepted_at: release.accepted_at, release_state: release.status, description: coverage.profile, limitations: coverage.limitations || coverage.known_limitations };
      });
      view.replaceChildren();
      append(view, pageHeading("Published data", "Data coverage", "See where each published dataset applies and whether its coverage is complete, partial, stale or unavailable."));
      append(view, el("div", "notice", `Coverage comes from published dataset metadata. Request ID ${result.requestId}. If a row is absent, coverage is unknown—not confirmed absent.`));
      if (!rows.length) { append(view, emptyState("No published coverage evidence", "Coverage appears only after a release has been accepted. No negative finding is inferred.")); return; }
      append(view, panel(`${rows.length} coverage entries`, "Every colour is paired with a written status", makeTable(
        [{ label: "Dataset" }, { label: "Area" }, { label: "Research area" }, { label: "Coverage" }, { label: "Publication state" }, { label: "Published version" }, { label: "As at" }, { label: "Limitations" }], rows,
        (item) => { const row = el("tr"); append(row, cell(primaryCell(item.dataset_id, item.description)), cell(item.locality), cell(researchAreaLabel(item.target_feature)), cell(badge(item.coverage_status)), cell(badge(item.release_state)), cell(item.release_version, "mono"), cell(formatDate(item.accepted_at)), cell(item.limitations ? technicalDetails(item.limitations, "Inspect") : "None recorded")); return row; },
      )));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  return { renderEvidenceExplorer, renderCoverage };
}

function qualityTable(items) {
  return makeTable([{ label: "Rule" }, { label: "Dimension" }, { label: "Severity" }, { label: "Outcome" }, { label: "Observed / expected" }, { label: "Message" }, { label: "Bounded sample" }], items,
    (item) => { const row = el("tr"); append(row, cell(primaryCell(item.rule_key, item.rule_version)), cell(humanise(item.dimension)), cell(badge(item.severity)), cell(badge(item.status)), cell(technicalDetails({ observed: item.observed_value_json, expected: item.expected_value_json }, "Compare")), cell(item.message || "No message recorded"), cell(item.sample_json ? technicalDetails(item.sample_json, "Inspect") : "No sample recorded")); return row; });
}

function artifactTable(items) {
  return makeTable([{ label: "Artifact" }, { label: "Type" }, { label: "Size" }, { label: "SHA-256" }, { label: "Retention" }, { label: "Created" }, { label: "Lineage" }], items,
    (item) => { const row = el("tr"); append(row, cell(primaryCell(item.logical_key, item.id)), cell(`${humanise(item.artifact_kind)} · ${item.media_type || "media type unknown"}`), cell(formatBytes(item.bytes), "numeric"), cell(String(item.content_sha256 || "Not recorded").slice(0, 24), "mono"), cell(badge(item.retention_class || "unknown")), cell(formatDate(item.created_at)), cell(technicalDetails({ ingestion_run_id: item.ingestion_run_id, task_id: item.ingestion_task_id, dataset_release_id: item.dataset_release_id }, "Inspect"))); return row; });
}

function problemSuffix(error) {
  return error?.requestId ? ` Request ID ${error.requestId}.` : "";
}
