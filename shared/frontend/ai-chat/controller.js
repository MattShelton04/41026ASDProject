import { append, el } from "../browser/index.js";
import {
  defaultSuggestions, findAssistantScope, normalizeAssistantContexts, normalizeAssistantScopes,
  TERMINAL_ASSISTANT_STATES,
} from "./definitions.js";
import { renderAssistantTurn, contextSummary } from "./components.js";
import { completedTurnHistory, normalizeTurnDetail } from "./formats.js";
import { mergeAssistantEvents, nextAssistantPollDelay } from "./polling.js";

function runFromCreate(payload) {
  return normalizeTurnDetail(payload);
}

function hasContext(context) {
  return Object.values(context || {}).some((value) => value !== null && value !== undefined && value !== "");
}

function activeTurn(turn) {
  return !turn.error && !TERMINAL_ASSISTANT_STATES.has(String(turn.run?.status || "queued").toLowerCase());
}

export function createAiChat({
  root,
  client,
  initialScope = "feature",
  context = {},
  contextOptions = [],
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
  const contextDefinitions = normalizeAssistantContexts(contextOptions);
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

  const welcome = el("section", "ps-ai-chat__welcome");
  append(welcome, el("span", "ps-ai-chat__speaker", assistantLabel), el("h2", "", welcomeTitle), el("p", "", welcomeMessage));
  const suggestionsHost = el("div", "ps-ai-chat__suggestions");
  append(welcome, suggestionsHost);

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
  const contextHost = el("div", "ps-ai-chat__context-host");
  append(scopeHost, scopeLabel, contextHost);

  const transcript = el("div", "ps-ai-chat__transcript");
  transcript.setAttribute("aria-label", "Assistant conversation");

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
  const helper = el("p", "", "Enter sends · Shift+Enter adds a line · completed replies provide bounded follow-up context");
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

  function renderContext() {
    contextHost.replaceChildren();
    if (hasContext(state.context) || !contextDefinitions.length) {
      append(contextHost, contextSummary(state.context));
      if (hasContext(state.context) && contextDefinitions.length) {
        const clear = el("button", "ps-ai-chat__context-clear", "Change page context");
        clear.type = "button";
        clear.addEventListener("click", () => {
          state.context = {};
          renderContext();
        });
        append(contextHost, clear);
      }
      return;
    }

    const editor = el("div", "ps-ai-chat__context-editor");
    const typeLabel = el("label");
    typeLabel.htmlFor = "ps-ai-chat-context-type";
    append(typeLabel, el("span", "", "Page context"));
    const type = el("select");
    type.id = "ps-ai-chat-context-type";
    for (const definition of contextDefinitions) {
      const option = el("option", "", definition.label);
      option.value = definition.id;
      append(type, option);
    }
    append(typeLabel, type);
    const parameterHost = el("div", "ps-ai-chat__context-parameter");

    const updateParameter = () => {
      parameterHost.replaceChildren();
      const definition = contextDefinitions.find((item) => item.id === type.value) || contextDefinitions[0];
      state.context = { ...definition.context };
      if (definition.description) append(parameterHost, el("p", "", definition.description));
      if (!definition.parameter) return;
      const parameterLabel = el("label");
      const inputId = `ps-ai-chat-context-${definition.parameter.name}`;
      parameterLabel.htmlFor = inputId;
      append(parameterLabel, el("span", "", definition.parameter.label));
      const input = el("input");
      input.id = inputId;
      input.name = definition.parameter.name;
      input.type = "text";
      input.required = true;
      input.autocomplete = "off";
      input.placeholder = definition.parameter.placeholder;
      if (definition.parameter.pattern) input.pattern = definition.parameter.pattern;
      input.addEventListener("input", () => {
        const value = input.value.trim();
        state.context = { ...definition.context, ...(value ? { [definition.parameter.name]: value } : {}) };
      });
      append(parameterLabel, input);
      if (definition.parameter.help) append(parameterLabel, el("small", "", definition.parameter.help));
      append(parameterHost, parameterLabel);
    };
    type.addEventListener("change", updateParameter);
    updateParameter();
    append(editor, typeLabel, parameterHost);
    append(contextHost, editor);
  }

  function updateComposerAvailability() {
    const busy = state.turns.some(activeTurn);
    submit.disabled = busy;
    submit.setAttribute("aria-busy", String(busy));
    scope.disabled = busy;
    for (const control of contextHost.querySelectorAll("input, select, button")) control.disabled = busy;
    helper.textContent = busy
      ? "The current response must finish before a follow-up can be sent."
      : "Enter sends · Shift+Enter adds a line · completed replies provide bounded follow-up context";
  }

  function turnArticle(turn) {
    const article = renderAssistantTurn(turn, {
      activityHref,
      onCancel: cancelTurn,
      onRetry: retryTurn,
      assistantLabel,
    });
    article.dataset.turnKey = turn.clientId;
    const runKey = turn.id || turn.clientId;
    for (const [detailIndex, details] of [...article.querySelectorAll("details")].entries()) {
      details.dataset.disclosureKey = `${runKey}:${detailIndex}`;
    }
    for (const [focusIndex, target] of [...article.querySelectorAll("a, button, summary")].entries()) {
      target.dataset.transcriptFocusKey = `${runKey}:${focusIndex}`;
    }
    return article;
  }

  function renderTurn(turn) {
    const existing = [...transcript.children].find((item) => item.dataset.turnKey === turn.clientId);
    const disclosureState = new Map(
      [...(existing?.querySelectorAll("details[data-disclosure-key]") || [])]
        .map((details) => [details.dataset.disclosureKey, details.open]),
    );
    const active = document.activeElement;
    const activeKey = existing?.contains(active) ? active.dataset.transcriptFocusKey || "" : "";
    const top = existing?.getBoundingClientRect().top;
    const article = turnArticle(turn);
    for (const details of article.querySelectorAll("details[data-disclosure-key]")) {
      if (disclosureState.has(details.dataset.disclosureKey)) details.open = disclosureState.get(details.dataset.disclosureKey);
    }
    if (existing) existing.replaceWith(article);
    else append(transcript, article);
    if (Number.isFinite(top)) {
      const delta = article.getBoundingClientRect().top - top;
      if (Math.abs(delta) > 0.5) {
        const scrolling = document.documentElement;
        const previousBehavior = scrolling.style.scrollBehavior;
        scrolling.style.scrollBehavior = "auto";
        window.scrollBy(0, delta);
        scrolling.style.scrollBehavior = previousBehavior;
      }
    }
    if (activeKey) article.querySelector(`[data-transcript-focus-key="${activeKey}"]`)?.focus({ preventScroll: true });
    updateComposerAvailability();
  }

  function schedulePoll(turn, failures = 0) {
    clearTimeout(state.timers.get(turn.clientId));
    const delay = nextAssistantPollDelay(turn.run?.status, failures, document.hidden);
    if (delay === null || state.destroyed || !turn.id) {
      state.timers.delete(turn.clientId);
      updateComposerAvailability();
      return;
    }
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
      renderTurn(turn);
      if (turn.run.status !== previousStatus) announce(`Assistant turn ${turn.run.status}.`);
      schedulePoll(turn, 0);
    } catch (error) {
      turn.pollWarning = error;
      renderTurn(turn);
      schedulePoll(turn, failures + 1);
    }
  }

  async function submitMessage(message, existing = null) {
    if (!existing && state.turns.some(activeTurn)) return;
    const turn = existing || {
      clientId: globalThis.crypto?.randomUUID?.() || `turn-${Date.now()}-${state.turns.length}`,
      message,
      scope: state.scope,
      context: { ...state.context },
      history: completedTurnHistory(state.turns),
      run: { status: "queued" },
      events: [],
      cursor: 0,
    };
    if (!existing) state.turns.push(turn);
    if (existing) {
      clearTimeout(state.timers.get(turn.clientId));
      state.timers.delete(turn.clientId);
      turn.id = null;
      turn.run = { status: "queued" };
      turn.events = [];
      turn.cursor = 0;
    }
    turn.error = null;
    renderTurn(turn);
    announce("Creating a durable assistant run.");
    try {
      const result = await client.createTurn({
        message: turn.message,
        scope: turn.scope,
        context: turn.context,
        history: turn.history || [],
      });
      turn.run = runFromCreate(result.body);
      turn.id = turn.run.id || result.body?.id;
      if (!turn.id) throw new Error("The assistant did not return a run identifier.");
      renderTurn(turn);
      announce(`Assistant run ${turn.id} created.`);
      schedulePoll(turn);
    } catch (error) {
      turn.error = error;
      turn.run = { status: "failed" };
      renderTurn(turn);
      announce("The assistant turn could not start.");
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
      renderTurn(turn);
      schedulePoll(turn);
    } catch (error) {
      turn.cancelWarning = error;
      renderTurn(turn);
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
      if (!submit.disabled) form.requestSubmit();
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.turns.some(activeTurn) || !form.reportValidity()) return;
    const contextInput = contextHost.querySelector("input[required]");
    if (contextInput && !contextInput.reportValidity()) return;
    const message = textarea.value.trim();
    textarea.value = "";
    submitMessage(message);
  });

  renderSuggestions();
  renderContext();
  updateComposerAvailability();
  append(shell, intro, welcome, scopeHost, transcript, form);
  root.replaceChildren(shell);

  return Object.freeze({
    setContext(next) {
      state.context = { ...next };
      renderContext();
      updateComposerAvailability();
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
