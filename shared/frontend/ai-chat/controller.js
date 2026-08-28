import { append, el } from "../browser/index.js";
import { defaultSuggestions, findAssistantScope, normalizeAssistantScopes } from "./definitions.js";
import { renderAssistantTurn, contextSummary } from "./components.js";
import { normalizeTurnDetail } from "./formats.js";
import { mergeAssistantEvents, nextAssistantPollDelay } from "./polling.js";

function runFromCreate(payload) {
  return normalizeTurnDetail(payload);
}

export function createAiChat({
  root,
  client,
  initialScope = "feature",
  context = {},
  activityHref = () => "/operations/ai-mode/",
  announce = () => {},
  title = "Ask PropertyScope",
  description = "Ask about the application or use the available research tools. Every message creates a reviewable activity run.",
  scopes = undefined,
  suggestions = defaultSuggestions,
  assistantLabel = "PropertyScope assistant",
  welcomeTitle = "What would you like to understand?",
  welcomeMessage = "I can inspect available feature data through recorded, allowlisted tools. I will show the durable run and evidence for each answer.",
  composerLabel = "Message PropertyScope assistant",
  placeholder = "Ask about this research area, its evidence or an available record…",
} = {}) {
  if (!root || !client) throw new TypeError("createAiChat requires root and client");
  const scopeDefinitions = normalizeAssistantScopes(scopes);
  const state = {
    scope: findAssistantScope(initialScope, scopeDefinitions).id,
    context: { ...context },
    turns: [],
    timers: new Map(),
    destroyed: false,
    suggestionProvider: suggestions,
  };
  const shell = el("section", "ps-ai-chat");
  const intro = el("header", "ps-ai-chat__intro");
  append(intro, el("p", "ps-eyebrow", "Grounded AI workspace"), el("h1", "", title), el("p", "", description));
  const scopeHost = el("div", "ps-ai-chat__scope");
  const scopeLabel = el("label");
  scopeLabel.htmlFor = "ps-ai-chat-scope";
  append(scopeLabel, el("span", "", "Assistant scope"));
  const scope = el("select");
  scope.id = "ps-ai-chat-scope";
  for (const definition of scopeDefinitions) {
    const option = el("option", "", definition.label);
    option.value = definition.id;
    option.selected = definition.id === state.scope;
    append(scope, option);
  }
  const scopeDescription = el("p", "", findAssistantScope(state.scope, scopeDefinitions).description);
  append(scopeLabel, scope, scopeDescription);
  append(scopeHost, scopeLabel, contextSummary(state.context));

  const transcript = el("div", "ps-ai-chat__transcript");
  transcript.setAttribute("aria-label", "Assistant conversation");
  const welcome = el("section", "ps-ai-chat__welcome");
  append(welcome, el("span", "ps-ai-chat__speaker", assistantLabel), el("h2", "", welcomeTitle), el("p", "", welcomeMessage));
  const suggestionsHost = el("div", "ps-ai-chat__suggestions");
  append(welcome, suggestionsHost);
  append(transcript, welcome);

  const form = el("form", "ps-ai-chat__composer");
  const textareaLabel = el("label");
  textareaLabel.htmlFor = "ps-ai-chat-message";
  textareaLabel.className = "ps-ai-chat__composer-label";
  textareaLabel.textContent = composerLabel;
  const textarea = el("textarea");
  textarea.id = "ps-ai-chat-message";
  textarea.name = "message";
  textarea.rows = 3;
  textarea.minLength = 2;
  textarea.maxLength = 2000;
  textarea.required = true;
  textarea.placeholder = placeholder;
  const composerFooter = el("div", "ps-ai-chat__composer-footer");
  const helper = el("p", "", "Enter sends · Shift+Enter adds a line · no hidden conversation memory");
  const submit = el("button", "ps-button ps-button--primary", "Send message");
  submit.type = "submit";
  append(composerFooter, helper, submit);
  append(form, textareaLabel, textarea, composerFooter);

  function renderSuggestions() {
    suggestionsHost.replaceChildren();
    const provider = state.suggestionProvider;
    const suggestedMessages = typeof provider === "function" ? provider(state.scope) : provider;
    for (const suggestion of suggestedMessages || []) {
      const button = el("button", "ps-ai-chat__suggestion", suggestion);
      button.type = "button";
      button.addEventListener("click", () => {
        textarea.value = suggestion;
        textarea.focus();
      });
      append(suggestionsHost, button);
    }
  }

  function renderTranscript() {
    const disclosureState = new Map(
      [...transcript.querySelectorAll("details[data-disclosure-key]")]
        .map((details) => [details.dataset.disclosureKey, details.open]),
    );
    const active = document.activeElement;
    const activeKey = transcript.contains(active) ? active.dataset.transcriptFocusKey || "" : "";
    const turns = state.turns.map((turn) => renderAssistantTurn(turn, {
      activityHref,
      onCancel: cancelTurn,
      onRetry: retryTurn,
    }));
    transcript.replaceChildren(welcome, ...turns);
    for (const [turnIndex, article] of turns.entries()) {
      const runKey = state.turns[turnIndex].id || state.turns[turnIndex].clientId;
      for (const [detailIndex, details] of [...article.querySelectorAll("details")].entries()) {
        details.dataset.disclosureKey = `${runKey}:${detailIndex}`;
        if (disclosureState.has(details.dataset.disclosureKey)) details.open = disclosureState.get(details.dataset.disclosureKey);
      }
      for (const [focusIndex, target] of [...article.querySelectorAll("a, button, summary")].entries()) {
        target.dataset.transcriptFocusKey = `${runKey}:${focusIndex}`;
      }
    }
    if (activeKey) {
      [...transcript.querySelectorAll("[data-transcript-focus-key]")]
        .find((target) => target.dataset.transcriptFocusKey === activeKey)
        ?.focus({ preventScroll: true });
    }
  }

  function schedulePoll(turn, failures = 0) {
    clearTimeout(state.timers.get(turn.clientId));
    const delay = nextAssistantPollDelay(turn.run?.status, failures, document.hidden);
    if (delay === null || state.destroyed || !turn.id) return;
    const timer = setTimeout(() => pollTurn(turn, failures), delay);
    state.timers.set(turn.clientId, timer);
  }

  async function pollTurn(turn, failures = 0) {
    if (state.destroyed || !turn.id) return;
    try {
      const previousStatus = turn.run?.status;
      const [detailResult, eventsResult] = await Promise.all([
        client.getTurn(turn.id),
        client.getEvents(turn.id, turn.cursor || 0),
      ]);
      turn.run = normalizeTurnDetail(detailResult.body);
      const page = Array.isArray(eventsResult.body?.items) ? eventsResult.body.items : [];
      const merged = mergeAssistantEvents(turn.events, page);
      turn.events = merged.items;
      turn.cursor = Math.max(merged.cursor, Number(eventsResult.body?.next_cursor || 0));
      turn.pollWarning = null;
      renderTranscript();
      if (turn.run.status !== previousStatus) announce(`Assistant turn ${turn.run.status}.`);
      schedulePoll(turn, 0);
    } catch (error) {
      turn.pollWarning = error;
      renderTranscript();
      schedulePoll(turn, failures + 1);
    }
  }

  async function submitMessage(message, existing = null) {
    const turn = existing || {
      clientId: globalThis.crypto?.randomUUID?.() || `turn-${Date.now()}-${state.turns.length}`,
      message,
      scope: state.scope,
      context: { ...state.context },
      run: { status: "queued" },
      events: [],
      cursor: 0,
    };
    if (!existing) state.turns.push(turn);
    turn.error = null;
    renderTranscript();
    submit.disabled = true;
    submit.setAttribute("aria-busy", "true");
    announce("Creating a durable assistant run.");
    try {
      const result = await client.createTurn({ message: turn.message, scope: turn.scope, context: turn.context });
      turn.run = runFromCreate(result.body);
      turn.id = turn.run.id || result.body?.id;
      if (!turn.id) throw new Error("The assistant did not return a run identifier.");
      renderTranscript();
      announce(`Assistant run ${turn.id} created.`);
      schedulePoll(turn);
    } catch (error) {
      turn.error = error;
      turn.run = { status: "failed" };
      renderTranscript();
      announce("The assistant turn could not start.");
    } finally {
      submit.disabled = false;
      submit.setAttribute("aria-busy", "false");
    }
  }

  function retryTurn(turn) {
    submitMessage(turn.message, turn);
  }

  async function cancelTurn(turn) {
    if (!turn.id) return;
    try {
      const result = await client.cancelTurn(turn.id);
      turn.run = normalizeTurnDetail(result.body);
      turn.cancelWarning = null;
      renderTranscript();
      schedulePoll(turn);
    } catch (error) {
      turn.cancelWarning = error;
      renderTranscript();
      announce("Cancellation could not be requested.");
    }
  }

  scope.addEventListener("change", () => {
    state.scope = findAssistantScope(scope.value, scopeDefinitions).id;
    scopeDescription.textContent = findAssistantScope(state.scope, scopeDefinitions).description;
    renderSuggestions();
  });
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (!form.reportValidity()) return;
    const message = textarea.value.trim();
    textarea.value = "";
    submitMessage(message);
  });

  renderSuggestions();
  append(shell, intro, scopeHost, transcript, form);
  root.replaceChildren(shell);

  return Object.freeze({
    setContext(next) {
      state.context = { ...next };
      scopeHost.replaceChild(contextSummary(state.context), scopeHost.lastElementChild);
    },
    setSuggestions(next) {
      state.suggestionProvider = next || defaultSuggestions;
      renderSuggestions();
    },
    focusComposer() { textarea.focus(); },
    destroy() {
      state.destroyed = true;
      for (const timer of state.timers.values()) clearTimeout(timer);
      state.timers.clear();
    },
    get turns() { return [...state.turns]; },
  });
}
