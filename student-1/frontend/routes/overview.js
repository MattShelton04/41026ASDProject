import { collection } from "../core/api.js";
import { append, el, link } from "../core/dom.js";
import { displayName, formatDate, humanise, statusTone } from "../core/formats.js?v=18";
import { ACTIVE_RUN_STATES } from "../core/polling.js";
import { badge, pageHeading, panel } from "../components/layout.js?v=17";
import { icon, withIcon } from "../components/icons.js?v=1";
import { cell, makeTable } from "../components/tables.js?v=18";
import { emptyState, errorState, renderLoading } from "../components/states.js";

const OVERVIEW_FEED_LABELS = ["Source definitions", "Update history", "Published data"];

export function projectOverviewFeeds(results) {
  const values = results.map((result) => result.status === "fulfilled" ? collection(result.value.body) : null);
  const failures = results.flatMap((result, index) => result.status === "rejected"
    ? [{ label: OVERVIEW_FEED_LABELS[index], error: result.reason }]
    : []);
  return {
    sources: values[0],
    runs: values[1],
    releases: values[2],
    failures,
    allUnavailable: failures.length === OVERVIEW_FEED_LABELS.length,
  };
}

export async function renderOverview({ view, request, generationGuard, rerender }) {
  const routeEpoch = generationGuard.capture();
  renderLoading(view, "Loading operations overview");
  const results = await Promise.allSettled([
    request("sources?limit=100"), request("ingestion-runs?limit=25"), request("dataset-releases?limit=100"),
  ]);
  if (!routeEpoch.isCurrent()) return;
  const feeds = projectOverviewFeeds(results);
  if (feeds.allUnavailable) {
    view.replaceChildren(errorState(feeds.failures[0].error, rerender));
    return;
  }
  const sourcesAvailable = feeds.sources !== null;
  const runsAvailable = feeds.runs !== null;
  const releasesAvailable = feeds.releases !== null;
  const sources = (feeds.sources || []).filter((item) => item.status !== "retired");
  const runs = feeds.runs || [];
  const releases = feeds.releases || [];
  const coverage = releases.filter((release) => release.status === "accepted").map((release) => ({
    dataset: release.dataset_id,
    locality: release.coverage_json?.locality || release.coverage_json?.state || "NSW",
    status: release.coverage_json?.complete === false ? "partial" : "accepted",
  }));
  view.replaceChildren();
  append(view, pageHeading("Property data", "Data overview", "Check whether property data is current and review recent updates.", [withIcon(link("View data updates", "#jobs", "button primary overview-action"), "updates"), withIcon(link("Manage sources", "#sources", "button secondary overview-action"), "settings")]));
  if (feeds.failures.length) append(view, el("div", "notice warning", `Temporarily unavailable: ${feeds.failures.map((failure) => failure.label).join(" and ")}. Information from the remaining services is still shown below.`));
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
  for (const [label, value, note, tone, iconName] of [
    ["Updating now", runsAvailable ? active : "Unavailable", runsAvailable ? "Data updates in progress" : "Update history could not be checked", runsAvailable ? "info" : "warning", "refresh"],
    ["Update problems", runsAvailable ? failed : "Unavailable", runsAvailable ? "Latest updates that need review" : "Update problems could not be checked", runsAvailable && failed ? "negative" : runsAvailable ? "neutral" : "warning", "alert"],
    ["Out-of-date data", releasesAvailable ? stale : "Unavailable", releasesAvailable ? "Published sources past their review date" : "Published freshness could not be checked", releasesAvailable && stale ? "warning" : "neutral", "history"],
    ["Published sources", releasesAvailable ? accepted : "Unavailable", releasesAvailable ? "Available in property research" : "Published data could not be checked", releasesAvailable ? "positive" : "warning", "file"],
  ]) {
    const card = el("article", `stat-card ${tone}`);
    const copy = el("div", "stat-copy");
    append(copy, el("span", "stat-label", label), el("strong", "stat-value", value), el("span", "stat-note", note));
    append(card, icon(iconName, "stat-icon"), copy);
    append(stats, card);
  }
  append(view, stats);

  const problemRuns = latestByJob.filter((run) => ["failed", "interrupted"].includes(String(run.status).toLowerCase()));
  if (problemRuns.length) {
    const alert = el("div", "notice negative notice-actions");
    const copy = el("div");
    append(copy,
      el("strong", "", `${problemRuns.length} data ${problemRuns.length === 1 ? "update needs" : "updates need"} attention`),
      el("div", "", "These updates did not finish successfully. The current published versions remain in use."),
    );
    const problemLinks = el("div", "problem-links");
    for (const run of problemRuns.slice(0, 3)) {
      append(problemLinks, link(`${displayName(run.job_name || "Data update")} · ${humanise(run.status)}`, `#runs/${run.id}`));
    }
    append(copy, problemLinks);
    append(alert, copy, link(problemRuns.length === 1 ? "Review problem" : "Review problems", "#runs", "button secondary small"));
    append(view, alert);
  }

  const grid = el("div", "dashboard-grid");
  const recentBody = !runsAvailable ? el("div", "notice warning", "Update history is temporarily unavailable. Published data and source information remain unchanged.") : runs.length ? makeTable(
    [{ label: "Update" }, { label: "Method" }, { label: "Status" }, { label: "Started" }], runs.slice(0, 8),
    (run) => {
      const row = el("tr");
      append(row, cell(link(displayName(run.job_name || `Update ${String(run.id).slice(0, 8)}`), `#runs/${run.id}`), "primary-cell"), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatDate(run.requested_at || run.created_at)));
      return row;
    },
    "Recent data updates", { responsive: true },
  ) : emptyState("No updates yet", "Choose a saved data update to preview and start it.", link("View data updates", "#jobs", "button secondary"));

  const freshness = el("div", "stack");
  const sourceBody = el("div");
  if (!sourcesAvailable) append(sourceBody, el("div", "notice warning", "Source definitions are temporarily unavailable. No source has been removed or changed."));
  else if (!sources.length) append(sourceBody, el("p", "", "No source definitions are currently available."));
  for (const source of sources.slice(0, 6)) {
    const item = el("div", "coverage-card");
    const release = releases.find((candidate) => candidate.source_definition_id === source.id && candidate.status === "accepted");
    item.classList.add(statusTone(release?.freshness_status || (release ? "accepted" : "unavailable")));
    const publication = !releasesAvailable ? "Publication status unavailable" : release ? `${release.release_version} · published ${formatDate(release.accepted_at)}` : "No published data";
    append(item, el("strong", "", displayName(source.name)), el("span", "", publication));
    append(sourceBody, item);
  }
  const coverageBody = el("div", "coverage-grid");
  for (const item of coverage.slice(0, 6)) {
    const card = el("div", `coverage-card ${statusTone(item.status)}`);
    append(card, el("strong", "", item.locality || item.area || "NSW"), el("span", "", `${displayName(item.dataset || item.dataset_id || "Dataset")} · ${humanise(item.status)}`));
    append(coverageBody, card);
  }
  if (!releasesAvailable) append(coverageBody, el("div", "notice warning", "Published coverage is temporarily unavailable. No coverage record has been changed."));
  else if (!coverage.length) append(coverageBody, el("p", "", "Coverage evidence is not available from this deployment."));
  append(freshness, panel("Current published data", "Latest version available from each source", sourceBody), panel("NSW coverage", "Areas represented in published data", coverageBody));
  append(grid, panel("Recent updates", "Latest data processing activity", recentBody, link("View update history", "#runs")), freshness);
  append(view, grid);
}
