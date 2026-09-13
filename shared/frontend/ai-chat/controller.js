import { append, el } from "../browser/index.js";
import {
  defaultSuggestions, findAssistantScope, normalizeAssistantContexts, normalizeAssistantScopes,
  TERMINAL_ASSISTANT_STATES, assistantStatus,
  assistantContextFromInput,
} from "./definitions.js";
import { renderAssistantTurn, contextSummary } from "./components.js";
import { completedTurnHistory, normalizeTurnDetail } from "./formats.js";
import { mergeAssistantEvents, nextAssistantPollDelay } from "./polling.js";
import { assistantDrafts, draftContextKey, turnPresentationKey } from "./experience.js";
import { activityPresentation } from "./activity.js";
import { createEvidencePanel } from "./evidence-panel.js";
import { revealAnswer } from "./reveal.js";

let assistantInstance = 0;

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
  announce = null,
  title = "Ask PropertyScope",
  description = "Search records, ask about the data, and inspect the sources behind each answer.",
  scopes = undefined,
  suggestions = defaultSuggestions,
  assistantLabel = "PropertyScope assistant",
  welcomeTitle = "What would you like to check?",
  welcomeMessage = "Ask a question or choose a starting point.",
  composerLabel = "Message PropertyScope assistant",
  placeholder = "Ask about this research area, its evidence or an available record…",
  initialMessage = "",
  initialTurns = [],
  draftKey = "",
  layout = "page",
  toolLabels = {},
  searchContext = null,
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
  const instanceId = `ps-ai-chat-${++assistantInstance}`;
  let contextSearch = null;
  const shell = el("section", `ps-ai-chat ps-ai-chat--${layout === "embedded" ? "embedded" : "page"}`);
  const evidencePanel = createEvidencePanel(shell);
  const reveals = new Set();
  const liveRegion = el("div", "ps-ai-chat__sr-only");
  liveRegion.setAttribute("role", "status");
  liveRegion.setAttribute("aria-live", "polite");
  const publishStatus = (message) => {
    if (typeof announce === "function") announce(message);
    else liveRegion.textContent = message;
  };
  const intro = el("header", "ps-ai-chat__intro");
  const emblem = el("span", "ps-ai-chat__emblem", "✳");
  emblem.setAttribute("aria-hidden", "true");
  append(intro, emblem, el("p", "ps-eyebrow", "PropertyScope / Assistant"), el(layout === "embedded" ? "h2" : "h1", "", title), el("p", "", description));

  const welcome = el("section", "ps-ai-chat__welcome");
  append(welcome, el(layout === "embedded" ? "h3" : "h2", "", welcomeTitle), el("p", "", welcomeMessage));
  const suggestionsHost = el("div", "ps-ai-chat__suggestions");
  append(welcome, suggestionsHost);

  const scopeHost = el("div", "ps-ai-chat__scope");
  const scopeLabel = el("label");
  scopeLabel.htmlFor = `${instanceId}-scope`;
  append(scopeLabel, el("span", "", "Assistant scope"));
  const scope = el("select");
  scope.id = `${instanceId}-scope`;
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
  const settings = el("details", "ps-ai-chat__settings");
  const settingsSummary = el("summary", "", "Research scope and context");
  append(settings, settingsSummary, scopeHost);

  const transcript = el("div", "ps-ai-chat__transcript");
  transcript.setAttribute("aria-label", "Assistant conversation");
  transcript.setAttribute("role", "region");

  const form = el("form", "ps-ai-chat__composer");
  const textareaLabel = el("label");
  textareaLabel.htmlFor = `${instanceId}-message`;
  textareaLabel.className = "ps-ai-chat__composer-label";
  textareaLabel.textContent = composerLabel;
  const textarea = el("textarea");
  textarea.id = `${instanceId}-message`;
  textarea.name = "message";
  textarea.rows = 2;
  textarea.minLength = 2;
  textarea.maxLength = 2000;
  textarea.required = true;
  textarea.placeholder = placeholder;
  textarea.value = typeof initialMessage === "string" ? initialMessage.trim().slice(0, 2000) : "";
  const composerFooter = el("div", "ps-ai-chat__composer-footer");
  const helper = el("p", "", "Enter to send · Shift+Enter for a new line");
  helper.id = `${instanceId}-composer-help`;
  textarea.setAttribute("aria-describedby", helper.id);
  const submit = el("button", "ps-button ps-button--primary", "Send message");
  submit.type = "submit";
  const stop = el("button", "ps-button ps-button--secondary", "Stop response");
  stop.type = "button"; stop.hidden = true;
  stop.addEventListener("click", () => { const turn = state.turns.find(activeTurn); if (turn?.id) cancelTurn(turn); });
  append(composerFooter, helper, submit, stop);
  append(form, textareaLabel, textarea, composerFooter);
  const sessionNote = el("p", "ps-ai-chat__session-note", "Research support · Conversation stays in this view · Activity is saved");
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
    contextSearch?.abort();
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
    typeLabel.htmlFor = `${instanceId}-context-type`;
    append(typeLabel, el("span", "", "Page context"));
    const type = el("select");
    type.id = `${instanceId}-context-type`;
    for (const definition of contextDefinitions) {
      const option = el("option", "", definition.label);
      option.value = definition.id;
      append(type, option);
    }
    append(typeLabel, type);
    const parameterHost = el("div", "ps-ai-chat__context-parameter");

    const updateParameter = () => {
      contextSearch?.abort();
      parameterHost.replaceChildren();
      const definition = contextDefinitions.find((item) => item.id === type.value) || contextDefinitions[0];
      state.context = { ...definition.context };
      if (definition.description) append(parameterHost, el("p", "", definition.description));
      if (!definition.parameter) return;
      const parameterLabel = el("label");
      const inputId = `${instanceId}-context-${definition.parameter.name}`;
      parameterLabel.htmlFor = inputId;
      append(parameterLabel, el("span", "", definition.parameter.label));
      const input = el("input");
      input.id = inputId;
      input.name = definition.parameter.name;
      input.type = "text";
      input.required = true;
      input.autocomplete = "off";
      input.placeholder = definition.parameter.placeholder;
      if (definition.parameter.pattern && !definition.parameter.searchParameter) input.pattern = definition.parameter.pattern;
      if (definition.parameter.searchParameter) { input.minLength = 2; input.maxLength = 200; }
      input.addEventListener("input", () => {
        contextSearch?.abort();
        state.context = assistantContextFromInput(definition, input.value);
        matches.replaceChildren();
      });
      const matches = el("div", "ps-ai-chat__context-matches");
      matches.setAttribute("aria-live", "polite");
      append(parameterLabel, input);
      if (definition.parameter.help) {
        const help = el("small", "", definition.parameter.help);
        help.id = `${inputId}-help`;
        input.setAttribute("aria-describedby", help.id);
        append(parameterLabel, help);
      }
      append(parameterHost, parameterLabel);
      if (searchContext && definition.parameter.searchParameter) {
        const search = el("button", "ps-ai-chat__context-clear", "Find matching records");
        search.type = "button";
        search.addEventListener("click", async () => {
          if (!input.reportValidity() || input.value.trim().length < 2) return;
          contextSearch?.abort();
          const task = new AbortController();
          contextSearch = task;
          matches.replaceChildren(el("p", "", "Searching records…"));
          try {
            const results = await searchContext(definition.id, input.value.trim(), { signal: task.signal });
            if (state.destroyed || task.signal.aborted || state.turns.some(activeTurn)) return;
            matches.replaceChildren(el("p", "", results.note || "Choose a record to attach it."));
            for (const match of results.items || []) {
              const choice = el("button", "ps-ai-chat__context-match", match.label);
              choice.type = "button";
              choice.addEventListener("click", () => {
                if (state.turns.some(activeTurn)) return;
                saveDraft();
                state.context = { ...match.context, display_label: match.label.slice(0, 200) };
                renderContext(); restoreDraft(); updateComposerAvailability();
                publishStatus(`Attached ${match.label}`);
                settingsSummary.focus();
              });
              append(matches, choice);
            }
          } catch (error) {
            if (!task.signal.aborted && !state.destroyed) matches.replaceChildren(el("p", "", "Search is unavailable. Keep the name in context and ask the assistant to check it, or try again."));
          }
        });
        append(parameterHost, search, matches);
      }
    };
    type.addEventListener("change", () => { saveDraft(); updateParameter(); restoreDraft(); updateComposerAvailability(); });
    updateParameter();
    append(editor, typeLabel, parameterHost);
    append(contextHost, editor);
  }

  function updateComposerAvailability() {
    const busy = state.turns.some(activeTurn);
    submit.disabled = busy;
    submit.hidden = busy;
    const running = state.turns.find(activeTurn);
    stop.hidden = !busy || running?.canCancel === false;
    stop.disabled = !running?.id || Boolean(running?.cancelPending);
    stop.textContent = running?.cancelPending ? "Requesting stop…" : "Stop response";
    submit.setAttribute("aria-busy", String(busy));
    scope.disabled = busy;
    for (const control of contextHost.querySelectorAll("input, select, button")) control.disabled = busy;
    const paused = state.turns.some((turn) => turn.run?.status === "review_required");
    helper.textContent = busy && running?.canCancel === false
      ? "This recorded review is still active. Open full activity to manage it; you can draft a follow-up here."
      : paused
      ? "Human review is required. Inspect full activity or cancel this turn before continuing."
      : busy ? "A response is in progress. You can draft your next question here."
        : "Enter to send · Shift+Enter for a new line";
    submit.textContent = busy ? "Waiting…" : "Send message";
    welcome.hidden = state.turns.length > 0;
    shell.classList.toggle("ps-ai-chat--has-turns", state.turns.length > 0);
    if (state.turns.length && form.parentElement && form.previousElementSibling !== transcript) transcript.after(form);
    settingsSummary.textContent = state.context.display_label || state.context.query || (hasContext(state.context) ? "Linked page context" : `${findAssistantScope(state.scope, scopeDefinitions).label} · ${contextDefinitions.length ? "Change scope or attach a record" : "Change scope"}`);
  }

  function turnArticle(turn) {
    const article = renderAssistantTurn(turn, {
      activityHref,
      onCancel: turn.canCancel === false ? null : cancelTurn,
      onRetry: retryTurn,
      assistantLabel,
      toolLabels,
      inspection: evidencePanel.prepare(turn.clientId),
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
    if (!existing) article.classList.add("ps-ai-chat__turn--new");
    if (turn.run?.final_result && !existing?.querySelector(".ps-ai-chat__answer--grounded")) article.classList.add("ps-ai-chat__turn--answered");
    for (const details of article.querySelectorAll("details[data-disclosure-key]")) {
      if (disclosureState.has(details.dataset.disclosureKey)) details.open = disclosureState.get(details.dataset.disclosureKey);
    }
    if (existing) existing.replaceWith(article);
    else append(transcript, article);
    if (turn.run?.status === "succeeded" && !turn.answerRevealed) {
      turn.answerRevealed = true;
      reveals.add(revealAnswer(article));
    }
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
        const pane = shell.closest(".ps-ai-sidecar__body");
        if (pane && pane.scrollHeight > pane.clientHeight) pane.scrollTop += delta;
        else window.scrollBy(0, delta);
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
      const [detailResponse, eventResponse] = await Promise.allSettled([
        client.getTurn(turn.id),
        client.getEvents(turn.id, turn.cursor || 0),
      ]);
      if (state.destroyed) return;
      if (revision !== (turn.revision || 0)) { schedulePoll(turn); return; }
      if (detailResponse.status === "rejected") throw detailResponse.reason;
      const detailResult = detailResponse.value;
      turn.run = normalizeTurnDetail(detailResult.body);
      if (eventResponse.status === "fulfilled") {
        const eventsResult = eventResponse.value;
        const page = Array.isArray(eventsResult.body?.items) ? eventsResult.body.items : [];
        const merged = mergeAssistantEvents(turn.events, page);
        turn.events = merged.items;
        turn.cursor = Math.max(turn.cursor || 0, merged.cursor, Number(eventsResult.body?.next_cursor || 0));
      }
      turn.pollWarning = eventResponse.status === "rejected" && !TERMINAL_ASSISTANT_STATES.has(turn.run.status) ? eventResponse.reason : null;
      renderTurn(turn);
      const progress = activityPresentation(turn.run, toolLabels).title;
      if (progress !== turn.lastProgress || turn.run.status !== previousStatus) publishStatus(progress);
      turn.lastProgress = progress;
      schedulePoll(turn, eventResponse.status === "rejected" ? failures + 1 : 0);
    } catch (error) {
      if (state.destroyed || error.name === "AbortError") return;
      turn.pollWarning = error;
      renderTurn(turn);
      schedulePoll(turn, failures + 1);
    }
  }

  async function submitMessage(message) {
    if (state.destroyed || state.turns.some(activeTurn)) return;
    contextSearch?.abort();
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
    publishStatus("Starting your question.");
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
      publishStatus("Assistant run created. Recorded activity will appear with the answer.");
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
      publishStatus("The assistant turn could not start.");
    }
  }

  function retryTurn(turn) {
    if (state.turns.some(activeTurn)) { publishStatus("Wait for the current turn before retrying."); return; }
    // Preparing a question never creates a run or repeats an invalid context.
    // Both failed submissions and durable failures remain in the transcript.
    textarea.value = turn.message;
    textarea.setCustomValidity("");
    saveDraft(); resizeComposer(); textarea.focus();
    publishStatus("The previous question is ready to send again. Check the current scope and context.");
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
      publishStatus("Cancellation could not be confirmed. The last recorded state is shown.");
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
    updateComposerAvailability();
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
    if (contextInput && !contextInput.checkValidity()) {
      settings.open = true;
      contextInput.reportValidity();
      return;
    }
    const message = textarea.value.trim();
    textarea.value = "";
    saveDraft();
    resizeComposer();
    submitMessage(message);
  });

  renderSuggestions();
  renderContext();
  updateComposerAvailability();
  append(shell, intro, welcome, form, settings, transcript, sessionNote, liveRegion, evidencePanel.element);
  root.replaceChildren(shell);
  for (const initial of initialTurns) {
    const run = normalizeTurnDetail(initial.run);
    if (!run.id) continue;
    const turn = {
      ...initial, run, id: run.id, clientId: `${instanceId}-${run.id}`,
      scope: initial.scope || state.scope,
      scopeLabel: initial.scopeLabel || findAssistantScope(initial.scope || state.scope, scopeDefinitions).label,
      context: { ...(initial.context || state.context) },
      events: initial.events || [], cursor: 0, answerRevealed: true,
    };
    state.turns.push(turn);
    renderTurn(turn);
    // Fetch recorded events once even for a completed historical answer.
    pollTurn(turn);
  }
  if (assistantDrafts.read(draftId()) || !textarea.value) restoreDraft();
  requestAnimationFrame(resizeComposer);
  const elapsedTimer = setInterval(() => {
    if (state.destroyed || document.hidden || shell.hidden) return;
    for (const node of shell.querySelectorAll("[data-elapsed-start]")) {
      const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(node.dataset.elapsedStart)) / 1000));
      if (Number.isFinite(seconds)) node.textContent = seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    }
  }, 1000);

  return Object.freeze({
    setContext(next) {
      if (state.turns.some(activeTurn)) return;
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
    setDraft(message) { textarea.value = String(message || "").slice(0, 2000); saveDraft(); resizeComposer(); textarea.focus(); },
    destroy() {
      saveDraft();
      state.destroyed = true;
      for (const finish of reveals) finish();
      reveals.clear();
      contextSearch?.abort();
      clearInterval(elapsedTimer);
      for (const timer of state.timers.values()) clearTimeout(timer);
      state.timers.clear();
      client.destroy?.();
    },
    get turns() { return [...state.turns]; },
  });
}
