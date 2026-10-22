import { createMultiAgentClient, createMultiAgentPanel } from "./multi-agent/index.js";
import { API_BASE } from "./api.js";
import { createLatestTask, requestJsonResponse } from "./browser/index.js";

async function workflowCapabilities(apiRoot, { signal }) {
  const { body } = await requestJsonResponse(globalThis.fetch.bind(globalThis), `${apiRoot}/capabilities`, { signal });
  return body;
}

// Reuse the shared lifecycle, decision controls, activity and replay. A case change aborts
// the old view's polling; it does not cancel the person's durable workflow on the server.
export function createCaseActionPlan(section, createPanel = createMultiAgentPanel, createClient = createMultiAgentClient, getCapabilities = workflowCapabilities) {
  let panel = null;
  let selected = null;
  const runs = new Map();
  const availability = createLatestTask();
  const root = section.querySelector("[data-action-plan-root]");
  function status(message) {
    root.replaceChildren();
    root.setAttribute("role", "status");
    root.textContent = message;
  }
  return {
    async select(item) {
      section.hidden = !item;
      if (!item) {
        availability.cancel();
        selected = null;
        panel?.destroy();
        panel = null;
        section.querySelector("[data-action-plan-root]").replaceChildren();
        return;
      }
      section.querySelector("[data-action-plan-case]").textContent = `Selected case: ${item.name}`;
      if (selected === item.id) return;
      panel?.destroy();
      panel = null;
      selected = item.id;
      const caseId = item.id;
      const apiRoot = `${API_BASE}/buyer-cases/${encodeURIComponent(caseId)}/evidence-reviews`;
      const task = availability.start();
      status("Checking action-plan availability...");
      try {
        const capabilities = await getCapabilities(apiRoot, { signal: task.signal });
        if (!task.isCurrent()) return;
        if (typeof capabilities?.enabled !== "boolean") throw new Error("Invalid capabilities");
        if (!capabilities.enabled) {
          status("AI action plans are not enabled in this deployment. Your case records remain available.");
          return;
        }
      } catch (error) {
        if (!task.isCurrent() || error?.name === "AbortError") return;
        status("Action-plan availability could not be checked. Your case records remain available.");
        return;
      }
      root.replaceChildren();
      root.removeAttribute("role");
      panel = createPanel({
        root,
        client: createClient({apiRoot}),
        title: "Buyer case action plan",
        description: "Review proposed follow-ups and supporting evidence, then record your decision.",
        initialInput: {buyer_case_id: caseId},
        hiddenInputs: ["buyer_case_id"],
        runId: runs.get(caseId) || null,
        labels: {
          start: "Prepare an action plan",
          decisionSafety: "Your decision records a recommendation only. Case records and tasks are unchanged.",
        },
        onRunChange(run) {
          if (selected !== caseId || !run?.id) return;
          runs.set(caseId, run.id);
          if (runs.size > 20) runs.delete(runs.keys().next().value);
        },
      });
    },
    destroy() { availability.cancel(); selected = null; panel?.destroy(); panel = null; runs.clear(); },
  };
}
