import { collection } from "../core/api.js";
import { append, el, link } from "../core/dom.js";
import { formatDate, humanise, isInternalAssessmentFixture, statusTone } from "../core/formats.js?v=6";
import { ACTIVE_RUN_STATES } from "../core/polling.js";
import { badge, pageHeading, panel } from "../components/layout.js";
import { cell, makeTable } from "../components/tables.js";
import { emptyState, renderLoading } from "../components/states.js";

export async function renderOverview({ view, request }) {
  renderLoading(view, "Loading operations overview");
  const results = await Promise.allSettled([
    request("sources?limit=100"), request("ingestion-runs?limit=25"), request("dataset-releases?limit=100"), request("overview"),
  ]);
  const sources = results[0].status === "fulfilled" ? collection(results[0].value.body).filter((item) => !isInternalAssessmentFixture(item)) : [];
  const runs = results[1].status === "fulfilled" ? collection(results[1].value.body) : [];
  const releases = results[2].status === "fulfilled" ? collection(results[2].value.body).filter((item) => !isInternalAssessmentFixture(item)) : [];
  const coverage = releases.filter((release) => release.status === "accepted").map((release) => ({
    dataset: release.dataset_id,
    locality: release.coverage_json?.locality || release.coverage_json?.state || "NSW",
    status: release.coverage_json?.complete === false ? "partial" : "accepted",
  }));
  const failures = results.filter((result) => result.status === "rejected");
  view.replaceChildren();
  append(view, pageHeading("Property records", "Data operations overview", "Manage the sources and processing work that keep NSW property records current, checked and ready for research.", [link("Browse import jobs", "#jobs", "button primary"), link("Register a source", "#sources", "button secondary")]));
  if (failures.length) append(view, el("div", "notice warning", `${failures.length} supporting feed${failures.length === 1 ? " is" : "s are"} temporarily unavailable. The information that could be loaded is still shown below.`));
  const active = runs.filter((run) => ACTIVE_RUN_STATES.has(String(run.status).toLowerCase())).length;
  const latestByJob = [];
  const seenJobs = new Set();
  for (const run of runs) {
    const jobKey = run.job_definition_id || run.job_name;
    if (!jobKey || seenJobs.has(jobKey)) continue;
    seenJobs.add(jobKey);
    latestByJob.push(run);
  }
  const failed = latestByJob.filter((run) => ["failed", "interrupted"].includes(String(run.status).toLowerCase())).length;
  const stale = releases.filter((release) => ["stale", "expired"].includes(String(release.freshness_status || release.status).toLowerCase())).length;
  const accepted = releases.filter((release) => String(release.status).toLowerCase() === "accepted").length;
  const stats = el("section", "stat-grid");
  stats.setAttribute("aria-label", "Data readiness summary");
  for (const [label, value, note, tone] of [
    ["Processing now", active, "Imports currently running", "info"],
    ["Needs attention", failed, "Failed runs to review", failed ? "negative" : "neutral"],
    ["Stale datasets", stale, "Published data past its freshness window", stale ? "warning" : "neutral"],
    ["Published datasets", accepted, "Available to property research", "positive"],
  ]) {
    const card = el("article", `stat-card ${tone}`);
    append(card, el("span", "stat-label", label), el("strong", "stat-value", value), el("span", "stat-note", note));
    append(stats, card);
  }
  append(view, stats);

  const latestFailure = latestByJob.find((run) => ["failed", "interrupted"].includes(String(run.status).toLowerCase()));
  if (latestFailure) {
    const alert = el("div", "notice negative notice-actions");
    const copy = el("div");
    append(copy, el("strong", "", "A recent data update needs review"), el("div", "", `${latestFailure.job_name || "Processing run"} failed. Published data remains available while the failed run is investigated.`));
    append(alert, copy, link("Review run", `#runs/${latestFailure.id}`, "button secondary small"));
    append(view, alert);
  }

  const grid = el("div", "dashboard-grid");
  const recentBody = runs.length ? makeTable(
    [{ label: "Run" }, { label: "Mode" }, { label: "Status" }, { label: "Requested" }], runs.slice(0, 8),
    (run) => {
      const row = el("tr");
      append(row, cell(link(run.job_name || `Run ${String(run.id).slice(0, 8)}`, `#runs/${run.id}`), "primary-cell"), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatDate(run.requested_at || run.created_at)));
      return row;
    },
    "Recent ingestion runs",
  ) : emptyState("No processing runs yet", "Open an import job to preview and start a bounded data update.", link("Open import jobs", "#jobs", "button secondary"));

  const freshness = el("div", "stack");
  const sourceBody = el("div");
  if (!sources.length) append(sourceBody, el("p", "", "No source definitions are currently available."));
  for (const source of sources.slice(0, 6)) {
    const item = el("div", "coverage-card");
    const release = releases.find((candidate) => candidate.source_definition_id === source.id && candidate.status === "accepted");
    item.classList.add(statusTone(release?.freshness_status || (release ? "accepted" : "unavailable")));
    append(item, el("strong", "", source.name), el("span", "", release ? `${release.release_version} · published ${formatDate(release.accepted_at)}` : "No published dataset"));
    append(sourceBody, item);
  }
  const coverageBody = el("div", "coverage-grid");
  for (const item of coverage.slice(0, 6)) {
    const card = el("div", `coverage-card ${statusTone(item.status)}`);
    append(card, el("strong", "", item.locality || item.area || "NSW"), el("span", "", `${item.dataset || item.dataset_id || "Dataset"} · ${humanise(item.status)}`));
    append(coverageBody, card);
  }
  if (!coverage.length) append(coverageBody, el("p", "", "Coverage evidence is not available from this deployment."));
  append(freshness, panel("Latest published data", "Current dataset for each registered source", sourceBody), panel("NSW coverage", "Geography represented by published datasets", coverageBody));
  append(grid, panel("Recent processing runs", "Data update history", recentBody, link("View all runs", "#runs")), freshness);
  append(view, grid);
}
