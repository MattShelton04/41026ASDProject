import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatDate, formatNumber, humanise, researchAreaLabel, stateLabel, statusTone } from "../core/formats.js";
import { nextAgentPollDelay } from "../core/polling.js";
import { parseRoute } from "../core/router.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

const AGENT_ACTIVITY_URL = window.PROPERTYSCOPE_AGENT_ACTIVITY_URL
  || (window.location.pathname.startsWith("/features/data-platform/")
    ? "/operations/ai-mode/"
    : `${window.location.protocol}//${window.location.hostname}:5005/operations/ai-mode/`);
const OBJECTIVES = Object.freeze({
  compare: "Required outcome: compare this candidate with its accepted predecessor; quantify material schema, record-count, coverage, quality, and publication differences; distinguish missing evidence from a pass; confirm accepted data remains unchanged; and recommend one specific human-reviewed safe recovery. Do not publish or mutate data.",
  quality: "Required outcome: inspect this candidate and its exact ingestion run; identify each blocking or failed deterministic quality check and its observed impact; distinguish an empty result set from a pass; confirm prior accepted observations remain available; and recommend one specific human-reviewed bounded reprocess. Do not execute it.",
  consumer: "Required outcome: inspect this candidate's publication receipts and accepted predecessor; identify each failed or retryable consumer delivery with exact evidence; distinguish no receipt from successful delivery; confirm accepted data remains available; and recommend one specific recovery that requires separate human review. Do not publish or mutate data.",
});

export function createAiDiagnosisRoutes({ view, request, loading, mutate, state, generationGuard, rerender }) {
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
        const traceHost = el("div");
        traceHost.dataset.agentTrace = selectedAgentRun;
        traceHost.setAttribute("aria-live", "polite");
        append(view, traceHost);
        await renderAgentTrace(selectedAgentRun, traceHost);
      }
      append(view, await diagnosisForm(candidates, context));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  function diagnosisHistory(history, selectedAgentRun) {
    return panel("Diagnosis history", `${history.length} recorded investigations · newest first`, makeTable(
      [{ label: "Diagnosis" }, { label: "State" }, { label: "Latest phase" }, { label: "Tool calls" }, { label: "Started" }, { label: "Evidence" }], history,
      (run) => {
        const row = el("tr"); row.dataset.agentRunId = run.id;
        const status = cell(badge(run.status)); status.dataset.agentField = "status";
        const phase = cell(humanise(run.latest_phase)); phase.dataset.agentField = "phase";
        const tools = cell(formatNumber(run.tool_call_count), "numeric"); tools.dataset.agentField = "tools";
        append(row, cell(primaryCell(run.objective_preview || "Bounded diagnosis", run.id)), status, phase, tools, cell(formatDate(run.created_at)), cell(link(run.id === selectedAgentRun ? "Viewing trace" : "View trace", `#ai/${run.id}`, "button secondary small"), "actions-cell"));
        return row;
      },
    ));
  }

  async function diagnosisForm(candidates, context) {
    const host = el("section", "panel"); const heading = el("div", "panel-heading"); const copy = el("div");
    append(copy, el("h2", "", "Start a diagnosis"), el("p", "", "Plan → Act → Observe → Adapt, using read-only evidence and a separate human decision")); append(heading, copy); const body = el("div", "panel-body"); append(host, heading, body);
    if (!candidates.length) { append(body, emptyState("Nothing needs diagnosis", "A draft, candidate, review or rejected dataset will appear here when it needs investigation.")); return host; }
    const form = el("form", "form-grid");
    const releaseLabel = el("label", "wide"); releaseLabel.htmlFor = "diagnosis-release"; append(releaseLabel, el("span", "", "Dataset to investigate")); const releaseSelect = el("select"); releaseSelect.id = "diagnosis-release"; releaseSelect.required = true;
    for (const release of candidates) { const option = el("option", "", `${release.dataset_id} ${release.release_version} · ${humanise(release.status)} · run ${release.ingestion_run_id}`); option.value = release.id; option.selected = context === `release:${release.id}`; append(releaseSelect, option); }
    append(releaseLabel, releaseSelect);
    const objectiveLabel = el("label", "wide"); objectiveLabel.htmlFor = "diagnosis-objective"; append(objectiveLabel, el("span", "", "Investigation goal")); const objective = el("select"); objective.id = "diagnosis-objective"; objective.required = true;
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

  async function renderAgentTrace(id, host, failures = 0) {
    const generation = generationGuard.current();
    host.setAttribute("aria-busy", "true");
    const [detailResult, eventsResult] = await Promise.allSettled([
      request(`agent-runs/${id}`), request(`agent-runs/${id}/events${queryString({ after: 0, limit: 100 })}`),
    ]);
    if (!generationGuard.isCurrent(generation)) return;
    const detailError = detailResult.status === "rejected" ? detailResult.reason : null;
    const eventsError = eventsResult.status === "rejected" ? eventsResult.reason : null;
    const run = detailResult.status === "fulfilled" ? entity(detailResult.value.body, "agent_run") : { id, status: host.dataset.agentStatus || "unknown" };
    const events = eventsResult.status === "fulfilled" ? collection(eventsResult.value.body) : [];
    const recordedSteps = Array.isArray(run.steps) ? run.steps : detailResult.value?.body?.steps;
    const steps = recordedSteps?.length ? recordedSteps : events;
    const failedSteps = steps.filter((step) => String(step.status).toLowerCase() === "failed");
    const repairCount = steps.reduce((total, step) => total + Number(step.output?.model_invocation?.repair_count || 0), 0);
    const providerRetryCount = steps.reduce((total, step) => total + Number(step.output?.model_invocation?.provider_retry_count || 0), 0);
    const body = el("div", "stack");
    append(body, detailList([["State", badge(run.status)], ["Model profile", run.model_profile || "Not recorded"], ["Evidence calls", formatNumber(run.tool_call_count)], ["Iterations", formatNumber(run.iteration_count)], ["Agent run", el("code", "mono", run.id || id)], ["Request ID", el("code", "mono", run.request_id || detailResult.value?.requestId || "Not available")]]));
    append(body, el("div", "notice", "This assistant can inspect bounded evidence and recommend a next step. It cannot silently publish, retry, approve or replace accepted data."));
    if (detailError) append(body, el("div", "notice warning", `Latest run summary is unavailable. Previously recorded events remain below.${problemSuffix(detailError)}`));
    if (eventsError) append(body, el("div", "notice warning", `Durable event retrieval failed; no prior observation has been replaced by a negative conclusion.${problemSuffix(eventsError)}`));
    if (run.error) append(body, el("div", "notice negative", `${humanise(run.error.code || "Agent run failed")}: ${run.error.message || "The durable trace records where the investigation stopped."}`));
    if (repairCount) append(body, el("div", "notice", `The assistant corrected ${formatNumber(repairCount)} malformed structured response${repairCount === 1 ? "" : "s"} before continuing. Repairs are schema-informed and bounded; every attempt remains in model invocation metadata.`));
    if (providerRetryCount) append(body, el("div", "notice", `Recovered from ${formatNumber(providerRetryCount)} incomplete model response${providerRetryCount === 1 ? "" : "s"} by requesting the complete structured result again within the original run deadline.`));
    if (failedSteps.length && run.status === "succeeded") append(body, el("div", "notice positive", `Recovered automatically from ${formatNumber(failedSteps.length)} evidence issue${failedSteps.length === 1 ? "" : "s"}. Failed attempts remain visible below and were not rewritten as successful observations.`));
    if (!steps.length) append(body, emptyState("No durable events yet", "The run exists, but no Plan, Act, Observe or Adapt event is currently available."));
    else {
      const timeline = el("ol", "timeline");
      for (const step of steps) append(timeline, traceStep(step));
      append(body, timeline);
    }
    if (["review_required", "awaiting_review"].includes(run.status)) append(body, el("div", "notice warning", "Proposed action only: a protected retry or publication is paused. Review and execution are separate human-controlled steps in Agent activity; no write has occurred."));
    if (run.final_result) append(body, panel("Evidence-backed recovery brief", "A decision-useful diagnosis grounded in the durable tool trace", recoveryBrief(run.final_result)));
    const controls = el("div", "dialog-actions"); append(controls, sharedRunLink(id, "Open durable run detail"), button("Refresh evidence", "button secondary", () => renderAgentTrace(id, host))); append(body, controls);
    host.replaceChildren(panel("Plan · Act · Observe · Adapt", "Durable events from this exact Agent activity run", body));
    host.setAttribute("aria-busy", "false");
    host.dataset.agentStatus = run.status;
    updateHistorySummary(id, run);
    state.lastAgentStatus = run.status;
    scheduleAgentPoll(id, host, run.status, detailError || eventsError ? failures + 1 : 0);
  }

  function updateHistorySummary(id, run) {
    const row = [...view.querySelectorAll("[data-agent-run-id]")].find((item) => item.dataset.agentRunId === id);
    if (!row) return;
    row.querySelector('[data-agent-field="status"]')?.replaceChildren(badge(run.status));
    const phase = row.querySelector('[data-agent-field="phase"]');
    if (phase) phase.textContent = humanise(run.latest_phase);
    const tools = row.querySelector('[data-agent-field="tools"]');
    if (tools) tools.textContent = formatNumber(run.tool_call_count);
  }

  function scheduleAgentPoll(id, host, status, failures = 0) {
    clearTimeout(state.pollTimer);
    const delay = nextAgentPollDelay(status, failures, document.hidden);
    if (delay === null) return;
    const generation = generationGuard.current();
    state.pollTimer = setTimeout(() => {
      const current = parseRoute(location.hash);
      if (generationGuard.isCurrent(generation) && current.route === "ai" && current.id === id) renderAgentTrace(id, host, failures);
    }, delay);
  }

  function resumeAgentTrace(id) {
    const host = [...view.querySelectorAll("[data-agent-trace]")].find((item) => item.dataset.agentTrace === id);
    if (host) renderAgentTrace(id, host);
    else renderAi(id);
  }

  return { renderAi, resumeAgentTrace };
}

function option(value, label) { const item = el("option", "", label); item.value = value; return item; }
function sharedRunLink(runId, label) { return link(label, `${AGENT_ACTIVITY_URL}?run=${encodeURIComponent(runId)}&feature_key=student-1-propertyscope-data-platform`, "button secondary"); }
function problemSuffix(error) { return error?.requestId ? ` Request ID ${error.requestId}.` : ""; }

function traceStep(step) {
  const phase = String(step.phase || step.event_type || "agent_event").toLowerCase();
  const item = el("li");
  const detail = el("div", "timeline-detail");
  const call = step.input?.tool_call || {};
  const result = step.output?.tool_result || step.input?.tool_result || {};
  const plan = step.output?.plan;
  const adaptation = step.output?.adaptation;
  const observation = step.output?.observation;
  const invocation = step.output?.model_invocation;
  let title = humanise(phase);
  let summary = step.summary || step.message || humanise(step.status);
  let evidence = step.evidence || step.observation || null;
  if (phase === "plan" && plan) {
    title = `Plan · ${formatNumber(plan.actions?.length || 0)} evidence call${plan.actions?.length === 1 ? "" : "s"}`;
    summary = plan.goal;
    evidence = plan;
  } else if (phase === "act" && call.tool_name) {
    title = `Act · ${humanise(call.tool_name)}`;
    summary = result.outcome === "succeeded"
      ? `Validated ${formatNumber(result.evidence_references?.length || 0)} service reference${result.evidence_references?.length === 1 ? "" : "s"}.`
      : `${humanise(result.error?.code || step.error?.code || "Evidence call failed")}: ${result.error?.message || step.error?.message || "The issue was recorded for adaptation."}`;
    evidence = { arguments: call.arguments, result };
  } else if (phase === "observe" && (result.outcome || observation)) {
    title = result.outcome === "succeeded" ? "Observe · evidence accepted" : "Observe · issue retained";
    summary = result.outcome === "succeeded"
      ? "The validated tool result is now durable evidence for the next decision."
      : `The ${humanise(result.error?.code || "evidence failure")} was passed to Adapt instead of being treated as a successful observation.`;
    evidence = { observation, tool_result: result };
  } else if (phase === "adapt" && adaptation) {
    title = `Adapt · ${humanise(adaptation.decision)}`;
    summary = adaptation.justification;
    evidence = { adaptation, model_invocation: invocation };
  }
  append(detail, el("h3", "", title), el("p", "", summary));
  if (invocation?.model) append(detail, el("span", "timeline-meta", `${invocation.provider || "model"} · ${invocation.model}${invocation.repair_count ? ` · ${invocation.repair_count} repaired response${invocation.repair_count === 1 ? "" : "s"}` : ""}${invocation.provider_retry_count ? ` · ${invocation.provider_retry_count} incomplete response retried` : ""}`));
  if (call.tool_name) append(detail, el("code", "mono timeline-tool", call.tool_name));
  if (evidence) append(detail, technicalDetails(evidence, phase === "act" ? "Inspect call and bounded evidence" : "Inspect durable phase evidence"));
  append(item, el("span", `timeline-marker ${statusTone(step.status)}`, stateLabel(step.status).symbol), detail);
  return item;
}

function recoveryBrief(result) {
  const brief = el("div", "recovery-brief");
  append(brief, el("p", "recovery-summary", result.summary || "The assistant completed a bounded evidence review."));
  if (Array.isArray(result.findings) && result.findings.length) {
    const section = el("section"); const list = el("ul", "finding-list");
    for (const finding of result.findings) append(list, el("li", "", finding));
    append(section, el("h3", "", "Key findings"), list); append(brief, section);
  }
  if (result.recommended_next_step) append(brief, resultCallout("Recommended next step", result.recommended_next_step, "recommendation"));
  if (result.safety_note) append(brief, resultCallout("Safety boundary", result.safety_note, "safety"));
  if (Array.isArray(result.evidence) && result.evidence.length) {
    const section = el("section"); const list = el("ul", "evidence-list");
    for (const reference of result.evidence) append(list, el("li", "", reference));
    append(section, el("h3", "", "Evidence cited"), list); append(brief, section);
  }
  append(brief, technicalDetails(result, "Inspect structured result"));
  return brief;
}

function resultCallout(title, text, tone) {
  const callout = el("section", `result-callout ${tone}`);
  append(callout, el("h3", "", title), el("p", "", text));
  return callout;
}
