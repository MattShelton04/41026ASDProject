import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatDate, formatNumber, humanise, researchAreaLabel, stateLabel, statusTone } from "../core/formats.js?v=18";
import { createSubmissionGuard } from "../core/forms.js?v=18";
import { createLatestRequestGuard, nextAgentPollDelay } from "../core/polling.js?v=18";
import { parseRoute, routeQuery } from "../core/router.js?v=7";
import { badge, detailList, disclosurePanel, pageHeading, panel, technicalDetails } from "../components/layout.js?v=17";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

const AGENT_ACTIVITY_URL = window.PROPERTYSCOPE_AGENT_ACTIVITY_URL
  || (window.location.pathname.startsWith("/features/data-platform/")
    ? "/operations/ai-mode/"
    : `${window.location.protocol}//${window.location.hostname}:5005/operations/ai-mode/`);
const OBJECTIVES = Object.freeze({
  compare: "Compare this unpublished version with the current published version. Check schema, record count, coverage, quality and publishing differences. Make clear when information is missing. Recommend one next step for human review. Do not publish or change data.",
  quality: "Review this unpublished version and its exact data update. Explain each required or failed data check and its impact. Make clear when information is missing. Recommend one retry option for human review. Do not execute it.",
  consumer: "Review this unpublished version, its publishing records and the current published version. Explain each failed or retryable delivery. Make clear when a receipt is missing. Recommend one next step for human review. Do not publish or change data.",
});

function annotateTraceRefreshState(host) {
  const disclosureKeys = new Map();
  for (const details of host.querySelectorAll("details")) {
    const label = details.querySelector("summary")?.textContent?.trim() || "Details";
    const count = disclosureKeys.get(label) || 0;
    disclosureKeys.set(label, count + 1);
    details.dataset.traceRefreshKey = `${label}:${count}`;
  }
  const focusKeys = new Map();
  for (const target of host.querySelectorAll("a[href], button, summary")) {
    const base = target.matches("a[href]")
      ? `link:${target.getAttribute("href")}`
      : target.matches("summary")
        ? `summary:${target.closest("details")?.dataset.traceRefreshKey || target.textContent?.trim()}`
        : `button:${target.textContent?.trim()}`;
    const count = focusKeys.get(base) || 0;
    focusKeys.set(base, count + 1);
    target.dataset.traceRefreshFocusKey = `${base}:${count}`;
  }
}

function captureTraceRefreshState(host) {
  const active = document.activeElement;
  return {
    focusKey: host.contains(active) ? active.dataset.traceRefreshFocusKey || "" : "",
    disclosures: new Map(
      [...host.querySelectorAll("details[data-trace-refresh-key]")]
        .map((details) => [details.dataset.traceRefreshKey, details.open]),
    ),
  };
}

function restoreTraceRefreshState(host, snapshot) {
  for (const details of host.querySelectorAll("details[data-trace-refresh-key]")) {
    if (snapshot.disclosures.has(details.dataset.traceRefreshKey)) {
      details.open = snapshot.disclosures.get(details.dataset.traceRefreshKey);
    }
  }
  if (!snapshot.focusKey) return;
  const target = [...host.querySelectorAll("[data-trace-refresh-focus-key]")]
    .find((candidate) => candidate.dataset.traceRefreshFocusKey === snapshot.focusKey);
  target?.focus({ preventScroll: true });
}

export function createAiDiagnosisRoutes({ view, request, loading, mutate, state, generationGuard, rerender }) {
  const refreshGuard = createLatestRequestGuard();
  async function renderAi(context = "") {
    const routeEpoch = generationGuard.capture();
    loading("Loading AI review");
    try {
      const [releasesResult, historyResult] = await Promise.all([
        request("dataset-releases?limit=100"),
        request("agent-runs?limit=10").catch((error) => ({ error, body: { items: [] } })),
      ]);
      if (!routeEpoch.isCurrent()) return;
      const releases = collection(releasesResult.body);
      const actionable = releases.filter((release) => !["accepted", "superseded", "draft"].includes(release.status));
      const selectedReleaseId = context.startsWith("release:") ? context.slice("release:".length) : "";
      const selectedRelease = releases.find((release) => release.id === selectedReleaseId);
      const candidates = selectedRelease
        ? [selectedRelease, ...actionable.filter((release) => release.id !== selectedRelease.id).slice(0, 7)]
        : actionable.slice(0, 8);
      const history = collection(historyResult.body);
      const selectedAgentRun = context && !context.startsWith("release:") ? context : "";
      view.replaceChildren();
      append(view, pageHeading("Data review", "AI review", "Ask the assistant to compare an unpublished dataset with the version currently in use. You remain in control of every publishing decision.", selectedAgentRun ? [link("New AI review", "#ai", "button secondary"), sharedRunLink(selectedAgentRun, "Open activity history")] : [link("Open activity history", activityUrl(), "button secondary")]));
      append(view, el("div", "notice", "AI review is optional. Property search and data management continue to work if the model is unavailable."));
      if (selectedAgentRun) {
        const traceHost = el("div");
        traceHost.dataset.agentTrace = selectedAgentRun;
        traceHost.setAttribute("aria-live", "polite");
        append(view, traceHost);
        await renderAgentTrace(selectedAgentRun, traceHost);
        if (!routeEpoch.isCurrent()) return;
      }
      if (!selectedAgentRun) append(view, await diagnosisForm(candidates, context));
      if (historyResult.error) append(view, el("div", "notice warning", `AI review history is temporarily unavailable.${problemSuffix(historyResult.error)}`));
      else if (!history.length) append(view, emptyState("No AI reviews yet", "Start a review above. Its result will remain available in activity history."));
      else append(view, diagnosisHistory(history, selectedAgentRun));
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren(errorState(error, rerender));
    }
  }

  function diagnosisHistory(history, selectedAgentRun) {
    return disclosurePanel("Recent AI reviews", `${history.length} recorded reviews · newest first`, makeTable(
      [{ label: "Review" }, { label: "State" }, { label: "Source checks" }, { label: "Started" }, { label: "Result" }], history,
      (run) => {
        const row = el("tr"); row.dataset.agentRunId = run.id;
        const status = cell(badge(run.status)); status.dataset.agentField = "status";
        const tools = cell(formatNumber(run.tool_call_count), "numeric"); tools.dataset.agentField = "tools";
        append(row, cell(primaryCell(diagnosisTitle(run), `Read-only review · ${String(run.id).slice(0, 8)}`)), status, tools, cell(formatDate(run.created_at)), cell(link(run.id === selectedAgentRun ? "Viewing result" : "View result", `#ai/${run.id}`, "button secondary small"), "actions-cell"));
        return row;
      },
    ));
  }

  async function diagnosisForm(candidates, context) {
    const host = el("section", "panel"); const heading = el("div", "panel-heading"); const copy = el("div");
    append(copy, el("h2", "", "Start an AI review"), el("p", "", "The assistant reads recorded data checks and recommends a next step. It cannot publish changes.")); append(heading, copy); const body = el("div", "panel-body"); append(host, heading, body);
    if (!candidates.length) { append(body, emptyState("Nothing needs review", "An unpublished or rejected dataset will appear here when it needs attention.")); return host; }
    const form = el("form", "form-grid");
    const releaseLabel = el("label", "wide"); releaseLabel.htmlFor = "diagnosis-release"; append(releaseLabel, el("span", "", "Dataset to review (required)")); const releaseSelect = el("select"); releaseSelect.id = "diagnosis-release"; releaseSelect.required = true;
    for (const release of candidates) { const option = el("option", "", `${humanise(release.dataset_id)} · ${release.release_version} · ${humanise(release.status)}`); option.value = release.id; option.selected = context === `release:${release.id}`; append(releaseSelect, option); }
    append(releaseLabel, releaseSelect);
    const objectiveLabel = el("label", "wide"); objectiveLabel.htmlFor = "diagnosis-objective"; append(objectiveLabel, el("span", "", "What should the AI check? (required)")); const objective = el("select"); objective.id = "diagnosis-objective"; objective.required = true;
    append(objective, option("compare", "Compare with the published version"), option("quality", "Explain failed data checks"), option("consumer", "Explain a publishing failure")); append(objectiveLabel, objective);
    const requestedGoal = routeQuery(location.hash).get("goal");
    if (Object.hasOwn(OBJECTIVES, requestedGoal)) objective.value = requestedGoal;
    const scope = el("div", "notice wide"); scope.setAttribute("aria-live", "polite");
    const updateScope = () => { const release = candidates.find((item) => item.id === releaseSelect.value) || candidates[0]; scope.replaceChildren(document.createTextNode(`The AI will review ${humanise(release.dataset_id)} ${release.release_version}, its data checks and the current published version. It can recommend a next step, but it cannot publish or change data.`), technicalDetails({ release_id: release.id, ingestion_run_id: release.ingestion_run_id }, "Review references")); };
    releaseSelect.addEventListener("change", updateScope); updateScope();
    const submit = button("Start AI review", "button primary"); submit.type = "submit";
    append(form, releaseLabel, objectiveLabel, scope, submit); append(body, form);
    const progress = el("div");
    const submission = createSubmissionGuard(async () => {
      progress.className = "notice"; progress.textContent = "Starting AI review…"; body.prepend(progress);
      try {
        const result = await mutate(`dataset-releases/${releaseSelect.value}/agent-runs`, { body: { objective: OBJECTIVES[objective.value] }, success: "AI review started" });
        const run = entity(result, "agent_run"); location.hash = `#ai/${run.id || result.id}`;
      } catch (error) {
        progress.className = "notice warning"; progress.textContent = `${error.status === 503 ? "AI review is temporarily unavailable. Property search and data management still work. Your selected dataset and review goal are unchanged; retry when ready." : `${error.message} Your selected dataset and review goal are unchanged; correct the issue or retry.`}${problemSuffix(error)}`;
      }
    }, (pending) => {
      submit.disabled = pending;
      submit.textContent = pending ? "Starting review…" : "Start AI review";
      submit.setAttribute("aria-busy", String(pending));
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!form.reportValidity()) return;
      submission.submit();
    });
    return host;
  }

  async function renderAgentTrace(id, host, failures = 0) {
    const refresh = refreshGuard.next();
    const routeEpoch = generationGuard.capture();
    const isCurrent = () => refreshGuard.isCurrent(refresh)
      && routeEpoch.isCurrent()
      && parseRoute(location.hash).route === "ai"
      && parseRoute(location.hash).id === id;
    annotateTraceRefreshState(host);
    const refreshState = captureTraceRefreshState(host);
    host.setAttribute("aria-busy", "true");
    const [detailResult, eventsResult] = await Promise.allSettled([
      request(`agent-runs/${id}`), request(`agent-runs/${id}/events${queryString({ after: 0, limit: 100 })}`),
    ]);
    if (!isCurrent()) return;
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
    append(body, detailList([["State", badge(run.status)], ["Evidence calls", formatNumber(run.tool_call_count)], ["Iterations", formatNumber(run.iteration_count)]]));
    if (run.final_result) append(body, panel("Recommended next step", "AI summary for your review", recoveryBrief(run.final_result)));
    append(body, el("div", "notice", "The AI can read recorded checks and recommend a next step. It cannot publish, retry or approve changes."));
    if (detailError) append(body, el("div", "notice warning", `Latest run summary is unavailable. Previously recorded events remain below.${problemSuffix(detailError)}`));
    if (eventsError) append(body, el("div", "notice warning", `Some activity details could not be loaded. Previously recorded results have not been changed.${problemSuffix(eventsError)}`));
    if (run.error) append(body, el("div", "notice negative", `${humanise(run.error.code || "AI review failed")}: ${run.error.message || "Activity history shows where the review stopped."}`));
    if (["failed", "cancelled"].includes(run.status)) append(body, el("div", "notice warning", "This review is a retained activity record and cannot be changed. Start a new AI review to try again with the current data and tool contracts."));
    if (repairCount) append(body, el("div", "notice", `The assistant corrected ${formatNumber(repairCount)} invalid response${repairCount === 1 ? "" : "s"} before continuing. Each attempt remains available in the technical details.`));
    if (providerRetryCount) append(body, el("div", "notice", `Recovered from ${formatNumber(providerRetryCount)} incomplete model response${providerRetryCount === 1 ? "" : "s"} by requesting the complete structured result again within the original run deadline.`));
    if (failedSteps.length && run.status === "succeeded") append(body, el("div", "notice positive", `The review recovered from ${formatNumber(failedSteps.length)} source-check issue${failedSteps.length === 1 ? "" : "s"}. Earlier failed attempts remain in the activity details.`));
    if (!steps.length) append(body, emptyState("No activity yet", "The review has started, but no steps are available yet."));
    else {
      const timeline = el("ol", "timeline");
      for (const step of steps) append(timeline, traceStep(step));
      append(body, run.final_result
        ? disclosurePanel("How the assistant reached this answer", "Recorded review steps and source checks", timeline)
        : panel("Review progress", "Recorded steps and source checks", timeline));
    }
    if (["review_required", "awaiting_review"].includes(run.status)) append(body, el("div", "notice warning", "Proposed action only: a protected retry or publication is paused. Review and execution are separate human-controlled steps in Agent activity; no write has occurred."));
    append(body, technicalDetails({ model_profile: run.model_profile, agent_run_id: run.id || id, request_id: run.request_id || detailResult.value?.requestId || null }, "Technical run references"));
    const controls = el("div", "dialog-actions"); append(controls, sharedRunLink(id, "Open full activity details"), button("Refresh result", "button secondary", () => renderAgentTrace(id, host))); append(body, controls);
    const presentation = reviewPresentation(run);
    host.replaceChildren(panel(presentation.title, presentation.subtitle, body));
    annotateTraceRefreshState(host);
    restoreTraceRefreshState(host, refreshState);
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
    const tools = row.querySelector('[data-agent-field="tools"]');
    if (tools) tools.textContent = formatNumber(run.tool_call_count);
  }

  function scheduleAgentPoll(id, host, status, failures = 0) {
    clearTimeout(state.pollTimer);
    const delay = nextAgentPollDelay(status, failures, document.hidden);
    if (delay === null) return;
    const routeEpoch = generationGuard.capture();
    state.pollTimer = setTimeout(() => {
      const current = parseRoute(location.hash);
      if (routeEpoch.isCurrent() && current.route === "ai" && current.id === id) renderAgentTrace(id, host, failures);
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
function reviewPresentation(run) {
  if (run.final_result) return { title: "AI review result", subtitle: "Based on recorded Feature 1 checks" };
  if (run.status === "failed") return { title: "AI review failed", subtitle: "Recorded evidence shows where the review stopped" };
  if (run.status === "cancelled") return { title: "AI review stopped", subtitle: "Recorded evidence remains available for inspection" };
  if (["review_required", "awaiting_review"].includes(run.status)) return { title: "AI review needs review", subtitle: "A proposed action is waiting for a human decision" };
  if (run.status === "succeeded") return { title: "AI review complete", subtitle: "Recorded Feature 1 checks are available below" };
  return { title: "AI review in progress", subtitle: "Based on recorded Feature 1 checks" };
}
function diagnosisTitle(run) {
  const objective = String(run.objective_preview || "").toLowerCase();
  if (objective.includes("quality")) return "Quality-check investigation";
  if (objective.includes("consumer")) return "Consumer delivery investigation";
  if (objective.includes("compare")) return "Candidate comparison";
  return "Data review";
}
function activityUrl(runId = "") {
  const url = new URL(AGENT_ACTIVITY_URL, window.location.href);
  url.searchParams.set("feature_key", "student-1-propertyscope-data-platform");
  url.searchParams.set("feature_label", "Property data");
  url.searchParams.set("return_to", "/features/data-platform/#properties");
  if (runId) url.searchParams.set("run", runId);
  return url.href;
}
function sharedRunLink(runId, label) { return link(label, activityUrl(runId), "button secondary"); }
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
    title = `Review plan · ${formatNumber(plan.actions?.length || 0)} source check${plan.actions?.length === 1 ? "" : "s"}`;
    summary = plan.goal;
    evidence = plan;
  } else if (phase === "act" && call.tool_name) {
    title = `Source check · ${humanise(call.tool_name)}`;
    summary = result.outcome === "succeeded"
      ? `Validated ${formatNumber(result.evidence_references?.length || 0)} service reference${result.evidence_references?.length === 1 ? "" : "s"}.`
      : `${humanise(result.error?.code || step.error?.code || "Source check failed")}: ${result.error?.message || step.error?.message || "The issue was recorded before the review continued."}`;
    evidence = { arguments: call.arguments, result };
  } else if (phase === "observe" && (result.outcome || observation)) {
    title = result.outcome === "succeeded" ? "Result recorded" : "Issue recorded";
    summary = result.outcome === "succeeded"
      ? "The source result was recorded for the next decision."
      : `The ${humanise(result.error?.code || "source failure")} was kept as an issue instead of being treated as a successful result.`;
    evidence = { observation, tool_result: result };
  } else if (phase === "adapt" && adaptation) {
    title = `Next decision · ${humanise(adaptation.decision)}`;
    summary = adaptation.justification;
    evidence = { adaptation, model_invocation: invocation };
  }
  append(detail, el("h3", "", title), el("p", "", summary));
  if (invocation?.model) append(detail, el("span", "timeline-meta", `${invocation.provider || "model"} · ${invocation.model}${invocation.repair_count ? ` · ${invocation.repair_count} repaired response${invocation.repair_count === 1 ? "" : "s"}` : ""}${invocation.provider_retry_count ? ` · ${invocation.provider_retry_count} incomplete response retried` : ""}`));
  if (call.tool_name) append(detail, el("code", "mono timeline-tool", call.tool_name));
  if (evidence) append(detail, technicalDetails(evidence, phase === "act" ? "Inspect source call" : "Inspect step details"));
  append(item, el("span", `timeline-marker ${statusTone(step.status)}`, stateLabel(step.status).symbol), detail);
  return item;
}

function recoveryBrief(result) {
  const brief = el("div", "recovery-brief");
  append(brief, el("p", "recovery-summary", result.summary || "The assistant completed its review."));
  if (Array.isArray(result.findings) && result.findings.length) {
    const section = el("section"); const list = el("ul", "finding-list");
    for (const finding of result.findings) append(list, el("li", "", finding));
    append(section, el("h3", "", "Key findings"), list); append(brief, section);
  }
  if (result.recommended_next_step) append(brief, resultCallout("Recommended next step", result.recommended_next_step, "recommendation"));
  if (result.safety_note) append(brief, resultCallout("What did not change", result.safety_note, "safety"));
  if (Array.isArray(result.evidence) && result.evidence.length) {
    const section = el("section"); const list = el("ul", "evidence-list");
    for (const reference of result.evidence) append(list, el("li", "", reference));
    append(section, el("h3", "", "Sources used"), list); append(brief, section);
  }
  append(brief, technicalDetails(result, "Inspect structured result"));
  return brief;
}

function resultCallout(title, text, tone) {
  const callout = el("section", `result-callout ${tone}`);
  append(callout, el("h3", "", title), el("p", "", text));
  return callout;
}
