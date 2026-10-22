import { createMultiAgentClient, createMultiAgentPanel } from "./multi-agent/index.js";
import { API_BASE } from "./api.js";

// Reuse the shared lifecycle, decision controls, activity and replay. A case change aborts
// the old view's polling; it does not cancel the person's durable workflow on the server.
export function createCaseActionPlan(section, createPanel = createMultiAgentPanel, createClient = createMultiAgentClient) {
  let panel = null;
  let selected = null;
  const runs = new Map();
  return {
    select(item) {
      section.hidden = !item;
      if (!item) {
        selected = null;
        panel?.destroy();
        panel = null;
        section.querySelector("[data-action-plan-root]").replaceChildren();
        return;
      }
      section.querySelector("[data-action-plan-case]").textContent = `Selected case: ${item.name}`;
      if (selected === item.id) return;
      panel?.destroy();
      selected = item.id;
      const caseId = item.id;
      panel = createPanel({
        root: section.querySelector("[data-action-plan-root]"),
        client: createClient({apiRoot: `${API_BASE}/buyer-cases/${encodeURIComponent(caseId)}/evidence-reviews`}),
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
    destroy() { selected = null; panel?.destroy(); panel = null; runs.clear(); },
  };
}
