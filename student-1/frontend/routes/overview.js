import { collection } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatDate, humanise, statusTone } from "../core/formats.js";
import { ACTIVE_RUN_STATES } from "../core/polling.js";
import { badge, pageHeading, panel } from "../components/layout.js";
import { cell, makeTable } from "../components/tables.js";
import { emptyState, renderLoading } from "../components/states.js";

export async function renderOverview({ view, request }) {
  renderLoading(view, "Loading operations overview");
  const results = await Promise.allSettled([
    request("sources?limit=100"), request("ingestion-runs?limit=25"), request("dataset-releases?limit=100"), request("overview"),
  ]);
  const sources = results[0].status === "fulfilled" ? collection(results[0].value.body) : [];
  const runs = results[1].status === "fulfilled" ? collection(results[1].value.body) : [];
  const releases = results[2].status === "fulfilled" ? collection(results[2].value.body) : [];
  const coverage = releases.filter((release) => release.status === "accepted").map((release) => ({
    dataset: release.dataset_id,
    locality: release.coverage_json?.locality || release.coverage_json?.state || "NSW",
    status: release.coverage_json?.complete === false ? "partial" : "accepted",
  }));
  const failures = results.filter((result) => result.status === "rejected");
  view.replaceChildren();
  append(view, pageHeading("Feature 1 · Data platform", "Data operations overview", "See accepted data, failed candidates and work requiring review without confusing service health with evidence readiness.", [button("Plan a run", "button primary", () => { location.hash = "#jobs"; })]));
  if (failures.length) append(view, el("div", "notice warning", `${failures.length} overview feed${failures.length === 1 ? " is" : "s are"} unavailable. Available evidence is shown below; direct property search remains independent.`));
  const active = runs.filter((run) => ACTIVE_RUN_STATES.has(String(run.status).toLowerCase())).length;
  const failed = runs.filter((run) => String(run.status).toLowerCase() === "failed").length;
  const stale = releases.filter((release) => ["stale", "expired"].includes(String(release.freshness_status || release.status).toLowerCase())).length;
  const accepted = releases.filter((release) => String(release.status).toLowerCase() === "accepted").length;
  const stats = el("section", "stat-grid");
  stats.setAttribute("aria-label", "Data readiness summary");
  for (const [label, value, note, tone] of [
    ["Active runs", active, "Currently progressing", "info"],
    ["Failed runs", failed, "Requires evidence review", failed ? "negative" : "neutral"],
    ["Stale releases", stale, "Freshness, not service health", stale ? "warning" : "neutral"],
    ["Accepted releases", accepted, "Available to consumers", "positive"],
  ]) {
    const card = el("article", `stat-card ${tone}`);
    append(card, el("span", "stat-label", label), el("strong", "stat-value", value), el("span", "stat-note", note));
    append(stats, card);
  }
  append(view, stats);

  const grid = el("div", "dashboard-grid");
  const recentBody = runs.length ? makeTable(
    [{ label: "Run" }, { label: "Mode" }, { label: "Status" }, { label: "Requested" }], runs.slice(0, 8),
    (run) => {
      const row = el("tr");
      append(row, cell(link(run.job_name || `Run ${String(run.id).slice(0, 8)}`, `#runs/${run.id}`), "primary-cell"), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatDate(run.requested_at || run.created_at)));
      return row;
    },
    "Recent ingestion runs",
  ) : emptyState("No runs yet", "Activate a bounded job, preview its plan and launch the first fixture run.", link("Open jobs", "#jobs", "button secondary"));

  const freshness = el("div", "stack");
  const sourceBody = el("div");
  if (!sources.length) append(sourceBody, el("p", "", "No source definitions are currently available."));
  for (const source of sources.slice(0, 6)) {
    const item = el("div", "coverage-card");
    const release = releases.find((candidate) => candidate.source_definition_id === source.id && candidate.status === "accepted");
    item.classList.add(statusTone(release?.freshness_status || (release ? "accepted" : "unavailable")));
    append(item, el("strong", "", source.name), el("span", "", release ? `${release.release_version} · ${formatDate(release.accepted_at)}` : "No accepted release"));
    append(sourceBody, item);
  }
  const coverageBody = el("div", "coverage-grid");
  for (const item of coverage.slice(0, 6)) {
    const card = el("div", `coverage-card ${statusTone(item.status)}`);
    append(card, el("strong", "", item.locality || item.area || "NSW"), el("span", "", `${item.dataset || item.dataset_id || "Dataset"} · ${humanise(item.status)}`));
    append(coverageBody, card);
  }
  if (!coverage.length) append(coverageBody, el("p", "", "Coverage evidence is not available from this deployment."));
  append(freshness, panel("Source freshness", "Accepted evidence by source", sourceBody), panel("Supported coverage", "Geography and dataset availability", coverageBody));
  append(grid, panel("Recent ingestion runs", "Durable execution history", recentBody, link("View all", "#runs")), freshness);
  append(view, grid);
}
