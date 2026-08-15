import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatDate, formatNumber, humanise, stateLabel, statusTone } from "../core/formats.js";
import { actionAvailability, nextPollDelay } from "../core/polling.js";
import { parseRoute, routeQuery } from "../core/router.js";
import { filterToolbar } from "../components/forms.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
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
    if (task.error_json) append(detail, technicalDetails(task.error_json, "Safe failure evidence"));
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
      append(view, pageHeading("Feature 1 · Durable orchestration", "Ingestion runs", "Inspect task attempts, checkpoints, candidate failures and recovery lineage while accepted data remains stable.", [link("Run a job", "#jobs", "button primary")]));
      if (filters.job) {
        const jobFilter = el("div", "notice notice-actions");
        append(jobFilter, el("span", "", `Showing history for job ${filters.job}.`), link("Clear job filter", "#runs", "button secondary small"));
        append(view, jobFilter);
      }
      append(view, filterToolbar({ search: filters.q, status: filters.status, statuses: RUN_FILTERS, placeholder: "Run, job or request ID", onApply: (values) => { location.hash = `#runs${queryString({ ...values, job: filters.job })}`; rerender(); } }));
      if (!runs.length) { append(view, emptyState("No runs found", "Launch a validated job plan or adjust the current filters.", link("Open jobs", "#jobs", "button primary"))); return; }
      const table = makeTable([{ label: "Run" }, { label: "Mode" }, { label: "Progress" }, { label: "Rows accepted" }, { label: "Requested" }, { label: "Request ID" }], runs, (run) => {
        const row = el("tr");
        append(row, cell(primaryCell(run.job_name || `Run ${String(run.id).slice(0, 8)}`, run.id)), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatNumber(run.rows_accepted), "numeric"), cell(formatDate(run.requested_at)), cell(run.request_id || "—", "mono"));
        row.tabIndex = 0;
        row.setAttribute("aria-label", `Open run ${run.id}`);
        row.addEventListener("click", () => { location.hash = `#runs/${run.id}`; });
        row.addEventListener("keydown", (event) => { if (event.key === "Enter") location.hash = `#runs/${run.id}`; });
        return row;
      }, "Ingestion run history");
      append(view, panel(`${runs.length} runs`, "Newest evidence first", table));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  async function renderRunDetail(id, { polling = false } = {}) {
    const scrollTop = polling ? window.scrollY : 0;
    if (!polling) renderLoading(view, "Loading run evidence");
    try {
      const [detailResult, tasksResult, qualityResult, artifactsResult] = await Promise.all([
        request(`ingestion-runs/${id}`), request(`ingestion-runs/${id}/tasks?limit=100`), request(`ingestion-runs/${id}/quality-results?limit=100`), request(`ingestion-runs/${id}/artifacts?limit=100`),
      ]);
      const run = entity(detailResult.body, "run");
      const tasks = collection(tasksResult.body);
      const quality = collection(qualityResult.body);
      const artifacts = collection(artifactsResult.body);
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
      if (availability.resume) runAction("resume", "Resume", "Continue the existing non-terminal run from durable task evidence.");
      if (availability.retry) runAction("retry", "Retry failed", "Create a linked full-pipeline retry with the failed run retained as its parent evidence.");
      if (availability.reprocess) runAction("reprocess-cached", "Reprocess cached", "Create a linked child run using verified cached artifacts and current transforms.");
      if (availability.cancel) runAction("cancel", "Cancel", "Request cooperative cancellation. Completed evidence will remain available.", "danger");
      if (availability.diagnose) actions.push(button("Diagnose with AI", "button primary", () => { location.hash = "#ai"; }));
      append(view, pageHeading("Run evidence", run.job_name || `Run ${String(id).slice(0, 8)}`, `${humanise(run.run_mode)} · ${formatDate(run.requested_at)}`, actions));
      if (run.error_json) append(view, el("div", "notice negative", `${run.error_json.message || run.error_json.detail || "The run recorded a classified failure."} The previously accepted release remains unchanged.`));
      const metrics = el("div", "metric-strip");
      for (const [label, value] of [["Discovered", formatNumber(run.rows_discovered)], ["Staged", formatNumber(run.rows_staged)], ["Accepted", formatNumber(run.rows_accepted)], ["Rejected", formatNumber(run.rows_rejected)]]) {
        const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(metrics, metric);
      }
      append(view, metrics);
      const grid = el("div", "dashboard-grid");
      const runBody = el("div");
      append(runBody, runTimeline(tasks));
      const evidence = el("div", "stack");
      append(evidence,
        panel("Run state", "Control-plane projection", detailList([["Status", badge(run.status)], ["Heartbeat", formatDate(run.heartbeat_at)], ["Attempt", run.attempt_number], ["Parent run", run.parent_run_id ? link(String(run.parent_run_id), `#runs/${run.parent_run_id}`) : "None"], ["Request ID", el("code", "mono", run.request_id || detailResult.requestId)], ["Finished", formatDate(run.finished_at)]])),
        panel("Checkpoints and watermark", "Candidate progress never advances accepted data", detailList([["Input checkpoint", JSON.stringify(run.input_checkpoint_json || {})], ["Candidate checkpoint", JSON.stringify(run.output_checkpoint_json || {})], ["Accepted watermark", JSON.stringify(run.accepted_watermark_json || {})]])),
        panel("Linked evidence", "Safe metadata only", detailList([["Quality checks", link(`${quality.length} results`, `#quality/${id}`)], ["Artifacts", link(`${artifacts.length} records`, `#artifacts/${id}`)]])),
      );
      append(grid, panel("Stage and task timeline", `${tasks.length} durable task records`, runBody), evidence);
      append(view, grid);
      append(view, panel("Complete run projection", "Expandable, structured evidence for audit", technicalDetails(detailResult.body)));
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
