import { createAiChat } from "../ai-chat/index.js";
import { propertyAssistantOptions } from "../integration/assistant.js";
import { createReviewClient, recordedReviewTurn, releaseReviewContext, reviewContextOptions, REVIEW_OBJECTIVES, REVIEW_SUGGESTIONS } from "../integration/ai-review.js";
import { propertyActivityUrl } from "../integration/activity.js";
import { collection, entity } from "../core/api.js";
import { append, el, link } from "../core/dom.js";
import { formatDate, formatNumber } from "../core/formats.js";
import { routeQuery } from "../core/router.js";
import { badge, disclosurePanel } from "../components/layout.js";
import { errorState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

export function createAiDiagnosisRoutes({ view, request, loading, generationGuard, rerender, announce }) {
  let active = null;
  function destroy() { active?.destroy(); active = null; }

  async function renderAi(context = "") {
    destroy();
    const routeEpoch = generationGuard.capture();
    const selectedReleaseId = context.startsWith("release:") ? context.slice("release:".length) : "";
    const selectedRunId = context && !selectedReleaseId ? context : "";
    loading("Loading AI review");
    try {
      // A saved result does not depend on the current release inventory or history feed.
      const detail = selectedRunId ? await request(`agent-runs/${encodeURIComponent(selectedRunId)}`)
        : selectedReleaseId ? await request(`dataset-releases/${encodeURIComponent(selectedReleaseId)}`) : null;
      const inventory = !context ? await request("dataset-releases?limit=100").catch(() => null) : null;
      if (!routeEpoch.isCurrent()) return;
      const recordedTurn = selectedRunId ? recordedReviewTurn(detail.body) : null;
      const linkedContext = recordedTurn?.context || (detail ? releaseReviewContext(entity(detail.body, "release")) : {});
      const options = propertyAssistantOptions({ announce, context: linkedContext });
      view.replaceChildren();
      const actions = el("nav", "button-row");
      actions.setAttribute("aria-label", "AI review navigation");
      append(actions, link("New AI review", "#ai", "button secondary"), link("Open activity history", activityUrl(selectedRunId), "button secondary"));
      if (linkedContext.release_id) append(actions, link("Back to dataset", `#releases/${linkedContext.release_id}`, "button secondary"));
      const chatHost = el("div");
      const historyHost = el("div");
      append(view, actions, chatHost, historyHost);
      let hasSavedReview = Boolean(selectedRunId);
      active = createAiChat({
        ...options, root: chatHost,
        client: createReviewClient({ request, recordedTurn, client: options.client, onCreated: (run) => {
          if (!hasSavedReview && run.id && routeEpoch.isCurrent()) {
            hasSavedReview = true;
            // Keep the live conversation mounted while making this review reloadable.
            history.replaceState(null, "", `#ai/${encodeURIComponent(run.id)}`);
          }
        } }),
        title: "AI review",
        description: "Compare datasets, understand data checks, or investigate publishing. The assistant can recommend a next step; publishing and retries stay in your control.",
        contextOptions: reviewContextOptions(inventory ? collection(inventory.body) : []), suggestions: REVIEW_SUGGESTIONS,
        initialMessage: selectedRunId ? "" : REVIEW_OBJECTIVES[routeQuery(location.hash).get("goal")] || REVIEW_OBJECTIVES.compare,
        initialTurns: recordedTurn ? [recordedTurn] : [],
        draftKey: "propertyscope:ai-review",
      });
      if (!selectedRunId && !selectedReleaseId) chatHost.querySelector(".ps-ai-chat__settings").open = true;
      request("agent-runs?limit=10").catch((error) => ({ error })).then((historyResult) => {
        if (!routeEpoch.isCurrent()) return;
        if (historyResult.error) append(historyHost, el("div", "notice warning", "AI review history is temporarily unavailable. You can continue in the assistant."));
        else {
          const history = collection(historyResult.body);
          if (history.length) append(historyHost, diagnosisHistory(history, selectedRunId));
        }
      });
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      destroy();
      view.replaceChildren(errorState(error, rerender));
    }
  }

  return { renderAi, destroy };
}

function diagnosisHistory(history, selectedRunId) {
  return disclosurePanel("Recent AI reviews", `${history.length} recorded reviews · newest first`, makeTable(
    [{ label: "Review" }, { label: "State" }, { label: "Source checks" }, { label: "Started" }, { label: "Result" }], history,
    (run) => {
      const row = el("tr");
      append(row, cell(primaryCell("Data review", String(run.id).slice(0, 8))), cell(badge(run.status)), cell(formatNumber(run.tool_call_count), "numeric"), cell(formatDate(run.created_at)), cell(link(run.id === selectedRunId ? "Viewing result" : "View result", `#ai/${run.id}`, "button secondary small")));
      return row;
    },
  ));
}

function activityUrl(runId = "") {
  return propertyActivityUrl(runId, { baseUrl: document.baseURI, activityUrl: window.PROPERTYSCOPE_AGENT_ACTIVITY_URL, returnTo: `/features/data-platform/${location.hash}` });
}
