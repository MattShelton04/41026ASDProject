import { collection, entity, queryString, requestIdSuffix } from "../core/api.js";
import { disposeTableRegions } from "../browser/index.js";
import { collectionPagination, pageOffset } from "../components/pagination.js";
import { append, button, el, link } from "../core/dom.js";
import { displayName, formatBytes, formatDate, formatDuration, formatNumber, humanise, stateLabel, statusTone } from "../core/formats.js";
import { actionAvailability, createLatestRequestGuard, nextRunDetailPollDelay, retainRecent } from "../core/polling.js";
import { parseRoute, routeQuery } from "../core/router.js";
import { failureExplanationDraft, reconcileTimelineTask, runFailureSummary } from "../core/run-failure.js";
import { mergeActivity, taskProgress } from "../core/run-progress.js";
import { runActivity } from "../components/run-activity.js";
import { filterToolbar } from "../components/forms.js";
import { badge, detailList, disclosurePanel, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState, renderLoading } from "../components/states.js";
import { cell, makeTable, primaryCell, technicalReference } from "../components/tables.js";

const RUN_FILTERS = ["", "queued", "running", "succeeded", "failed", "cancelled", "interrupted"];

function activeStageCard(run, tasks) {
  if (!actionAvailability(run.status).cancel && run.status !== "cancelling") return null;
  const task = tasks.map((item) => reconcileTimelineTask(run, item)).find((item) => ["running", "claimed"].includes(item.status));
  const card = el("section", "run-stage-card");
  card.setAttribute("aria-label", "Current update stage");
  const pulse = el("span", "run-stage-pulse"); pulse.setAttribute("aria-hidden", "true");
  append(card, pulse);
  if (!task) {
    append(card, el("h2", "", "Waiting for the acquisition worker"), el("p", "", "Updates share one serial worker. A full-history update ahead of this one can take several minutes. This page updates automatically."));
    return card;
  }
  const progress = taskProgress(task);
  card.classList.toggle("is-stale", progress.stale);
  const awaitingLoader = task.stage === "import" && ["planned", "queued", "interrupted"].includes(task.import_status);
  const phase = awaitingLoader ? "Waiting for the database loader" : humanise(task.progress_phase || task.stage);
  append(card, el("p", "eyebrow", `Attempt ${task.attempt_number || 1} · ${humanise(task.stage)}`), el("h2", "", phase));
  const metrics = el("div", "run-stage-metrics");
  const rowsLabel = task.stage === "acquire" ? "Source records prepared" : task.stage === "build_release" ? "Release records exported" : task.progress_phase_key === "typed_staging" ? "Canonical rows copied" : "Canonical rows staged";
  append(metrics, el("strong", "", `${formatNumber(progress.rows)} ${rowsLabel.toLowerCase()}`));
  if (progress.bytes > 0) append(metrics, el("span", "", `${formatBytes(progress.bytes)} read`));
  append(metrics, el("span", "", progress.elapsed === null ? "Starting" : `${formatDuration(0, progress.elapsed)} this attempt`));
  append(card, metrics);
  if (awaitingLoader) append(card, el("p", "", "The canonical file is ready. Another import or publication may own the serial database loader; this stage has not started loading yet."));
  else if (task.import_started_at) append(card, el("p", "", `Loader preparation and queue wait: ${formatDuration(task.started_at, task.import_started_at)}. Current loader attempt started ${formatDate(task.import_started_at)}.`));
  if (progress.ratio !== null) {
    const bar = el("progress", "run-stage-progress"); bar.max = 1; bar.value = progress.ratio;
    bar.setAttribute("aria-label", `${humanise(task.stage)} progress`);
    append(card, bar, el("p", "", progress.usesRows ? `${formatNumber(progress.rows)} of ${formatNumber(progress.total)} rows` : `${formatBytes(progress.bytes)} of ${formatBytes(progress.total)}`));
  } else append(card, el("p", "", "The source does not provide a reliable total for this phase. No completion estimate is available."));
  const heartbeat = progress.heartbeatAge === null ? "No heartbeat recorded yet" : `Worker heartbeat ${formatDuration(0, progress.heartbeatAge)} ago`;
  const activity = progress.progressAge === null ? "No progress checkpoint yet" : `Progress checkpoint ${formatDuration(0, progress.progressAge)} ago`;
  append(card, el("p", "run-stage-health", `${heartbeat} · ${activity}`));
  if (progress.stale) append(card, el("p", "notice warning", "The worker heartbeat is stale. Processing may have stopped; recovery becomes available after its lease expires."));
  else if (progress.stalled) append(card, el("p", "notice warning", "The worker is responding, but counters have not advanced recently. Database sorting, joins and indexes may be working between checkpoints."));
  return card;
}

function runFailureNotice(run, tasks) {
  const failure = runFailureSummary(run, tasks);
  if (!failure) return null;
  const notice = el("section", "notice negative stack");
  notice.setAttribute("aria-labelledby", "run-failure-heading");
  const title = el("h2", "", failure.title);
  title.id = "run-failure-heading";
  append(notice,
    title,
    el("p", "", failure.message),
    el("p", "", "No candidate data was published, so the previously accepted release remains unchanged."),
  );
  if (failure.cachedReplayRecommended) {
    append(notice, el("p", "", "The verified canonical file is retained. After correcting import handling, use the downloaded file to retry without repeating acquisition."));
  }
  return notice;
}

function runTimeline(run, tasks, { available = true } = {}) {
  const list = el("ol", "timeline");
  if (!tasks.length) append(list, el("li", "", available
    ? "No task ledger is available yet."
    : "No update-step details can be shown until this feed recovers."));
  for (const rawTask of tasks) {
    const task = reconcileTimelineTask(run, rawTask);
    const live = taskProgress(task);
    const item = el("li");
    const tone = statusTone(task.status);
    const marker = el("span", `timeline-marker ${tone}`, stateLabel(task.status).symbol);
    const detail = el("div");
    const durableRows = live.rows;
    const phase = task.progress_phase ? ` · ${task.progress_phase}` : "";
    const finished = task.finished_at || Date.now();
    const elapsed = task.started_at ? formatDuration(task.started_at, finished) : "not started";
    const rowTotal = task.progress_total_rows == null ? null : Number(task.progress_total_rows);
    const byteTotal = task.progress_total_bytes == null ? null : Number(task.progress_total_bytes);
    const usesRows = Number.isFinite(rowTotal) && rowTotal > 0;
    const processed = usesRows ? durableRows : Number(task.progress_bytes || 0);
    const total = usesRows ? rowTotal : byteTotal;
    const progressRatio = Number.isFinite(total) && total > 0
      ? Math.max(0, Math.min(1, processed / total))
      : null;
    const indeterminate = task.status === "running" && progressRatio === null;
    const unitProgress = usesRows
      ? `${formatNumber(processed)} of ${formatNumber(total)} rows`
      : Number.isFinite(total) && total > 0
        ? `${formatBytes(processed)} of ${formatBytes(total)}`
        : `${formatNumber(durableRows)} rows · ${indeterminate ? "remaining work indeterminate" : "total not recorded"}`;
    const remainingMs = null; // Stage elapsed includes earlier phases; it is not a valid ETA.
    const timing = task.started_at
      ? task.finished_at
        ? `took ${elapsed}`
        : `${elapsed} elapsed${remainingMs === null ? "" : ` · about ${formatDuration(0, remainingMs)} remaining`}`
      : task.status === "skipped"
        ? "not run (cached result reused)"
        : "not started";
    append(detail,
      el("h3", "", humanise(task.stage)),
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

function resolveFeed(result, cache, key) {
  cache.failures ||= {};
  if (result.status === "fulfilled") {
    const items = collection(result.value.body);
    cache[key] = items;
    delete cache.failures[key];
    return { items, available: true, cached: false, error: null };
  }
  const cached = Object.hasOwn(cache, key);
  cache.failures[key] = result.reason;
  return { items: cached ? cache[key] : [], available: false, cached, error: result.reason };
}

function feedWarning(label, feed) {
  if (feed.available) return null;
  const copy = feed.cached
    ? `${label} are temporarily unavailable. Showing the last loaded details.`
    : `${label} are temporarily unavailable. No previously loaded details are available.`;
  return el("div", "notice warning", `${copy}${requestIdSuffix(feed.error)}`);
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
  for (const target of root.querySelectorAll("a[href], button, summary, select, input, [tabindex]")) {
    if (target.dataset.refreshFocusKey) continue;
    const base = target.matches("a[href]")
      ? `link:${target.getAttribute("href")}`
      : target.matches("summary")
        ? target.closest("details")?.dataset.refreshKey || `summary:${target.textContent?.trim()}`
        : `${target.tagName}:${target.getAttribute("aria-label") || target.name || target.textContent?.trim()}`;
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
    const routeEpoch = generationGuard.capture();
    const params = routeQuery(location.hash);
    const filters = { q: params.get("q") || "", status: params.get("status") || "", job: params.get("job") || "" };
    const offset = pageOffset(params);
    renderLoading(view, "Loading run history");
    try {
      const { body } = await request(`ingestion-runs${queryString({ status: filters.status, q: filters.q, job_definition_id: filters.job, limit: 100, offset })}`);
      if (!routeEpoch.isCurrent()) return;
      const runs = collection(body);
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
      append(view, collectionPagination("runs", filters, body, offset));
      if (!runs.length) { append(view, emptyState("No updates found", "Start a saved data update or adjust the current filters.", link("View data updates", "#jobs", "button primary"))); return; }
      const table = makeTable([{ label: "Update" }, { label: "Method" }, { label: "Status" }, { label: "Rows loaded" }, { label: "Started" }, { label: "Reference" }], runs, (run) => {
        const row = el("tr");
        const runLink = link(displayName(run.job_name || `Update ${String(run.id).slice(0, 8)}`), `#runs/${encodeURIComponent(run.id)}`);
        append(row, cell(primaryCell(runLink, displayName(run.dataset_id || run.run_mode))), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatNumber(run.rows_accepted), "numeric"), cell(formatDate(run.requested_at)), cell(technicalReference(run.request_id)));
        return row;
      }, "Data update history", { responsive: true });
      append(view, panel(`${runs.length} ${runs.length === 1 ? "update" : "updates"}`, "Newest first", table));
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren(errorState(error, rerender));
    }
  }

  async function renderRunDetail(id, { polling = false, resetInterruptedReconciliation = false } = {}) {
    const refresh = refreshGuard.begin();
    const routeEpoch = generationGuard.capture();
    const isCurrent = () => refresh.isCurrent()
      && routeEpoch.isCurrent()
      && parseRoute(location.hash).route === "runs"
      && parseRoute(location.hash).id === id;
    clearTimeout(state.pollTimer);
    if (resetInterruptedReconciliation) state.interruptedReconciliationAttempts = 0;
    if (polling && state.lastRunStatus === "interrupted") {
      state.interruptedReconciliationAttempts += 1;
    }
    if (!polling) renderLoading(view, "Loading run evidence");
    else {
      view.setAttribute("aria-busy", "true");
      const status = view.querySelector("[data-run-refresh-status]");
      if (status) status.textContent = "Refreshing update status…";
    }
    try {
      const cache = retainRecent(feedCache, id, feedCache.get(id) || {});
      const detailResult = await request(`ingestion-runs/${id}`, { signal: refresh.signal });
      if (!isCurrent()) return;
      const run = entity(detailResult.body, "run");
      const refreshEvidence = !polling || cache.runStatus !== run.status || Date.now() - (cache.evidenceAt || 0) > 15000;
      const evidenceRequest = (key, path) => !refreshEvidence && Object.hasOwn(cache, key)
        ? cache.failures?.[key] ? Promise.reject(cache.failures[key]) : Promise.resolve({ body: { items: cache[key] } })
        : request(path, { signal: refresh.signal });
      const supportingFeeds = Promise.allSettled([
        request(`ingestion-runs/${id}/tasks?limit=100`, { signal: refresh.signal }),
        evidenceRequest("quality", `ingestion-runs/${id}/quality-results?limit=100`),
        evidenceRequest("artifacts", `ingestion-runs/${id}/artifacts?limit=100`),
        evidenceRequest("releases", `dataset-releases?ingestion_run_id=${encodeURIComponent(id)}&limit=100`),
        request(`ingestion-runs/${id}/activity?limit=${!polling || cache.runStatus !== run.status ? 1000 : 100}`, { signal: refresh.signal }),
      ]);
      const [tasksResult, qualityResult, artifactsResult, releasesResult, activityResult] = await supportingFeeds;
      if (!isCurrent()) return;
      if (refreshEvidence) cache.evidenceAt = Date.now();
      cache.runStatus = run.status;
      const tasksFeed = resolveFeed(tasksResult, cache, "tasks");
      const qualityFeed = resolveFeed(qualityResult, cache, "quality");
      const artifactsFeed = resolveFeed(artifactsResult, cache, "artifacts");
      const releasesFeed = resolveFeed(releasesResult, cache, "releases");
      const activityFeed = resolveFeed(activityResult, cache, "activity");
      cache.activityHistory = mergeActivity(cache.activityHistory || [], activityFeed.items);
      cache.logOptions ||= { filter: "all", paused: false, frozen: [], autoscroll: true };
      const latestActivity = new Map(cache.activityHistory.map((event) => [event.task_id, event.recorded_at]));
      const tasks = tasksFeed.items.map((task) => ({ ...task, progress_changed_at: latestActivity.get(task.id) }));
      const quality = qualityFeed.items;
      const artifacts = artifactsFeed.items;
      const linkedRelease = releasesFeed.items.find((release) => release.ingestion_run_id === id && !["accepted", "superseded"].includes(release.status));
      const refreshState = polling ? captureRefreshState(view) : null;
      disposeTableRegions(view);
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
      if (availability.resume) runAction("resume", "Resume update", "Restart the interrupted stage from its verified input. COPY and export restart that stage from the beginning; earlier completed stages are reused.");
      if (availability.retry) runAction("retry", "Retry update", "Start the full update again while keeping this failed attempt in the history.");
      if (availability.reprocess) runAction("reprocess-cached", "Use downloaded file", "Start again with the already downloaded and verified file.");
      if (availability.cancel) runAction("cancel", "Cancel update", "Stop the update. Completed steps will remain in its history.", "danger");
      if (availability.diagnose) {
        const failed = run.status === "failed";
        actions.push(button(
          failed ? "Explain this failure" : "Ask AI about update",
          `button ${failed ? "primary" : "secondary"}`,
          () => {
            const draft = failed ? `&draft=${encodeURIComponent(failureExplanationDraft(run, tasks))}` : "";
            const label = String(run.source_name || run.job_name || run.dataset_id || "Data update").slice(0, 200);
            location.hash = `#assistant?route=runs/detail&ingestion_run_id=${encodeURIComponent(id)}&display_label=${encodeURIComponent(label)}${draft}`;
          },
        ));
        if (linkedRelease) {
          actions.push(link("Open candidate", `#releases/${linkedRelease.id}`, "button primary"));
          actions.push(button("Ask AI to review candidate", "button secondary", () => {
            location.hash = `#ai/release:${linkedRelease.id}?goal=${failed ? "quality" : "compare"}`;
          }));
        }
      }
      const sourceName = displayName(run.source_name || run.job_name || run.dataset_id || `Update ${String(id).slice(0, 8)}`);
      const activeCard = activeStageCard(run, tasks);
      append(view, pageHeading("Data update", activeCard ? `Updating ${sourceName}` : sourceName, `${humanise(run.run_mode)} · requested ${formatDate(run.requested_at)} · reference ${String(id).slice(0, 8)}`, actions));
      if (activeCard) append(view, activeCard);
      if (run.status === "succeeded" && linkedRelease) append(view, el("div", "notice positive", `Candidate prepared with ${formatNumber(linkedRelease.record_count)} records. Open the candidate to inspect its checks and make a separate publication decision.`));
      const nextDelay = nextRunDetailPollDelay(
        run.status,
        0,
        document.hidden,
        state.interruptedReconciliationAttempts,
      );
      const refreshCopy = run.status === "interrupted"
        ? nextDelay === null
          ? "Refreshed just now · automatic recovery checks complete; return to this tab or refresh to check again"
          : "Refreshed just now · checking periodically for recovery started elsewhere"
        : nextDelay !== null
          ? "Refreshed just now · updates automatically while this update is active"
          : "Refreshed just now · latest saved status";
      const refreshStatus = el("p", "run-refresh-status", refreshCopy);
      refreshStatus.dataset.runRefreshStatus = "";
      append(view, refreshStatus);
      const releaseWarning = feedWarning("Published-version details", releasesFeed);
      if (releaseWarning) append(view, releaseWarning);
      const failureNotice = runFailureNotice(run, tasks);
      if (failureNotice) append(view, failureNotice);
      const metrics = el("div", "metric-strip");
      for (const [label, value] of [["Found", formatNumber(run.rows_discovered)], ["Prepared", formatNumber(run.rows_staged)], ["Loaded", formatNumber(run.rows_accepted)], ["Rejected", formatNumber(run.rows_rejected)]]) {
        const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(metrics, metric);
      }
      if (!activeCard) append(view, metrics);
      const grid = el("div", "dashboard-grid");
      const runBody = el("div");
      const tasksWarning = feedWarning("Update steps", tasksFeed);
      if (tasksWarning) append(runBody, tasksWarning);
      append(runBody, runTimeline(run, tasks, { available: tasksFeed.available || tasksFeed.cached }));
      const evidence = el("div", "stack");
      const evidenceAvailability = el("div");
      const qualityWarning = feedWarning("Data checks", qualityFeed);
      const artifactsWarning = feedWarning("File and lineage details", artifactsFeed);
      if (qualityWarning) append(evidenceAvailability, qualityWarning);
      if (artifactsWarning) append(evidenceAvailability, artifactsWarning);
      append(evidence,
        panel("Update status", "Current state", detailList([["Status", badge(run.status)], ["Last activity", formatDate(run.last_activity_at || run.finished_at || run.heartbeat_at)], ["Attempt", run.attempt_number], ["Previous update", run.parent_run_id ? link(String(run.parent_run_id), `#runs/${run.parent_run_id}`) : "None"], ["Reference", el("code", "mono", run.request_id || detailResult.requestId)], ["Finished", formatDate(run.finished_at)]])),
        disclosurePanel("Saved progress", "Stage inputs used for recovery; not row-level restart positions", detailList([["Input checkpoint", JSON.stringify(run.input_checkpoint_json || {})], ["Candidate checkpoint", JSON.stringify(run.output_checkpoint_json || {})], ["Published watermark", JSON.stringify(run.accepted_watermark_json || {})]])),
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
      const activityBody = runActivity(cache.activityHistory, id, cache.logOptions);
      const activityWarning = feedWarning("Saved activity", activityFeed);
      if (activityWarning) activityBody.prepend(activityWarning);
      append(view, disclosurePanel("Live activity", "Saved stage changes, progress and bounded failure codes", activityBody, { open: true }));
      append(view, panel("Technical run details", "Expandable record for troubleshooting and audit", technicalDetails(detailResult.body)));
      annotateRefreshState(view);
      if (refreshState) restoreRefreshState(view, refreshState);
      const statusChanged = state.lastRunStatus && state.lastRunStatus !== run.status;
      if (statusChanged) announce(`Run status changed to ${humanise(run.status)}.`);
      state.lastRunStatus = run.status;
      if (run.status !== "interrupted") state.interruptedReconciliationAttempts = 0;
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
    } finally {
      refresh.finish();
    }
  }

  function scheduleRunPoll(id, status, failures = 0) {
    clearTimeout(state.pollTimer);
    const delay = nextRunDetailPollDelay(
      status,
      failures,
      document.hidden,
      state.interruptedReconciliationAttempts,
    );
    if (delay === null) return;
    const routeEpoch = generationGuard.capture();
    state.pollTimer = setTimeout(() => {
      const current = parseRoute(location.hash);
      if (routeEpoch.isCurrent() && current.route === "runs" && current.id === id) renderRunDetail(id, { polling: true });
    }, delay);
  }

  return { renderRuns, renderRunDetail };
}
