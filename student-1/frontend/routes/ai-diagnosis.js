import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatDate, formatNumber, humanise, researchAreaLabel, stateLabel, statusTone } from "../core/formats.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

const AGENT_ACTIVITY_URL = "http://localhost:5005/operations/ai-mode/";
const OBJECTIVES = Object.freeze({
  compare: "Compare this candidate with its accepted predecessor, identify deterministic quality or consumer failures, preserve accepted data, and propose only a reviewed safe recovery.",
  quality: "Inspect this candidate's exact ingestion run and deterministic quality evidence, identify blocking checks, preserve prior observations, and propose only a reviewed bounded reprocess.",
  consumer: "Inspect this candidate's publication receipts and accepted predecessor, identify retryable consumer failures, and propose a recovery without publishing or mutating data.",
});

export function createAiDiagnosisRoutes({ view, request, loading, mutate, rerender }) {
  async function renderAi(context = "") {
    loading("Loading diagnosis workspace");
    try {
      const [releasesResult, historyResult] = await Promise.all([
        request("dataset-releases?limit=100"),
        request("agent-runs?limit=50").catch((error) => ({ error, body: { items: [] } })),
      ]);
      const releases = collection(releasesResult.body);
      const candidates = releases.filter((release) => !["accepted", "superseded"].includes(release.status));
      const history = collection(historyResult.body);
      const selectedAgentRun = context && !context.startsWith("release:") ? context : "";
      view.replaceChildren();
      append(view, pageHeading("Data recovery", "Assisted diagnosis", "Investigate one unpublished dataset and its processing run. The assistant can gather evidence and propose a recovery, but a person must decide what happens next.", selectedAgentRun ? [link("New diagnosis", "#ai", "button secondary"), sharedRunLink(selectedAgentRun, "Open activity history")] : [link("Open activity history", AGENT_ACTIVITY_URL, "button secondary")]));
      append(view, el("div", "notice", "Property search, sources, import jobs, published datasets and quality evidence remain available if the local model is offline. Previously recorded observations are never hidden by a later failure."));
      if (historyResult.error) append(view, el("div", "notice warning", `Diagnosis history is temporarily unavailable.${problemSuffix(historyResult.error)}`));
      else if (!history.length) append(view, emptyState("No diagnosis history", "Start the first bounded investigation below. Its durable evidence will remain available after navigation or reload."));
      else append(view, diagnosisHistory(history, selectedAgentRun));
      if (selectedAgentRun) {
        const traceHost = el("div"); append(view, traceHost); await renderAgentTrace(selectedAgentRun, traceHost);
      }
      append(view, await diagnosisForm(candidates, context));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  function diagnosisHistory(history, selectedAgentRun) {
    return panel("Diagnosis history", `${history.length} recorded investigations · newest first`, makeTable(
      [{ label: "Diagnosis" }, { label: "State" }, { label: "Latest phase" }, { label: "Tool calls" }, { label: "Started" }, { label: "Evidence" }], history,
      (run) => { const row = el("tr"); append(row, cell(primaryCell(run.objective_preview || "Bounded diagnosis", run.id)), cell(badge(run.status)), cell(humanise(run.latest_phase)), cell(formatNumber(run.tool_call_count), "numeric"), cell(formatDate(run.created_at)), cell(link(run.id === selectedAgentRun ? "Viewing trace" : "View trace", `#ai/${run.id}`, "button secondary small"), "actions-cell")); return row; },
    ));
  }

  async function diagnosisForm(candidates, context) {
    const host = el("section", "panel"); const heading = el("div", "panel-heading"); const copy = el("div");
    append(copy, el("h2", "", "Start a diagnosis"), el("p", "", "Plan → Act → Observe → Adapt, using read-only evidence and a separate human decision")); append(heading, copy); const body = el("div", "panel-body"); append(host, heading, body);
    if (!candidates.length) { append(body, emptyState("Nothing needs diagnosis", "A draft, candidate, review or rejected dataset will appear here when it needs investigation.")); return host; }
    const form = el("form", "form-grid");
    const releaseLabel = el("label", "wide"); append(releaseLabel, el("span", "", "Dataset to investigate")); const releaseSelect = el("select"); releaseSelect.required = true;
    for (const release of candidates) { const option = el("option", "", `${release.dataset_id} ${release.release_version} · ${humanise(release.status)} · run ${release.ingestion_run_id}`); option.value = release.id; option.selected = context === `release:${release.id}`; append(releaseSelect, option); }
    append(releaseLabel, releaseSelect);
    const objectiveLabel = el("label", "wide"); append(objectiveLabel, el("span", "", "Investigation goal")); const objective = el("select"); objective.required = true;
    append(objective, option("compare", "Compare candidate, predecessor and failures"), option("quality", "Inspect blocking quality evidence"), option("consumer", "Inspect consumer publication failure")); append(objectiveLabel, objective);
    const scope = el("div", "notice wide"); scope.setAttribute("aria-live", "polite");
    const updateScope = () => { const release = candidates.find((item) => item.id === releaseSelect.value) || candidates[0]; scope.textContent = `Evidence boundary: release ${release.id}; ingestion run ${release.ingestion_run_id}; accepted predecessor for ${release.dataset_id} and ${researchAreaLabel(release.target_feature)}; bounded release, run, quality, coverage and receipt metadata only.`; };
    releaseSelect.addEventListener("change", updateScope); updateScope();
    const review = el("label", "wide review-acknowledgement"); const check = el("input"); check.type = "checkbox"; check.required = true; append(review, check, el("span", "", "I understand this run can propose a recovery, but cannot approve, publish or execute a protected mutation on my behalf."));
    const submit = button("Start diagnosis", "button primary"); submit.type = "submit";
    append(form, releaseLabel, objectiveLabel, scope, review, submit); append(body, form);
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); if (!form.reportValidity()) return; submit.disabled = true;
      const progress = el("div", "notice", "Creating a durable Agent activity run…"); body.prepend(progress);
      try {
        const result = await mutate(`dataset-releases/${releaseSelect.value}/agent-runs`, { body: { objective: OBJECTIVES[objective.value] }, success: "Diagnosis started" });
        const run = entity(result, "agent_run"); location.hash = `#ai/${run.id || result.id}`;
      } catch (error) {
        progress.className = "notice warning"; progress.textContent = `${error.status === 503 ? "The model service is unavailable. Deterministic evidence and recovery controls remain usable." : error.message}${problemSuffix(error)}`; submit.disabled = false;
      }
    });
    return host;
  }

  async function renderAgentTrace(id, host) {
    const [detailResult, eventsResult] = await Promise.allSettled([
      request(`agent-runs/${id}`), request(`agent-runs/${id}/events${queryString({ after: 0, limit: 100 })}`),
    ]);
    const detailError = detailResult.status === "rejected" ? detailResult.reason : null;
    const eventsError = eventsResult.status === "rejected" ? eventsResult.reason : null;
    const run = detailResult.status === "fulfilled" ? entity(detailResult.value.body, "agent_run") : { id, status: "unknown" };
    const events = eventsResult.status === "fulfilled" ? collection(eventsResult.value.body) : [];
    const body = el("div", "stack");
    append(body, detailList([["State", badge(run.status)], ["Agent run", el("code", "mono", run.id || id)], ["Request ID", el("code", "mono", run.request_id || detailResult.value?.requestId || "Not available")], ["Execution", "Read-only evidence gathering; protected actions require a separate human review"]]));
    if (detailError) append(body, el("div", "notice warning", `Latest run summary is unavailable. Previously recorded events remain below.${problemSuffix(detailError)}`));
    if (eventsError) append(body, el("div", "notice warning", `Durable event retrieval failed; no prior observation has been replaced by a negative conclusion.${problemSuffix(eventsError)}`));
    const steps = run.steps || detailResult.value?.body?.steps || events;
    if (!steps.length) append(body, emptyState("No durable events yet", "The run exists, but no Plan, Act, Observe or Adapt event is currently available."));
    else {
      const timeline = el("ol", "timeline");
      for (const step of steps) { const item = el("li"); const detail = el("div"); append(detail, el("h3", "", humanise(step.phase || step.event_type || "Agent event")), el("p", "", step.summary || step.message || humanise(step.status))); if (step.tool_key || step.tool_name) append(detail, el("code", "mono", step.tool_key || step.tool_name)); if (step.evidence || step.observation) append(detail, technicalDetails(step.evidence || step.observation, "Inspect bounded observation")); append(item, el("span", `timeline-marker ${statusTone(step.status)}`, stateLabel(step.status).symbol), detail); append(timeline, item); }
      append(body, timeline);
    }
    if (["review_required", "awaiting_review"].includes(run.status)) append(body, el("div", "notice warning", "Proposed action only: a protected retry or publication is paused. Review and execution are separate human-controlled steps in Agent activity; no write has occurred."));
    if (run.final_result) append(body, panel("Recovery proposal", "Model output is evidence for review, not approval or execution", technicalDetails(run.final_result, "Inspect proposal and cited evidence")));
    const controls = el("div", "dialog-actions"); append(controls, sharedRunLink(id, "Open durable run detail"), button("Refresh evidence", "button secondary", () => renderAgentTrace(id, host))); append(body, controls);
    host.replaceChildren(panel("Plan · Act · Observe · Adapt", "Durable events from this exact Agent activity run", body));
  }

  return { renderAi };
}

function option(value, label) { const item = el("option", "", label); item.value = value; return item; }
function sharedRunLink(runId, label) { return link(label, `${AGENT_ACTIVITY_URL}?run=${encodeURIComponent(runId)}&feature_key=student-1-propertyscope-data-platform`, "button secondary"); }
function problemSuffix(error) { return error?.requestId ? ` Request ID ${error.requestId}.` : ""; }
