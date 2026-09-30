import { createFeatureAssistant } from "./ai-chat/index.js";
import { API_BASE } from "./api.js";

export const assistantScopes = [
  { id: "guidance", label: "Workspace guidance (RAG)", description: "Ask about the buyer workflow using public project guidance." },
  { id: "case", label: "Selected case records and workspace guidance", description: "Approved read-only records for this case and Student 5 workspace guidance." },
];

export const CASE_SUMMARY_MESSAGE = "Summarise this case";

export function setSummaryVisibility(button, selected) {
  if (!button) return;
  button.hidden = !selected;
  button.disabled = !selected;
}

// A different selected case starts a separate conversation, even during an active run.
// Never carry another case's history or attached context into the new conversation.
export function createBuyerAssistant(root, create = createFeatureAssistant, selectedLabel = null) {
  let assistant = null;
  let selected;
  let selectedContext = {};
  return {
    select(item) {
      const id = item?.id || null;
      selectedContext = item ? { buyer_case_id: item.id, display_label: item.name } : {};
      if (selectedLabel) selectedLabel.textContent = item ? `Selected case: ${item.name}` : "No case selected. Open a buyer case to summarise its records.";
      if (assistant && selected === id) { assistant.controller.setContext(selectedContext); return; }
      assistant?.controller.destroy();
      selected = id;
      assistant = create({
        root, apiRoot: `${API_BASE}/assistant`,
        featureKey: "student-5-buyer-journey", featureLabel: "Buyer workspace",
        returnTo: "/features/buyer-workspaces/", initialScope: id ? "case" : "guidance",
        context: selectedContext,
        scopes: assistantScopes.filter((scope) => scope.id === (id ? "case" : "guidance")),
        suggestions: ["How do I manage my shortlist?", "What do journey stages mean?", "What are the limits of the evidence?"],
      });
    },
    summarise() {
      // Use the same native scope-change and form-submit path as typed questions.
      // Do not bypass the shared controller's busy, history or cancellation guards.
      const scope = root.querySelector(".ps-ai-chat__scope select");
      const form = root.querySelector("form");
      if (!selected || !assistant || !scope || scope.disabled || !form) return false;
      scope.value = "case";
      scope.dispatchEvent(new Event("change", { bubbles: true }));
      assistant.controller.setContext(selectedContext);
      assistant.controller.setDraft(CASE_SUMMARY_MESSAGE);
      form.requestSubmit();
      return true;
    },
    destroy() { assistant?.controller.destroy(); assistant = null; },
  };
}
