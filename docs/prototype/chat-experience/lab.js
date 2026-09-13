/* Interaction spikes only. No API calls or persisted conversation. */
const study = document.body.dataset.study;
const studies = { fieldnote: "Fieldnote", desk: "Research desk", focus: "Focus", sidecar: "Contextual sidecar", canvas: "Research canvas" };
const defaultQuestion = "What can this property record tell me, and what is still missing?";
const records = [
  { name: "18 Example Street, Parramatta NSW 2150", kind: "Accepted address", id: "00000000-0000-4000-8000-000000000101" },
  { name: "18 Example Street, North Parramatta NSW 2151", kind: "Accepted address", id: "00000000-0000-4000-8000-000000000102" },
  { name: "NSW address register · September demonstration", kind: "Dataset release", id: "00000000-0000-4000-8000-000000000201" },
  { name: "Government schools · September update", kind: "Data update", id: "00000000-0000-4000-8000-000000000301" },
];
const sources = [
  { title: "Accepted address record", kind: "Recorded tool result", detail: "A stable property reference and its accepted address.", excerpt: "This demonstration record identifies an accepted NSW address. It does not establish ownership, dwelling count, a valuation or planning permission.", date: "Simulated accepted snapshot", ref: records[0].id },
  { title: "Publication & coverage guide", kind: "Retrieved project guidance", detail: "What accepted data means, and the limits of its coverage.", excerpt: "Acceptance records a publication decision for a dataset generation. A missing sale record is missing evidence; it is not proof that the property has never sold.", date: "Simulated guidance · reviewed 7 Sep 2026", ref: "operator-guidance / demo-version / passage-02" },
];
const escape = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const app = document.getElementById("app");
app.innerHTML = `
  <div class="lab-bar"><a href="index.html">← All studies</a><span class="lab-note">${escape(studies[study])} · Simulated interactions and evidence</span><div class="lab-tools"><label>Study <select id="study" aria-label="Interaction study">${Object.entries(studies).map(([id, label]) => `<option value="${id}" ${id === study ? "selected" : ""}>${label}</option>`).join("")}</select></label><label>Scenario <select id="scenario" aria-label="Simulation scenario"><option value="success">Successful research</option><option value="missing">Guidance unavailable</option><option value="reconnect">Connection interrupted</option><option value="failure">Source check failed</option><option value="ambiguous">Ambiguous address</option></select></label></div></div>
  <div class="app-shell"><aside class="sidebar"><a href="index.html" class="brand"><span class="brand-mark">p.</span>PropertyScope</a><nav class="side-nav" aria-label="Prototype navigation"><span class="eyebrow">RESEARCH WORKSPACE</span><span>⌂ &nbsp; Overview</span><span>⌕ &nbsp; Property discovery</span><span class="selected">✳ &nbsp; Assistant</span><span>▤ &nbsp; Sources & history</span><span class="eyebrow">DESIGN STUDIO</span><a href="index.html">← &nbsp; Compare interactions</a></nav><div class="side-bottom">NSW property research<br>Prototype · simulated evidence</div></aside>
  <main class="workspace"><header class="workspace-head"><strong>Property data <span class="muted">/ ${study === "sidecar" ? "Property record" : studies[study]}</span></strong><span class="head-status"><span class="status-dot"></span> Read-only research · demo</span><button class="new-chat" id="reset" type="button">＋ New conversation</button></header>
  <div class="conversation-layout"><section class="property-page" hidden><div class="eyebrow">ACCEPTED ADDRESS · DEMONSTRATION</div><h1>18 Example Street</h1><p>Parramatta NSW 2150</p><div class="property-art"><div class="house-roof"></div><div class="house-wall"><i></i><i></i><i></i></div><div class="art-ground"></div><span>Conceptual illustration · not a property photograph</span></div><div class="property-tabs"><span>Research</span><span>Sale history</span><span>Sources</span></div><h2>Property at a glance</h2><dl class="property-facts"><dt>Address evidence</dt><dd>Accepted demonstration record</dd><dt>Sale history</dt><dd>No accepted rows in this example</dd><dt>Planning information</dt><dd>Not checked</dd></dl><button class="page-ask" type="button" data-prompt="Explain why this property has no sale history.">✳ Explain this record</button><p class="dialog-copy">Keep the property in view while the assistant checks its evidence. The record stays attached to your question.</p></section>
  <section class="conversation" aria-label="Research conversation"><div class="welcome" id="welcome"><span class="welcome-symbol" aria-hidden="true">✳</span><div class="focus-orbit" aria-hidden="true">✳</div><div class="eyebrow">YOUR PROPERTY RESEARCH COMPANION</div><h1>${study === "canvas" ? "A question becomes<br>a clearer picture." : study === "sidecar" ? "A little clarity,<br>right here." : "A little more context.<br>A much clearer picture."}</h1><p>Explore the records, understand the limits, and follow the evidence. Start with what's on your mind.</p><div class="prompt-grid"><button class="prompt-card" type="button" data-prompt="${defaultQuestion}"><span>UNDERSTAND A RECORD ↗</span>What does this property evidence actually tell me?</button><button class="prompt-card" type="button" data-prompt="Why does an accepted address have no sale history?"><span>FIND THE GAPS ↗</span>Why is some information still missing?</button></div></div>
  <div class="context-row"><button type="button" id="context" class="context-button"><span aria-hidden="true">⌕</span><span class="context-name">${escape(records[0].name)}</span><span class="muted">⌄</span></button><button type="button" id="clear-context" class="context-clear">Remove</button></div>
  <div class="transcript" id="transcript" role="region" aria-label="Questions and answers"></div>
  <div class="composer-wrap"><form id="composer" class="composer"><label for="message" class="sr-only">Ask about Property data</label><textarea id="message" rows="2" maxlength="2000" placeholder="Ask about this record, its sources, or what's missing…">${defaultQuestion}</textarea><div class="composer-actions"><span class="composer-hint" id="composer-hint">Enter to send · Shift+Enter for a new line</span><button id="send" class="send-button" type="submit"><span>Ask PropertyScope</span><span class="send-icon" aria-hidden="true">↑</span></button><button id="stop" class="send-button" type="button" hidden>■ &nbsp; Stop</button></div></form><p class="conversation-footnote">Design prototype · simulated answers and records · research support</p></div></section>
  <aside class="research-rail" aria-label="Sources in this research"><div class="rail-title"><strong>In this research</strong><span id="source-count">0 sources</span></div><p class="rail-placeholder" id="rail-placeholder">Sources appear here as the checks finish. Open any source to see exactly what it supports.</p><div id="rail-sources" class="rail-sources"></div><div class="rail-bottom">A source can support a finding without answering every part of your question. Gaps stay visible in the brief.</div></aside></div></main></div>
  <dialog id="context-dialog" aria-labelledby="context-title"><div class="dialog-heading"><div><div class="eyebrow">ATTACH CONTEXT</div><h2 id="context-title">Find it by name.</h2></div><button type="button" class="close-dialog" data-close aria-label="Close context search">×</button></div><p class="dialog-copy">Search an address, dataset or update. Paste a GUID for an exact match. The selected record keeps both its readable name and stable link.</p><label class="search-label" for="context-search">Address, dataset name or GUID</label><input class="context-search" id="context-search" type="search" placeholder="Try Parramatta, schools, or a GUID" autocomplete="off"><p id="search-status" class="search-status" role="status"></p><div id="search-results" class="search-results"></div><p class="replay-note">Four synthetic records are available in this local spike.</p></dialog>
  <dialog id="source-dialog" aria-labelledby="source-title"><div class="dialog-heading"><div><div class="source-type" id="source-type"></div><h2 id="source-title"></h2></div><button type="button" class="close-dialog" data-close aria-label="Close source">×</button></div><p class="dialog-copy" id="source-detail"></p><blockquote class="source-excerpt" id="source-excerpt"></blockquote><dl class="source-metadata"><dt>Evidence date</dt><dd id="source-date"></dd><dt>Stable reference</dt><dd id="source-reference"></dd><dt>Evidence boundary</dt><dd>Simulated for interaction review; not current property evidence.</dd></dl><button type="button" class="dialog-action" id="ask-source">Ask about this source →</button></dialog>
  <div id="announcer" class="sr-only" role="status" aria-live="polite" aria-atomic="true"></div>`;
const byId = (id) => document.getElementById(id);
let active = null;
let selectedRecord = records[0];
let turnNumber = 0;
let sourceIndex = 0;
let contextResume = false;
const announce = (message) => { byId("announcer").textContent = message; };
function follow(message) { byId("message").value = message; byId("message").focus(); }
function setBusy(busy) {
  byId("send").hidden = busy; byId("stop").hidden = !busy;
  byId("context").disabled = busy; byId("clear-context").disabled = busy;
  byId("composer-hint").textContent = busy ? "Research in progress. You can draft your follow-up." : "Enter to send · Shift+Enter for a new line";
}
function showSource(index) {
  sourceIndex = index;
  const source = sources[index];
  for (const key of ["title", "type", "detail", "excerpt", "date", "reference"]) {
    byId(`source-${key}`).textContent = source[{ type: "kind", reference: "ref" }[key] || key];
  }
  byId("source-dialog").showModal();
}
function sourceButton(index, rail = false) {
  const source = sources[index];
  const button = document.createElement("button");
  button.type = "button"; button.className = rail ? "rail-card" : "source-chip";
  button.innerHTML = rail ? `<small>${index === 0 ? "01 · PROPERTY RECORD" : "02 · PROJECT GUIDANCE"}</small><strong>${escape(source.title)} ↗</strong><p>${escape(source.detail)}</p>` : `<b>${String(index + 1).padStart(2, "0")}</b>${escape(source.title)} ↗`;
  button.addEventListener("click", () => showSource(index));
  return button;
}
function addSource(turn, index) {
  if (turn.sources.includes(index)) return;
  turn.sources.push(index);
  turn.article.querySelector(".sources-inline").append(sourceButton(index));
  byId("rail-placeholder").hidden = true;
  byId("rail-sources").append(sourceButton(index, true));
  byId("source-count").textContent = `${turn.sources.length} source${turn.sources.length === 1 ? "" : "s"}`;
}
function searchRecords() {
  const query = byId("context-search").value.trim().toLowerCase();
  const matches = records.filter((record) => `${record.name} ${record.kind} ${record.id}`.toLowerCase().includes(query));
  byId("search-status").textContent = matches.length ? `${matches.length} matching demonstration record${matches.length === 1 ? "" : "s"}. Choose the exact record.` : "No matching demonstration record. Try Parramatta, address register or schools.";
  byId("search-results").replaceChildren();
  for (const record of matches) {
    const button = document.createElement("button"); button.type = "button"; button.className = "search-result";
    button.innerHTML = `<strong>${escape(record.name)}</strong><small>${escape(record.kind)} · ${record.id}</small>`;
    button.addEventListener("click", () => {
      selectedRecord = record; updateContext(); byId("context-dialog").close();
      if (contextResume) { contextResume = false; byId("scenario").value = "success"; follow(`Research the selected record: ${record.name}`); }
      announce(`Attached ${record.name}.`);
    });
    byId("search-results").append(button);
  }
}
function updateContext() {
  byId("context").querySelector(".context-name").textContent = selectedRecord?.name || "Attach a record · name or GUID";
  byId("clear-context").hidden = !selectedRecord;
}
function openContext(ambiguous = false) {
  contextResume = ambiguous;
  byId("context-search").value = ambiguous ? "18 Example Street" : "";
  searchRecords(); byId("context-dialog").showModal(); byId("context-search").focus();
}
function progress(turn, label, detail, marker = "◌") {
  const elapsed = ((performance.now() - turn.started) / 1000).toFixed(1);
  turn.article.querySelector(".progress-label").textContent = label;
  turn.article.querySelector(".progress-detail").textContent = detail;
  const previous = turn.article.querySelector(".activity-list .current");
  if (previous) { previous.classList.remove("current"); previous.querySelector(".activity-mark").textContent = "✓"; }
  const item = document.createElement("li"); item.className = "current";
  item.innerHTML = `<span class="activity-mark">${marker}</span><span>${escape(label)}</span><time>${elapsed}s</time>`;
  turn.article.querySelector(".activity-list").append(item);
  turn.article.querySelector(".activity-count").textContent = `Follow the activity · ${turn.article.querySelectorAll(".activity-list li").length} updates`;
  announce(label);
}
function notice(turn, message, action, handler) {
  const block = document.createElement("div"); block.className = "notice"; block.setAttribute("role", "status"); block.textContent = message;
  if (action) { const button = document.createElement("button"); button.type = "button"; button.textContent = action; button.addEventListener("click", handler); block.append(button); }
  turn.article.querySelector(".answer-host").append(block); return block;
}
function settle(turn, state) {
  clearInterval(turn.clock); turn.article.classList.remove("is-running");
  turn.article.querySelector(".response-state").textContent = state;
  turn.article.querySelector(".progress-glyph").textContent = state === "Complete" ? "✓" : "−";
  turn.article.querySelector(".progress-elapsed").textContent = `${((performance.now() - turn.started) / 1000).toFixed(1)}s · demo`;
  const current = turn.article.querySelector(".activity-list .current");
  if (current) { current.classList.remove("current"); current.querySelector(".activity-mark").textContent = state === "Complete" ? "✓" : "−"; }
  if (active === turn) active = null;
  setBusy(false); announce(state);
}
function finishAnswer(turn) {
  const missing = turn.scenario === "missing";
  const isFollowUp = turnNumber > 1;
  progress(turn, missing ? "Record checked. Guidance is unavailable." : "Your research brief is ready", "The findings below keep recorded facts and evidence gaps separate.", "✓");
  const answer = document.createElement("div"); answer.className = "answer";
  answer.innerHTML = `<div class="answer-kicker">${missing ? "Partial evidence · document context unavailable" : "Research brief · sources identified"}</div><h2>${missing ? "Here is what the record supports." : isFollowUp ? "The distinction is in the evidence." : "An address is a starting point.<br>Not the whole story."}</h2><p class="answer-lead">${missing ? "The address check completed, but the guidance library could not be reached. You can still inspect the recorded result. A guidance-based explanation needs another attempt." : "This example links an accepted address to a stable property reference. That gives you a reliable starting point for research, with a clear boundary around what has—and hasn't—been checked."}</p>
    <div class="finding"><span class="finding-num">01</span><div><h3>A record you can return to <button type="button" class="cite" data-source="0" aria-label="Inspect source 1: accepted address record">1 ↗</button></h3><p>The readable address and its GUID travel together. Search finds the record; the stable reference identifies the exact selection.</p></div></div>
    ${missing ? "" : `<div class="finding"><span class="finding-num">02</span><div><h3>Missing sales are a gap, not a conclusion <button type="button" class="cite" data-source="1" aria-label="Inspect source 2: publication and coverage guide">2 ↗</button></h3><p>No accepted sale rows are shown in this simulated example. That does not establish that the property has never sold.</p></div></div>`}
    <div class="coverage-note"><strong>${missing ? "DOCUMENT GUIDANCE UNAVAILABLE" : "STILL TO ESTABLISH"}</strong>${missing ? "No document-based finding is presented. Source inspection remains available, and a new turn can check guidance again." : "Ownership, planning permission and a valuation are not established by this record. Those questions need their own appropriate evidence."}</div>
    <div class="follow-ups"><button type="button" data-prompt="What would I need to check next?">What should I check next? ↗</button><button type="button" data-prompt="Explain accepted data in plain English.">Explain accepted data ↗</button></div><div class="answer-footer"><span>Illustrative answer · ${turn.sources.length} simulated sources</span><button type="button" class="show-activity">View recorded activity</button><button type="button" class="copy-answer">Copy brief</button></div>`;
  turn.article.querySelector(".answer-host").append(answer);
  answer.querySelectorAll("[data-source]").forEach((button) => button.addEventListener("click", () => showSource(Number(button.dataset.source))));
  answer.querySelector(".show-activity").addEventListener("click", () => { const fold = turn.article.querySelector("details"); fold.open = true; fold.querySelector("summary").focus(); });
  answer.querySelector(".copy-answer").addEventListener("click", async (event) => {
    try { await navigator.clipboard.writeText(`SIMULATED PROTOTYPE ANSWER\n${answer.innerText}`); event.target.textContent = "Copied ✓"; }
    catch { event.target.textContent = "Select brief to copy"; announce("Copy unavailable in this browser. You can select the brief text."); }
  });
  bindPrompts(answer); settle(turn, "Complete");
}
function waitTurn(turn, ms) { return new Promise((resolve) => { turn.timer = setTimeout(resolve, ms); turn.releaseWait = resolve; }); }
async function simulate(turn) {
  const sequence = [
    ["Understanding your question", "Choosing the checks needed for this question."],
    ["Checking the accepted address", "Reading the selected property record through its owning service."],
    ["Reading the publication guidance", "Looking for a relevant explanation in the reviewed guidance library."],
    ["Checking what the sources support", "Keeping current record facts separate from general guidance."],
  ];
  for (let index = 0; index < sequence.length; index += 1) {
    await waitTurn(turn, index === 0 ? 900 : 1800);
    if (active !== turn) return;
    if (index === 1 && turn.scenario === "ambiguous") {
      progress(turn, "Two addresses match. Which one did you mean?", "Nothing has been attached automatically.");
      notice(turn, "18 Example Street appears in Parramatta and North Parramatta in this demo. Choose the exact address to continue.", "Choose the property →", () => openContext(true));
      settle(turn, "Choose a record"); return;
    }
    if (index === 2) addSource(turn, 0);
    if (index === 2 && turn.scenario === "failure") {
      progress(turn, "The next source check could not complete", "The completed address check remains available.");
      notice(turn, "The simulated guidance check failed. Your question and its attached record are preserved.", "Prepare this question again →", () => follow(turn.message));
      settle(turn, "Could not complete"); return;
    }
    if (index === 2 && turn.scenario === "reconnect") {
      const reconnect = notice(turn, "Activity updates paused. The last recorded state is still here; reconnecting does not submit your question again.");
      announce("Activity updates paused. Reconnecting.");
      await waitTurn(turn, 2500); if (active !== turn) return;
      reconnect.textContent = "Reconnected. Continuing the same research turn.";
    }
    if (index === 3 && turn.scenario !== "missing") addSource(turn, 1);
    if (index === 3 && turn.scenario === "missing") notice(turn, "The guidance library is unavailable. The address result is retained; document-based findings will be omitted.");
    progress(turn, ...sequence[index]);
  }
  await waitTurn(turn, 1600); if (active === turn) finishAnswer(turn);
}
function sendQuestion(event) {
  event?.preventDefault(); if (active) return;
  const message = byId("message").value.trim(); if (message.length < 2) { byId("message").focus(); return; }
  turnNumber += 1; byId("welcome").hidden = true;
  byId("rail-sources").replaceChildren(); byId("rail-placeholder").hidden = false; byId("source-count").textContent = "0 sources";
  const user = document.createElement("div"); user.className = "user-turn";
  user.innerHTML = `<span class="user-label">YOU${selectedRecord ? " · RECORD ATTACHED" : ""}</span>${escape(message)}`;
  const article = document.createElement("article"); article.className = "response is-running";
  article.innerHTML = `<div class="response-byline"><span class="assistant-glyph" aria-hidden="true">✳</span>PropertyScope<span class="response-state">Researching</span></div><div class="progress-block"><div class="progress-top"><span class="progress-glyph" aria-hidden="true">✳</span><span class="progress-label">Starting your research</span><span class="progress-elapsed">0.0s · demo</span></div><p class="progress-detail">Your question and selected context are attached.</p><details class="activity-fold" ${study === "canvas" ? "open" : ""}><summary class="activity-count">Follow the activity</summary><ol class="activity-list"></ol></details></div><div class="sources-inline"></div><div class="answer-host"></div>`;
  byId("transcript").append(user, article);
  const turn = { article, message, sources: [], scenario: byId("scenario").value, started: performance.now() };
  active = turn; setBusy(true); byId("message").value = "";
  progress(turn, "Question received", selectedRecord ? `Attached: ${selectedRecord.name}` : "No record attached. This is a general research question.");
  turn.clock = setInterval(() => { article.querySelector(".progress-elapsed").textContent = `${((performance.now() - turn.started) / 1000).toFixed(1)}s · demo`; }, 250);
  simulate(turn);
  // Do not force scroll while reading sources; only reveal the response after a send.
  article.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "nearest" });
}
function stopTurn() {
  const turn = active; if (!turn) return;
  clearTimeout(turn.timer); turn.releaseWait?.();
  progress(turn, "Research stopped", "Any completed checks stay attached to this turn.", "−");
  notice(turn, "You stopped this simulated turn. You can inspect completed sources or prepare the question again.", "Prepare question again →", () => follow(turn.message));
  settle(turn, "Cancelled");
}
function reset() {
  stopTurn(); byId("transcript").replaceChildren(); byId("rail-sources").replaceChildren();
  byId("welcome").hidden = false; byId("rail-placeholder").hidden = false; byId("source-count").textContent = "0 sources";
  byId("message").value = defaultQuestion; turnNumber = 0;
}
function bindPrompts(root) { root.querySelectorAll("[data-prompt]").forEach((button) => button.addEventListener("click", () => follow(button.dataset.prompt))); }
bindPrompts(app);
byId("composer").addEventListener("submit", sendQuestion);
byId("message").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); sendQuestion(); } });
byId("stop").addEventListener("click", stopTurn);
byId("reset").addEventListener("click", () => { reset(); byId("message").focus(); });
byId("scenario").addEventListener("change", () => { reset(); announce("Scenario changed. Send a question to play it."); });
byId("study").addEventListener("change", (event) => { location.href = `${event.target.value}.html`; });
byId("context").addEventListener("click", () => openContext());
byId("clear-context").addEventListener("click", () => { selectedRecord = null; updateContext(); });
byId("context-search").addEventListener("input", searchRecords);
byId("ask-source").addEventListener("click", () => { byId("source-dialog").close(); follow(`What does the ${sources[sourceIndex].title.toLowerCase()} support, and what are its limits?`); });
document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
if (study === "sidecar") document.querySelector(".property-page").hidden = false;
window.addEventListener("pagehide", () => { if (active) { clearTimeout(active.timer); clearInterval(active.clock); active = null; } });
