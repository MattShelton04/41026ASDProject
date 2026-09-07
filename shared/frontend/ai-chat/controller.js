import { append, el } from "../browser/index.js";
import {
  defaultSuggestions, findAssistantScope, normalizeAssistantContexts, normalizeAssistantScopes,
  TERMINAL_ASSISTANT_STATES, assistantStatus,
} from "./definitions.js";
import { renderAssistantTurn, contextSummary } from "./components.js";
import { completedTurnHistory, normalizeTurnDetail } from "./formats.js";
import { mergeAssistantEvents, nextAssistantPollDelay } from "./polling.js";
import { assistantDrafts, draftContextKey, turnPresentationKey } from "./experience.js";

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
  welcomeMessage = "Answers use only the tools available to this scope. Source checks, coverage limits and the full activity record stay visible.",
  composerLabel = "Message PropertyScope assistant",
  placeholder = "Ask about this research area, its evidence or an available record…",
  initialMessage = "",
  draftKey = "",
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
  append(intro, el("p", "ps-eyebrow", "PropertyScope / Assistant"), el("h1", "", title), el("p", "", description));

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
  transcript.setAttribute("role", "region");

  const form = el("form", "ps-ai-chat__composer");
  const textareaLabel = el("label");
  textareaLabel.htmlFor = "ps-ai-chat-message";
  textareaLabel.className = "ps-ai-chat__composer-label";
  textareaLabel.textContent = composerLabel;
  const textarea = el("textarea");
  textarea.id = "ps-ai-chat-message";
  textarea.name = "message";
  textarea.rows = 2;
  textarea.minLength = 2;
  textarea.maxLength = 2000;
  textarea.required = true;
  textarea.placeholder = placeholder;
  textarea.value = typeof initialMessage === "string" ? initialMessage.trim().slice(0, 2000) : "";
  const composerFooter = el("div", "ps-ai-chat__composer-footer");
  const helper = el("p", "", "Enter to send · Shift+Enter for a new line");
  helper.id = "ps-ai-chat-composer-help";
  textarea.setAttribute("aria-describedby", helper.id);
  const submit = el("button", "ps-button ps-button--primary", "Send message");
  submit.type = "submit";
  append(composerFooter, helper, submit);
  append(form, textareaLabel, textarea, composerFooter);
  const sessionNote = el("p", "ps-ai-chat__session-note", "The conversation stays in this view; activity records are durable. Drafts stay in this tab until reload. Do not enter secrets.");
  const draftId = () => draftContextKey(draftKey, state.scope, state.context);
  const saveDraft = () => assistantDrafts.write(draftId(), textarea.value);
  const resizeComposer = () => {
    if (state.destroyed) return;
    textarea.style.height = "auto";
    const maximum = Number.parseFloat(getComputedStyle(textarea).maxHeight) || 200;
    textarea.style.height = `${Math.min(Math.max(textarea.scrollHeight, 64), maximum)}px`;
  };
  const restoreDraft = () => {
    textarea.value = assistantDrafts.read(draftId());
    textarea.setCustomValidity("");
    resizeComposer();
  };

  function renderSuggestions() {
    suggestionsHost.replaceChildren();
    const provider = state.suggestionProvider;
    const suggestedMessages = typeof provider === "function" ? provider(state.scope) : provider;
    for (const suggestion of (Array.isArray(suggestedMessages) ? suggestedMessages : []).filter((item) => typeof item === "string" && item.trim()).slice(0, 4)) {
      const button = el("button", "ps-ai-chat__suggestion", suggestion);
      button.type = "button";
      button.addEventListener("click", () => {
        textarea.value = suggestion;
        textarea.setCustomValidity("");
        saveDraft();
        resizeComposer();
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
          saveDraft();
          state.context = {};
          renderContext();
          restoreDraft();
          contextHost.querySelector("select, input")?.focus();
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
      if (definition.parameter.help) {
        const help = el("small", "", definition.parameter.help);
        help.id = `${inputId}-help`;
        input.setAttribute("aria-describedby", help.id);
        append(parameterLabel, help);
      }
      append(parameterHost, parameterLabel);
    };
    type.addEventListener("change", () => { saveDraft(); updateParameter(); restoreDraft(); });
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
    const paused = state.turns.some((turn) => turn.run?.status === "review_required");
    helper.textContent = paused
      ? "Human review is required. Inspect full activity or cancel this turn before continuing."
      : busy ? "A response is in progress. You can draft your next question here."
        : "Enter to send · Shift+Enter for a new line";
    submit.textContent = busy ? "Waiting…" : "Send message";
    welcome.hidden = state.turns.length > 0;
    shell.classList.toggle("ps-ai-chat--has-turns", state.turns.length > 0);
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
      details.dataset.disclosureKey = `${runKey}:${details.dataset.disclosure || detailIndex}`;
    }
    for (const [focusIndex, target] of [...article.querySelectorAll("a, button, summary")].entries()) {
      target.dataset.transcriptFocusKey = `${runKey}:${target.dataset.action || (target.tagName === "SUMMARY" ? target.parentElement.dataset.disclosure : focusIndex)}`;
    }
    return article;
  }

  function renderTurn(turn) {
    const existing = [...transcript.children].find((item) => item.dataset.turnKey === turn.clientId);
    const presentationKey = turnPresentationKey(turn);
    if (existing && turn.presentationKey === presentationKey) return;
    turn.presentationKey = presentationKey;
    const disclosureState = new Map(
      [...(existing?.querySelectorAll("details[data-disclosure-key]") || [])]
        .map((details) => [details.dataset.disclosureKey, details.open]),
    );
    const active = document.activeElement;
    const activeKey = existing?.contains(active) ? active.dataset.transcriptFocusKey || "" : "";
    const anchoredInput = active === textarea;
    const anchorTop = activeKey || anchoredInput ? active.getBoundingClientRect().top : existing?.getBoundingClientRect().top;
    const article = turnArticle(turn);
    for (const details of article.querySelectorAll("details[data-disclosure-key]")) {
      if (disclosureState.has(details.dataset.disclosureKey)) details.open = disclosureState.get(details.dataset.disclosureKey);
    }
    if (existing) existing.replaceWith(article);
    else append(transcript, article);
    updateComposerAvailability();
    const restoredFocus = activeKey ? [...article.querySelectorAll("[data-transcript-focus-key]")]
      .find((node) => node.dataset.transcriptFocusKey === activeKey) : null;
    const focusTarget = restoredFocus && !restoredFocus.disabled
      ? restoredFocus : article.querySelector(".ps-ai-chat__speaker[tabindex]");
    if (activeKey) focusTarget?.focus({ preventScroll: true });
    const anchor = anchoredInput ? textarea : activeKey ? focusTarget || article : article;
    if (Number.isFinite(anchorTop)) {
      const delta = anchor.getBoundingClientRect().top - anchorTop;
      if (Math.abs(delta) > 0.5) {
        const scrolling = document.documentElement;
        const previousBehavior = scrolling.style.scrollBehavior;
        scrolling.style.scrollBehavior = "auto";
        window.scrollBy(0, delta);
        scrolling.style.scrollBehavior = previousBehavior;
      }
    }
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
      const revision = turn.revision || 0;
      const [detailResult, eventsResult] = await Promise.all([
        client.getTurn(turn.id),
        client.getEvents(turn.id, turn.cursor || 0),
      ]);
      if (state.destroyed) return;
      if (revision !== (turn.revision || 0)) { schedulePoll(turn); return; }
      turn.run = normalizeTurnDetail(detailResult.body);
      const page = Array.isArray(eventsResult.body?.items) ? eventsResult.body.items : [];
      const merged = mergeAssistantEvents(turn.events, page);
      turn.events = merged.items;
      turn.cursor = Math.max(merged.cursor, Number(eventsResult.body?.next_cursor || 0));
      turn.pollWarning = null;
      renderTurn(turn);
      if (turn.run.status !== previousStatus) announce(`Assistant: ${assistantStatus(turn.run.status).label}.`);
      schedulePoll(turn, 0);
    } catch (error) {
      if (state.destroyed || error.name === "AbortError") return;
      turn.pollWarning = error;
      renderTurn(turn);
      schedulePoll(turn, failures + 1);
    }
  }

  async function submitMessage(message) {
    if (state.destroyed || state.turns.some(activeTurn)) return;
    const turn = {
      clientId: globalThis.crypto?.randomUUID?.() || `turn-${Date.now()}-${state.turns.length}`,
      message,
      scope: state.scope,
      scopeLabel: findAssistantScope(state.scope, scopeDefinitions).label,
      context: { ...state.context },
      history: completedTurnHistory(state.turns),
      run: { status: "queued" },
      events: [],
      cursor: 0,
    };
    state.turns.push(turn);
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
      if (state.destroyed) return;
      turn.run = runFromCreate(result.body);
      turn.id = turn.run.id || result.body?.id;
      if (!turn.id) throw new Error("The assistant did not return a run identifier.");
      renderTurn(turn);
      announce("Assistant run created. Recorded activity will appear with the answer.");
      schedulePoll(turn);
    } catch (error) {
      if (state.destroyed || error.name === "AbortError") return;
      turn.error = error;
      turn.run = { status: "failed" };
      // Restore a rejected question only when it cannot overwrite the next draft.
      if (!textarea.value.trim()) {
        textarea.value = turn.message;
        saveDraft();
        resizeComposer();
      }
      renderTurn(turn);
      announce("The assistant turn could not start.");
    }
  }

  function retryTurn(turn) {
    if (state.turns.some(activeTurn)) { announce("Wait for the current turn before retrying."); return; }
    // Preparing a question never creates a run or repeats an invalid context.
    // Both failed submissions and durable failures remain in the transcript.
    textarea.value = turn.message;
    textarea.setCustomValidity("");
    saveDraft(); resizeComposer(); textarea.focus();
    announce("The previous question is ready to send again. Check the current scope and context.");
  }

  async function cancelTurn(turn) {
    if (state.destroyed || !turn.id || turn.cancelPending || TERMINAL_ASSISTANT_STATES.has(turn.run?.status)) return;
    turn.cancelPending = true;
    turn.revision = (turn.revision || 0) + 1;
    renderTurn(turn);
    try {
      const result = await client.cancelTurn(turn.id);
      if (state.destroyed) return;
      turn.run = normalizeTurnDetail(result.body);
      turn.cancelWarning = null;
      schedulePoll(turn);
    } catch (error) {
      if (state.destroyed || error.name === "AbortError") return;
      turn.cancelWarning = error;
      renderTurn(turn);
      announce("Cancellation could not be confirmed. The last recorded state is shown.");
    } finally {
      turn.cancelPending = false;
      if (!state.destroyed) renderTurn(turn);
    }
  }

  scope.addEventListener("change", () => {
    saveDraft();
    state.scope = findAssistantScope(scope.value, scopeDefinitions).id;
    scopeDescription.textContent = findAssistantScope(state.scope, scopeDefinitions).description;
    renderSuggestions();
    restoreDraft();
  });
  textarea.addEventListener("input", () => {
    textarea.setCustomValidity("");
    saveDraft();
    resizeComposer();
  });
  textarea.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      if (!submit.disabled) form.requestSubmit();
    }
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.turns.some(activeTurn)) return;
    textarea.setCustomValidity(textarea.value.trim().length < 2 ? "Enter a question with at least two non-space characters." : "");
    if (!form.reportValidity()) return;
    const contextInput = contextHost.querySelector("input[required]");
    if (contextInput && !contextInput.reportValidity()) return;
    const message = textarea.value.trim();
    textarea.value = "";
    saveDraft();
    resizeComposer();
    submitMessage(message);
  });

  renderSuggestions();
  renderContext();
  updateComposerAvailability();
  append(shell, intro, scopeHost, welcome, transcript, form, sessionNote);
  root.replaceChildren(shell);
  if (!textarea.value) restoreDraft();
  requestAnimationFrame(resizeComposer);

  return Object.freeze({
    setContext(next) {
      saveDraft();
      state.context = { ...next };
      renderContext();
      restoreDraft();
      updateComposerAvailability();
    },
    setSuggestions(next) {
      state.suggestionProvider = next || defaultSuggestions;
      renderSuggestions();
    },
    focusComposer() { textarea.focus(); },
    destroy() {
      saveDraft();
      state.destroyed = true;
      for (const timer of state.timers.values()) clearTimeout(timer);
      state.timers.clear();
      client.destroy?.();
    },
    get turns() { return [...state.turns]; },
  });
}
