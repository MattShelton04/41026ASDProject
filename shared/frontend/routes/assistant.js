import { createAiChat, createAssistantClient } from "../ai-chat/index.js";
import { append, el, link, notice } from "../core.js";

export const SHARED_ASSISTANT_SCOPES = Object.freeze([
  { id: "application", label: "Application guidance", description: "Help navigating PropertyScope. This assistant’s evidence tools currently cover Property data, not every research area." },
  { id: "feature", label: "Property data", description: "Property records, sources, updates, releases, quality and coverage." },
]);

export function sharedAssistantSuggestions(scope) {
  return scope === "application"
    ? ["What can PropertyScope help me research?", "Which research areas are available now?", "How does AI activity stay reviewable?"]
    : ["Which Property data sources are available?", "Explain candidate and accepted datasets.", "Find an accepted property record in Parramatta."];
}

function assistantScope(hash) {
  const value = new URLSearchParams(String(hash).split("?")[1] || "").get("scope");
  return value === "feature" ? "feature" : "application";
}

function activityHref(runId) {
  const params = new URLSearchParams({
    feature_key: "student-1-propertyscope-data-platform",
    feature_label: "Property data",
    return_to: "/#assistant",
    run: runId,
  });
  return `/operations/ai-mode/?${params}`;
}

export function createAssistantRoute({ announce = () => {} } = {}) {
  let active = null;
  return (root) => {
    active?.destroy();
    root.classList.add("shared-assistant-page");
    const client = createAssistantClient({ apiRoot: "/api/data-platform/v1/assistant" });
    active = createAiChat({
      root,
      client,
      draftKey: "propertyscope:shared-assistant",
      initialScope: assistantScope(location.hash),
      scopes: SHARED_ASSISTANT_SCOPES,
      suggestions: sharedAssistantSuggestions,
      activityHref,
      announce,
      title: "Better questions. Visible evidence.",
      description: "Ask PropertyScope about your workspace and Property data. Follow the sources, keep the limits in view and inspect the activity behind each answer.",
    });
    const guide = el("aside", "assistant-guide");
    guide.setAttribute("aria-label", "Assistant scope and evidence guide");
    append(guide, el("p", "ps-eyebrow", "Alongside the answer"), el("h2", "", "Keep the evidence close."));
    for (const [number, title, copy] of [
      ["01", "Check the scope", "Application guidance and Property data currently use the Property data assistant. Other research areas’ tools are not connected here."],
      ["02", "Follow the source", "Source references appear with a supported answer. Open a reference to inspect the evidence used for that turn."],
      ["03", "Leave room for unknown", "Missing or partial evidence stays explicit. An unanswered question is a useful next step."],
    ]) {
      const item = el("section", "assistant-guide__item");
      append(item, el("span", "mono", number), el("h3", "", title), el("p", "", copy));
      append(guide, item);
    }
    append(guide, link("Sources & history →", "#evidence"), link("Check data status →", "#system-status"));
    append(root.querySelector(".ps-ai-chat"), guide);
    const controller = active;
    client.capabilities().then(({ body }) => {
      if (active !== controller || !body?.suggested_questions?.length) return;
      controller.setSuggestions((scope) => scope === "application"
        ? body.suggested_questions.slice(0, 4)
        : sharedAssistantSuggestions(scope));
    }).catch(() => {
      if (active !== controller) return;
      root.querySelector(".ps-ai-chat__intro")?.after(
        notice("warning", "Capability guide unavailable", "Current scope guidance could not be refreshed. You can try a question, but service availability has not been confirmed."),
      );
    });
    return controller;
  };
}
