import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { displayName, formatDate, formatNumber, humanise, stateLabel, statusTone } from "../core/formats.js?v=16";
import { actionAvailability, nextPollDelay } from "../core/polling.js";
import { parseRoute, routeQuery } from "../core/router.js";
import { filterToolbar } from "../components/forms.js?v=17";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js?v=17";
import { emptyState, errorState, renderLoading } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

const RUN_FILTERS = ["", "requested", "queued", "running", "succeeded", "failed", "cancelled", "interrupted"];

function runTimeline(tasks) {
  const list = el("ol", "timeline");
  if (!tasks.length) append(list, el("li", "", "No task ledger is available yet."));
  for (const task of tasks) {
    const item = el("li");
    const tone = statusTone(task.status);
    const marker = el("span", `timeline-marker ${tone}`, stateLabel(task.status).symbol);
    const detail = el("div");
    append(detail, el("h3", "", `${humanise(task.stage)} · ${task.logical_key || "Task"}`), el("p", "", `${humanise(task.status)} · attempt ${task.attempt_number ?? 1} · ${formatNumber(task.rows_out)} rows out`));
    if (task.error_json) append(detail, technicalDetails(task.error_json, "Failure details"));
    append(item, marker, detail);
    append(list, item);
  }
  return list;
}

export function createRunRoutes({ view, request, mutate, confirmAction, showToast, announce, state, generationGuard, rerender }) {
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
        append(jobFilter, el("span", "", `Showing history for job ${filters.job}.`), link("Clear job filter", "#runs", "button secondary small"));
        append(view, jobFilter);
      }
      append(view, filterToolbar({ search: filters.q, status: filters.status, statuses: RUN_FILTERS, placeholder: "Update name or reference", onApply: (values) => { location.hash = `#runs${queryString({ ...values, job: filters.job })}`; rerender(); } }));
      if (!runs.length) { append(view, emptyState("No updates found", "Start a saved data update or adjust the current filters.", link("View data updates", "#jobs", "button primary"))); return; }
      const table = makeTable([{ label: "Update" }, { label: "Method" }, { label: "Status" }, { label: "Rows loaded" }, { label: "Started" }, { label: "Reference" }], runs, (run) => {
        const row = el("tr");
        append(row, cell(primaryCell(displayName(run.job_name || `Update ${String(run.id).slice(0, 8)}`), run.id)), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatNumber(run.rows_accepted), "numeric"), cell(formatDate(run.requested_at)), cell(run.request_id || "—", "mono"));
        row.tabIndex = 0;
        row.setAttribute("aria-label", `Open run ${run.id}`);
        row.addEventListener("click", () => { location.hash = `#runs/${run.id}`; });
        row.addEventListener("keydown", (event) => { if (event.key === "Enter") location.hash = `#runs/${run.id}`; });
        return row;
      }, "Data update history");
      append(view, panel(`${runs.length} updates`, "Newest first", table));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  async function renderRunDetail(id, { polling = false } = {}) {
    const scrollTop = polling ? window.scrollY : 0;
    if (!polling) renderLoading(view, "Loading run evidence");
    try {
      const [detailResult, tasksResult, qualityResult, artifactsResult, releasesResult] = await Promise.all([
        request(`ingestion-runs/${id}`), request(`ingestion-runs/${id}/tasks?limit=100`), request(`ingestion-runs/${id}/quality-results?limit=100`), request(`ingestion-runs/${id}/artifacts?limit=100`),
        request("dataset-releases?limit=100").catch(() => ({ body: { items: [] } })),
      ]);
      const run = entity(detailResult.body, "run");
      const tasks = collection(tasksResult.body);
      const quality = collection(qualityResult.body);
      const artifacts = collection(artifactsResult.body);
      const linkedRelease = collection(releasesResult.body).find((release) => release.ingestion_run_id === id && !["accepted", "superseded"].includes(release.status));
      view.replaceChildren();
      const availability = actionAvailability(run.status);
      const actions = [];
      const runAction = (key, label, description, tone = "secondary") => actions.push(button(label, `button ${tone}`, async () => {
        const confirmed = await confirmAction({ title: `${label} this run?`, description, label, tone: tone === "secondary" ? "primary" : tone });
        if (!confirmed) return;
        try {
          const created = await mutate(`ingestion-runs/${id}/${key}`, { success: `${label} requested` });
          const child = entity(created, "run");
          if (child?.id && child.id !== id) location.hash = `#runs/${child.id}`;
          else renderRunDetail(id);
        } catch (error) { showToast(`${error.message} Request ID ${error.requestId}`); }
      }));
      if (availability.resume) runAction("resume", "Resume update", "Continue this interrupted update from its last saved step.");
      if (availability.retry) runAction("retry", "Retry update", "Start the full update again while keeping this failed attempt in the history.");
      if (availability.reprocess) runAction("reprocess-cached", "Use downloaded file", "Start again with the already downloaded and verified file.");
      if (availability.cancel) runAction("cancel", "Cancel update", "Stop the update. Completed steps will remain in its history.", "danger");
      if (availability.diagnose) {
        const failed = run.status === "failed";
        actions.push(button(failed ? "Explain this failure" : "Ask AI about run", `button ${failed ? "primary" : "secondary"}`, () => { location.hash = linkedRelease ? `#ai/release:${linkedRelease.id}?goal=${failed ? "quality" : "compare"}` : "#ai"; }));
      }
      append(view, pageHeading("Data update", displayName(run.job_name || `Update ${String(id).slice(0, 8)}`), `${humanise(run.run_mode)} · started ${formatDate(run.requested_at)}`, actions));
      if (run.error_json) append(view, el("div", "notice negative", `${run.error_json.message || run.error_json.detail || "The run recorded a classified failure."} The previously accepted release remains unchanged.`));
      const metrics = el("div", "metric-strip");
      for (const [label, value] of [["Found", formatNumber(run.rows_discovered)], ["Prepared", formatNumber(run.rows_staged)], ["Loaded", formatNumber(run.rows_accepted)], ["Rejected", formatNumber(run.rows_rejected)]]) {
        const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(metrics, metric);
      }
      append(view, metrics);
      const grid = el("div", "dashboard-grid");
      const runBody = el("div");
      append(runBody, runTimeline(tasks));
      const evidence = el("div", "stack");
      append(evidence,
        panel("Update status", "Current state", detailList([["Status", badge(run.status)], ["Last activity", formatDate(run.heartbeat_at)], ["Attempt", run.attempt_number], ["Previous update", run.parent_run_id ? link(String(run.parent_run_id), `#runs/${run.parent_run_id}`) : "None"], ["Reference", el("code", "mono", run.request_id || detailResult.requestId)], ["Finished", formatDate(run.finished_at)]])),
        panel("Saved progress", "Technical checkpoints used if the update must resume", detailList([["Input checkpoint", JSON.stringify(run.input_checkpoint_json || {})], ["Candidate checkpoint", JSON.stringify(run.output_checkpoint_json || {})], ["Published watermark", JSON.stringify(run.accepted_watermark_json || {})]])),
        panel("Checks and files", "Specialist details for this update", detailList([["Quality checks", link(`${quality.length} results`, `#quality/${id}`)], ["Files and lineage", link(`${artifacts.length} records`, `#artifacts/${id}`)]])),
      );
      append(grid, panel("Update timeline", `${tasks.length} recorded steps`, runBody), evidence);
      append(view, grid);
      append(view, panel("Technical run details", "Expandable record for troubleshooting and audit", technicalDetails(detailResult.body)));
      if (polling) window.scrollTo({ top: scrollTop });
      const statusChanged = state.lastRunStatus && state.lastRunStatus !== run.status;
      if (statusChanged) announce(`Run status changed to ${humanise(run.status)}.`);
      state.lastRunStatus = run.status;
      scheduleRunPoll(id, run.status);
    } catch (error) {
      if (!polling) view.replaceChildren(errorState(error, () => renderRunDetail(id)));
      else scheduleRunPoll(id, state.lastRunStatus, 1);
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
