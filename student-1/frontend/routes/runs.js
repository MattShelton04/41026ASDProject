import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { displayName, durationMilliseconds, formatBytes, formatDate, formatDuration, formatNumber, humanise, stateLabel, statusTone } from "../core/formats.js?v=19";
import { actionAvailability, createLatestRequestGuard, nextPollDelay, retainRecent } from "../core/polling.js?v=18";
import { parseRoute, routeQuery } from "../core/router.js";
import { filterToolbar } from "../components/forms.js?v=17";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js?v=17";
import { emptyState, errorState, renderLoading } from "../components/states.js";
import { cell, makeTable, primaryCell, technicalReference } from "../components/tables.js?v=18";

const RUN_FILTERS = ["", "requested", "queued", "running", "succeeded", "failed", "cancelled", "interrupted"];

function runTimeline(tasks, { available = true } = {}) {
  const list = el("ol", "timeline");
  if (!tasks.length) append(list, el("li", "", available
    ? "No task ledger is available yet."
    : "No update-step details can be shown until this feed recovers."));
  for (const task of tasks) {
    const item = el("li");
    const tone = statusTone(task.status);
    const marker = el("span", `timeline-marker ${tone}`, stateLabel(task.status).symbol);
    const detail = el("div");
    const durableRows = Math.max(Number(task.rows_out || 0), Number(task.progress_rows || 0));
    const phase = task.progress_phase ? ` · ${task.progress_phase}` : "";
    const finished = task.finished_at || Date.now();
    const elapsed = task.started_at ? formatDuration(task.started_at, finished) : "not started";
    const rowTotal = task.progress_total_rows == null ? null : Number(task.progress_total_rows);
    const byteTotal = task.progress_total_bytes == null ? null : Number(task.progress_total_bytes);
    const usesRows = Number.isFinite(rowTotal) && rowTotal > 0;
    const processed = usesRows ? durableRows : Number(task.progress_bytes || 0);
    const total = usesRows ? rowTotal : byteTotal;
    const unitProgress = usesRows
      ? `${formatNumber(processed)} of ${formatNumber(total)} rows`
      : Number.isFinite(total) && total > 0
        ? `${formatBytes(processed)} of ${formatBytes(total)}`
        : `${formatNumber(durableRows)} rows · total not yet known`;
    const progressRatio = Number.isFinite(total) && total > 0
      ? Math.max(0, Math.min(1, processed / total))
      : null;
    const elapsedMs = task.started_at ? durationMilliseconds(task.started_at, finished) : null;
    const remainingMs = task.status === "running" && progressRatio > 0 && progressRatio < 1
      && elapsedMs >= 10_000 ? elapsedMs * ((1 - progressRatio) / progressRatio) : null;
    const timing = task.started_at
      ? task.finished_at
        ? `took ${elapsed}`
        : `${elapsed} elapsed${remainingMs === null ? "" : ` · about ${formatDuration(0, remainingMs)} remaining`}`
      : task.status === "skipped"
        ? "not run (cached result reused)"
        : "not started";
    append(detail,
      el("h3", "", `${humanise(task.stage)} · ${task.logical_key || "Task"}`),
      el("p", "", `${humanise(task.status)}${phase} · attempt ${task.attempt_number ?? 1}`),
      el("span", "timeline-meta", `${unitProgress}${progressRatio === null ? "" : ` (${Math.round(progressRatio * 100)}%)`} · ${timing}`),
    );
    if (task.status === "running" && progressRatio !== null) {
      const bar = el("progress", "timeline-progress");
      bar.max = 1;
      bar.value = progressRatio;
      bar.setAttribute("aria-label", `${humanise(task.stage)} ${Math.round(progressRatio * 100)}% complete`);
      append(detail, bar);
    }
    if (task.error_json) append(detail, technicalDetails(task.error_json, "Failure details"));
    append(item, marker, detail);
    append(list, item);
  }
  return list;
}

function requestSuffix(error) {
  return error?.requestId ? ` Request ID ${error.requestId}.` : "";
}

function resolveFeed(result, cache, key) {
  if (result.status === "fulfilled") {
    const items = collection(result.value.body);
    cache[key] = items;
    return { items, available: true, cached: false, error: null };
  }
  const cached = Object.hasOwn(cache, key);
  return { items: cached ? cache[key] : [], available: false, cached, error: result.reason };
}

function feedWarning(label, feed) {
  if (feed.available) return null;
  const copy = feed.cached
    ? `${label} are temporarily unavailable. Showing the last loaded details.`
    : `${label} are temporarily unavailable. No previously loaded details are available.`;
  return el("div", "notice warning", `${copy}${requestSuffix(feed.error)}`);
}

function annotateRefreshState(root) {
  const detailKeys = new Map();
  for (const details of root.querySelectorAll("details")) {
    const label = details.querySelector("summary")?.textContent?.trim() || "Details";
    const count = detailKeys.get(label) || 0;
    detailKeys.set(label, count + 1);
    details.dataset.refreshKey = `details:${label}:${count}`;
  }
  const focusKeys = new Map();
  for (const target of root.querySelectorAll("a[href], button, summary")) {
    const base = target.matches("a[href]")
      ? `link:${target.getAttribute("href")}`
      : target.matches("summary")
        ? target.closest("details")?.dataset.refreshKey || `summary:${target.textContent?.trim()}`
        : `button:${target.textContent?.trim()}`;
    const count = focusKeys.get(base) || 0;
    focusKeys.set(base, count + 1);
    target.dataset.refreshFocusKey = `${base}:${count}`;
  }
}

function captureRefreshState(root) {
  const active = document.activeElement;
  return {
    scrollTop: window.scrollY,
    focusKey: root.contains(active) ? active.dataset.refreshFocusKey || "" : "",
    disclosures: new Map(
      [...root.querySelectorAll("details[data-refresh-key]")]
        .map((details) => [details.dataset.refreshKey, details.open]),
    ),
  };
}

function restoreRefreshState(root, snapshot) {
  for (const details of root.querySelectorAll("details[data-refresh-key]")) {
    if (snapshot.disclosures.has(details.dataset.refreshKey)) {
      details.open = snapshot.disclosures.get(details.dataset.refreshKey);
    }
  }
  if (snapshot.focusKey) {
    const target = [...root.querySelectorAll("[data-refresh-focus-key]")]
      .find((candidate) => candidate.dataset.refreshFocusKey === snapshot.focusKey);
    target?.focus({ preventScroll: true });
  }
  window.scrollTo({ top: snapshot.scrollTop });
}

export function createRunRoutes({ view, request, mutate, confirmAction, announce, state, generationGuard, rerender }) {
  const refreshGuard = createLatestRequestGuard();
  const feedCache = new Map();
  let pollFailures = 0;

  async function renderRuns() {
    const params = routeQuery(location.hash);
    const filters = { q: params.get("q") || "", status: params.get("status") || "", job: params.get("job") || "" };
    renderLoading(view, "Loading run history");
    try {
      const { body } = await request(`ingestion-runs${queryString({ status: filters.status, limit: 100 })}`);
      const allRuns = collection(body);
      const search = filters.q.toLowerCase();
      const runs = allRuns.filter((run) => (!filters.job || run.job_definition_id === filters.job)
        && (!search || [run.id, run.job_name, run.request_id, run.dataset_id].some((value) => String(value || "").toLowerCase().includes(search))));
      view.replaceChildren();
      append(view, pageHeading("Property data", "Update history", "Track each data update from download through checks and publication review.", [link("Choose a data update", "#jobs", "button primary")]));
      if (filters.job) {
        const jobFilter = el("div", "notice notice-actions");
        const filterCopy = el("span");
        append(filterCopy, document.createTextNode("Showing history for data update "), technicalReference(filters.job), document.createTextNode("."));
        append(jobFilter, filterCopy, link("Clear job filter", "#runs", "button secondary small"));
        append(view, jobFilter);
      }
      append(view, filterToolbar({ search: filters.q, status: filters.status, statuses: RUN_FILTERS, placeholder: "Update name or reference", onApply: (values) => { location.hash = `#runs${queryString({ ...values, job: filters.job })}`; } }));
      if (!runs.length) { append(view, emptyState("No updates found", "Start a saved data update or adjust the current filters.", link("View data updates", "#jobs", "button primary"))); return; }
      const table = makeTable([{ label: "Update" }, { label: "Method" }, { label: "Status" }, { label: "Rows loaded" }, { label: "Started" }, { label: "Reference" }], runs, (run) => {
        const row = el("tr");
        const runLink = link(displayName(run.job_name || `Update ${String(run.id).slice(0, 8)}`), `#runs/${encodeURIComponent(run.id)}`);
        append(row, cell(primaryCell(runLink, displayName(run.dataset_id || run.run_mode))), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatNumber(run.rows_accepted), "numeric"), cell(formatDate(run.requested_at)), cell(technicalReference(run.request_id)));
        return row;
      }, "Data update history", { responsive: true });
      append(view, panel(`${runs.length} ${runs.length === 1 ? "update" : "updates"}`, "Newest first", table));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  async function renderRunDetail(id, { polling = false } = {}) {
    const refresh = refreshGuard.next();
    const routeGeneration = generationGuard.current();
    const isCurrent = () => refreshGuard.isCurrent(refresh)
      && generationGuard.isCurrent(routeGeneration)
      && parseRoute(location.hash).route === "runs"
      && parseRoute(location.hash).id === id;
    clearTimeout(state.pollTimer);
    if (!polling) renderLoading(view, "Loading run evidence");
    else {
      view.setAttribute("aria-busy", "true");
      const status = view.querySelector("[data-run-refresh-status]");
      if (status) status.textContent = "Refreshing update status…";
    }
    try {
      const supportingFeeds = Promise.allSettled([
        request(`ingestion-runs/${id}/tasks?limit=100`), request(`ingestion-runs/${id}/quality-results?limit=100`), request(`ingestion-runs/${id}/artifacts?limit=100`),
        request(`dataset-releases?ingestion_run_id=${encodeURIComponent(id)}&limit=100`),
      ]);
      const detailResult = await request(`ingestion-runs/${id}`);
      if (!isCurrent()) return;
      const [tasksResult, qualityResult, artifactsResult, releasesResult] = await supportingFeeds;
      if (!isCurrent()) return;
      const cache = retainRecent(feedCache, id, feedCache.get(id) || {});
      const tasksFeed = resolveFeed(tasksResult, cache, "tasks");
      const qualityFeed = resolveFeed(qualityResult, cache, "quality");
      const artifactsFeed = resolveFeed(artifactsResult, cache, "artifacts");
      const releasesFeed = resolveFeed(releasesResult, cache, "releases");
      const tasks = tasksFeed.items;
      const quality = qualityFeed.items;
      const artifacts = artifactsFeed.items;
      const linkedRelease = releasesFeed.items.find((release) => release.ingestion_run_id === id && !["accepted", "superseded"].includes(release.status));
      const refreshState = polling ? captureRefreshState(view) : null;
      const run = entity(detailResult.body, "run");
      view.replaceChildren();
      const availability = actionAvailability(run.status);
      const actions = [];
      const runAction = (key, label, description, tone = "secondary") => actions.push(button(label, `button ${tone}`, async () => {
        let created = null;
        const confirmed = await confirmAction({
          title: `${label} this run?`,
          description,
          label,
          tone: tone === "secondary" ? "primary" : tone,
          progressLabel: `${label.replace(/ update$/, "")}…`,
          onConfirm: async () => { created = await mutate(`ingestion-runs/${id}/${key}`, { success: `${label} requested` }); },
        });
        if (!confirmed) return;
        const child = entity(created, "run");
        if (child?.id && child.id !== id) location.hash = `#runs/${child.id}`;
        else renderRunDetail(id);
      }));
      if (availability.resume) runAction("resume", "Resume update", "Continue this interrupted update from its last saved step.");
      if (availability.retry) runAction("retry", "Retry update", "Start the full update again while keeping this failed attempt in the history.");
      if (availability.reprocess) runAction("reprocess-cached", "Use downloaded file", "Start again with the already downloaded and verified file.");
      if (availability.cancel) runAction("cancel", "Cancel update", "Stop the update. Completed steps will remain in its history.", "danger");
      if (availability.diagnose) {
        const failed = run.status === "failed";
        actions.push(button(
          failed ? "Explain this failure" : "Ask AI about update",
          `button ${failed ? "primary" : "secondary"}`,
          () => { location.hash = `#assistant?route=runs/detail&ingestion_run_id=${encodeURIComponent(id)}`; },
        ));
        if (linkedRelease) {
          actions.push(button("Review candidate data", "button secondary", () => {
            location.hash = `#ai/release:${linkedRelease.id}?goal=${failed ? "quality" : "compare"}`;
          }));
        }
      }
      append(view, pageHeading("Data update", displayName(run.job_name || `Update ${String(id).slice(0, 8)}`), `${humanise(run.run_mode)} · started ${formatDate(run.requested_at)}`, actions));
      const refreshStatus = el("p", "run-refresh-status", nextPollDelay(run.status) !== null
        ? "Refreshed just now · updates automatically while this update is active"
        : "Refreshed just now · latest saved status");
      refreshStatus.dataset.runRefreshStatus = "";
      append(view, refreshStatus);
      const releaseWarning = feedWarning("Published-version details", releasesFeed);
      if (releaseWarning) append(view, releaseWarning);
      if (run.error_json) append(view, el("div", "notice negative", `${run.error_json.message || run.error_json.detail || "The run recorded a classified failure."} The previously accepted release remains unchanged.`));
      const metrics = el("div", "metric-strip");
      for (const [label, value] of [["Found", formatNumber(run.rows_discovered)], ["Prepared", formatNumber(run.rows_staged)], ["Loaded", formatNumber(run.rows_accepted)], ["Rejected", formatNumber(run.rows_rejected)]]) {
        const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(metrics, metric);
      }
      append(view, metrics);
      const grid = el("div", "dashboard-grid");
      const runBody = el("div");
      const tasksWarning = feedWarning("Update steps", tasksFeed);
      if (tasksWarning) append(runBody, tasksWarning);
      append(runBody, runTimeline(tasks, { available: tasksFeed.available || tasksFeed.cached }));
      const evidence = el("div", "stack");
      const evidenceAvailability = el("div");
      const qualityWarning = feedWarning("Data checks", qualityFeed);
      const artifactsWarning = feedWarning("File and lineage details", artifactsFeed);
      if (qualityWarning) append(evidenceAvailability, qualityWarning);
      if (artifactsWarning) append(evidenceAvailability, artifactsWarning);
      append(evidence,
        panel("Update status", "Current state", detailList([["Status", badge(run.status)], ["Last activity", formatDate(run.last_activity_at || run.finished_at || run.heartbeat_at)], ["Attempt", run.attempt_number], ["Previous update", run.parent_run_id ? link(String(run.parent_run_id), `#runs/${run.parent_run_id}`) : "None"], ["Reference", el("code", "mono", run.request_id || detailResult.requestId)], ["Finished", formatDate(run.finished_at)]])),
        panel("Saved progress", "Technical checkpoints used if the update must resume", detailList([["Input checkpoint", JSON.stringify(run.input_checkpoint_json || {})], ["Candidate checkpoint", JSON.stringify(run.output_checkpoint_json || {})], ["Published watermark", JSON.stringify(run.accepted_watermark_json || {})]])),
        panel("Checks and files", "Specialist details for this update", el("div", "stack", "")),
      );
      const evidencePanelBody = evidence.lastElementChild.querySelector(".panel-body");
      append(evidencePanelBody, evidenceAvailability, detailList([
        ["Quality checks", link(qualityFeed.available || qualityFeed.cached ? `${quality.length} results` : "Open details", `#quality/${id}`)],
        ["Files and lineage", link(artifactsFeed.available || artifactsFeed.cached ? `${artifacts.length} records` : "Open details", `#artifacts/${id}`)],
      ]));
      const timelineSubtitle = tasksFeed.available
        ? `${tasks.length} recorded steps`
        : tasksFeed.cached ? `${tasks.length} recorded steps · last loaded` : "Steps temporarily unavailable";
      append(grid, panel("Update timeline", timelineSubtitle, runBody), evidence);
      append(view, grid);
      append(view, panel("Technical run details", "Expandable record for troubleshooting and audit", technicalDetails(detailResult.body)));
      annotateRefreshState(view);
      if (refreshState) restoreRefreshState(view, refreshState);
      const statusChanged = state.lastRunStatus && state.lastRunStatus !== run.status;
      if (statusChanged) announce(`Run status changed to ${humanise(run.status)}.`);
      state.lastRunStatus = run.status;
      pollFailures = 0;
      view.setAttribute("aria-busy", "false");
      scheduleRunPoll(id, run.status);
    } catch (error) {
      if (!isCurrent()) return;
      if (!polling) view.replaceChildren(errorState(error, () => renderRunDetail(id)));
      else {
        pollFailures += 1;
        const status = view.querySelector("[data-run-refresh-status]");
        if (status) status.textContent = "Refresh delayed · retrying automatically";
        view.setAttribute("aria-busy", "false");
        scheduleRunPoll(id, state.lastRunStatus, pollFailures);
      }
    }
  }

  function scheduleRunPoll(id, status, failures = 0) {
    clearTimeout(state.pollTimer);
    const delay = nextPollDelay(status, failures, document.hidden);
    if (delay === null) return;
    const generation = generationGuard.current();
    state.pollTimer = setTimeout(() => {
      const current = parseRoute(location.hash);
      if (generationGuard.isCurrent(generation) && current.route === "runs" && current.id === id) renderRunDetail(id, { polling: true });
    }, delay);
  }

  return { renderRuns, renderRunDetail };
}
