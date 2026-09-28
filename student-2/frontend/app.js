import { el, requestJsonResponse, createLatestTask } from "./browser/index.js";
import { createFeatureAssistant } from "./ai-chat/index.js";

const API = "/api/market-intelligence/v1";
const EXAMPLE_PROPERTY = {
  reference: "a0000000-0000-0000-0000-000000000001",
  address: "11 Example Street, Sydney NSW 2000",
};
const money = new Intl.NumberFormat("en-AU", {
  style: "currency",
  currency: "AUD",
  maximumFractionDigits: 0,
});

const state = { cases: [], selectedId: null, evidence: null, evidenceLoading: false, evidenceError: null, editing: false, assistant: null };
const evidenceTask = createLatestTask();
let saving = false;
let deleting = false;
const byId = (id) => document.getElementById(id);

function text(node, value) {
  node.textContent = value == null || value === "" ? "Not available" : String(value);
}

function clear(node) {
  while (node.firstChild) node.firstChild.remove();
}

function humanise(value) {
  return String(value || "unknown").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function populatePropertyChoices(selectedReference, selectedAddress) {
  const properties = new Map([[EXAMPLE_PROPERTY.reference, EXAMPLE_PROPERTY.address]]);
  for (const item of state.cases) properties.set(item.property_ref, item.address_display);
  if (selectedReference) properties.set(selectedReference, selectedAddress || "Selected property");

  const select = byId("form-property-choice");
  clear(select);
  for (const [reference, address] of properties) {
    const option = el("option", "", address);
    option.value = reference;
    option.dataset.address = address;
    select.append(option);
  }
  select.value = selectedReference || EXAMPLE_PROPERTY.reference;
  syncSelectedProperty();
}

function syncSelectedProperty() {
  const select = byId("form-property-choice");
  const option = select.selectedOptions[0];
  byId("form-property").value = option?.value || "";
  byId("form-address").value = option?.dataset.address || "";
}

async function api(path, options = {}) {
  return (await requestJsonResponse(fetch, `${API}${path}`, options)).body;
}

function notify(message, isError = false) {
  const notice = byId("notice");
  text(notice, message);
  notice.hidden = !message;
  notice.classList.toggle("error-text", isError);
}

function renderCases() {
  const list = byId("case-list");
  clear(list);
  if (!state.cases.length) list.append(el("p", "case-list-empty", "No saved cases yet. Create a case to begin."));
  for (const item of state.cases) {
    const button = el("button", "case-item");
    button.type = "button";
    button.dataset.caseId = item.id;
    button.setAttribute("aria-current", String(item.id === state.selectedId));
    button.append(el("strong", "", item.name));
    button.append(el("span", "", `${humanise(item.status)} · ${item.date_from.slice(0, 4)}–${item.date_to.slice(0, 4)}`));
    button.append(el("span", "", item.address_display));
    list.append(button);
  }
}

function renderVolume(items) {
  const chart = byId("volume-chart");
  clear(chart);
  if (!items.length) {
    chart.append(el("p", "muted", "No eligible sales in this case window."));
    return;
  }
  const maximum = Math.max(...items.map((item) => Number(item.transactions) || 0), 1);
  for (const item of items) {
    const column = el("div", "volume-column");
    const count = el("strong", "", item.transactions);
    const bar = el("div", "volume-bar");
    bar.style.setProperty("--volume-ratio", String(Math.max(0, Number(item.transactions) || 0) / maximum));
    bar.setAttribute("aria-hidden", "true");
    column.append(count, bar, el("span", "", item.period));
    chart.append(column);
  }
}

function renderLimitations(summary) {
  const list = byId("limitations");
  clear(list);
  for (const limitation of summary.limitations || []) list.append(el("li", "", limitation));
  const reasons = byId("exclusion-reasons");
  clear(reasons);
  for (const [reason, count] of Object.entries(summary.exclusion_reasons || {})) {
    reasons.append(el("dt", "", humanise(reason)), el("dd", "", count));
  }
  if (!reasons.childElementCount) reasons.append(el("dt", "", "No exclusions"), el("dd", "", "0"));
}

function renderSales(sales) {
  const body = byId("sales-body");
  clear(body);
  if (!sales.length) {
    const row = el("tr"); const cell = el("td", "muted", "No eligible source observations in this date window.");
    cell.colSpan = 5; row.append(cell); body.append(row);
  }
  for (const sale of sales) {
    const row = document.createElement("tr");
    const values = [
      sale.contract_date || "Not recorded",
      Number.isInteger(sale.price_aud) && sale.price_aud > 0 ? money.format(sale.price_aud) : "Missing / zero",
      `${sale.match_tier} · ${Math.round(Number(sale.match_confidence) * 100)}%`,
      sale.release_version,
      sale.synthetic ? "Synthetic fixture" : "Accepted release",
    ];
    for (const value of values) row.append(el("td", "", value));
    body.append(row);
  }
  text(byId("sales-label"), `${sales.length} source record${sales.length === 1 ? "" : "s"}`);
}

function renderEvidence() {
  const evidence = state.evidence;
  const waiting = state.evidenceLoading || Boolean(state.evidenceError);
  byId("evidence-state").hidden = !waiting;
  byId("evidence-state").setAttribute("aria-busy", String(state.evidenceLoading));
  text(byId("evidence-state-title"), state.evidenceError ? "Case evidence could not be loaded" : "Loading case evidence");
  text(byId("evidence-state-copy"), state.evidenceError || "Reading the saved case and source observations.");
  byId("retry-evidence").hidden = !state.evidenceError;
  byId("empty-state").hidden = Boolean(evidence) || waiting;
  byId("case-detail").hidden = !evidence;
  if (!evidence) return;
  const item = evidence.market_case;
  const summary = evidence.summary;
  text(byId("case-title"), item.name);
  text(byId("case-address"), item.address_display);
  text(byId("case-status"), humanise(item.status));
  byId("case-status").dataset.state = item.status;
  byId("validation-state").dataset.state = item.property_validation_state;
  text(byId("validation-state"), `Property: ${humanise(item.property_validation_state)}`);
  text(byId("sale-count"), summary.eligible_sale_count);
  text(byId("median-price"), summary.median_price_aud == null ? "Insufficient data" : money.format(summary.median_price_aud));
  text(byId("excluded-count"), summary.excluded_sale_count);
  text(byId("source-count"), summary.source_release_ids.length);
  text(byId("case-window"), `${summary.date_from} to ${summary.date_to} · tier ${summary.minimum_match_tier}+`);
  renderVolume(summary.transaction_volume || []);
  renderLimitations(summary);
  renderSales(evidence.sales || []);
}

async function loadCases(preferredId = null) {
  const body = await api("/market-cases");
  state.cases = body.items || [];
  state.selectedId = preferredId || state.selectedId || state.cases[0]?.id || null;
  if (!state.cases.some((item) => item.id === state.selectedId)) state.selectedId = state.cases[0]?.id || null;
  renderCases();
  await loadEvidence();
}

async function loadEvidence() {
  const task = evidenceTask.start();
  const id = state.selectedId;
  state.evidence = null;
  state.evidenceError = null;
  state.evidenceLoading = Boolean(id);
  syncAssistantContext();
  renderCases();
  renderEvidence();
  if (!id) return;
  byId("case-detail").setAttribute("aria-busy", "true");
  try {
    const evidence = await api(`/market-cases/${encodeURIComponent(id)}/evidence`, { signal: task.signal });
    if (!task.isCurrent()) return;
    state.evidence = evidence;
    state.evidenceLoading = false;
    renderEvidence();
  } catch (error) {
    if (task.isCurrent()) state.evidenceError = error.message;
  } finally {
    if (task.isCurrent()) {
      state.evidenceLoading = false;
      byId("case-detail").setAttribute("aria-busy", "false");
      renderEvidence();
    }
  }
}

function openCreate() {
  state.editing = false;
  text(byId("form-title"), "New case");
  byId("case-form").reset();
  byId("form-version").value = "";
  byId("form-property-choice").disabled = false;
  populatePropertyChoices(EXAMPLE_PROPERTY.reference, EXAMPLE_PROPERTY.address);
  byId("form-from").value = "2019-01-01";
  byId("form-to").value = "2026-12-31";
  byId("form-tier").value = "B";
  byId("form-error").hidden = true;
  byId("case-dialog").showModal();
  byId("form-name").focus();
}

function openEdit() {
  if (!state.evidence) return;
  state.editing = true;
  const item = state.evidence.market_case;
  text(byId("form-title"), "Edit case");
  byId("form-version").value = item.version;
  byId("form-name").value = item.name;
  populatePropertyChoices(item.property_ref, item.address_display);
  byId("form-property-choice").disabled = true;
  byId("form-from").value = item.date_from;
  byId("form-to").value = item.date_to;
  byId("form-status").value = item.status;
  byId("form-tier").value = item.filters?.minimum_match_tier || "B";
  byId("form-notes").value = item.notes;
  byId("form-error").hidden = true;
  byId("case-dialog").showModal();
  byId("form-name").focus();
}

function formPayload() {
  return {
    name: byId("form-name").value.trim(),
    address_display: byId("form-address").value.trim(),
    date_from: byId("form-from").value,
    date_to: byId("form-to").value,
    status: byId("form-status").value,
    notes: byId("form-notes").value.trim(),
    filters: { minimum_match_tier: byId("form-tier").value },
  };
}

async function saveCase(event) {
  event.preventDefault();
  if (saving) return;
  saving = true;
  const button = event.submitter;
  if (button) button.disabled = true;
  byId("form-error").hidden = true;
  try {
  const payload = formPayload();
  let saved;
  if (state.editing) {
    payload.version = Number(byId("form-version").value);
    saved = await api(`/market-cases/${state.selectedId}`, { method: "PUT", body: JSON.stringify(payload) });
  } else {
    payload.property_ref = byId("form-property").value.trim();
    saved = await api("/market-cases", { method: "POST", body: JSON.stringify(payload) });
  }
  byId("case-dialog").close();
  notify(`Saved “${saved.name}”.`);
  await loadCases(saved.id);
  } catch (error) {
    text(byId("form-error"), error.message);
    byId("form-error").hidden = false;
    byId("form-error").focus();
  } finally {
    saving = false;
    if (button) button.disabled = false;
  }
}

async function deleteCase() {
  if (!state.evidence || deleting) return;
  const item = state.evidence.market_case;
  if (!window.confirm(`Delete “${item.name}”? This cannot be undone.`)) return;
  deleting = true;
  try {
  await api(`/market-cases/${item.id}`, { method: "DELETE" });
  state.selectedId = null;
  notify(`Deleted “${item.name}”.`);
  await loadCases();
  } finally { deleting = false; }
}

function selectedCase() {
  return state.cases.find((item) => item.id === state.selectedId) || null;
}

function syncAssistantContext() {
  // The backend answers one saved case, so the composer must not exist before a case is bound;
  // an unscoped turn is rejected as a missing case_id, which reads like a fault to the user.
  const item = selectedCase();
  byId("assistant-requires-case").hidden = Boolean(item);
  byId("assistant-root").hidden = !item;
  if (!item) return;
  if (!state.assistant) initialiseAssistant();
  state.assistant.controller.setContext({ market_case_id: item.id, display_label: item.name });
}

function initialiseAssistant() {
  state.assistant = createFeatureAssistant({
    root: byId("assistant-root"),
    apiRoot: `${API}/assistant`,
    featureKey: "student-2-market-intelligence",
    featureLabel: "Sales & market",
    returnTo: "/features/market-intelligence/#market-cases",
    scopes: [{ id: "feature", label: "Sales & market", description: "Recorded sale observations, deterministic case summaries and this feature's published guidance." }],
    suggestions: [
      "Explain the recorded sales, exclusions and limitations in this case.",
      "What does the match tier threshold exclude from this summary?",
      "What can this evidence not tell me about the property's value?",
    ],
    title: "Ask about this case",
    description: "Ask about the selected case's recorded sales, exclusions and limits. Every answer is a bounded, reviewable AI activity run.",
    welcomeTitle: "What would you like to understand?",
    welcomeMessage: "I read this case through two read-only tools and the feature's published guidance. I do not estimate value, forecast prices or recommend whether to buy.",
    placeholder: "Ask about the recorded sales, exclusions or limits of this case...",
    announce: (message) => notify(message),
  });
}

function initialise() {
byId("retry-evidence").addEventListener("click", () => loadEvidence());
byId("case-list").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-case-id]");
  if (!button) return;
  state.selectedId = button.dataset.caseId;
  notify("");
  await loadEvidence().catch((error) => notify(error.message, true));
});
byId("new-case").addEventListener("click", openCreate);
byId("edit-case").addEventListener("click", openEdit);
byId("form-property-choice").addEventListener("change", syncSelectedProperty);
byId("delete-case").addEventListener("click", () => deleteCase().catch((error) => notify(error.message, true)));
byId("close-dialog").addEventListener("click", () => byId("case-dialog").close());
byId("cancel-dialog").addEventListener("click", () => byId("case-dialog").close());
byId("case-form").addEventListener("submit", (event) => saveCase(event).catch((error) => notify(error.message, true)));

loadCases().catch((error) => {
  notify(`Sales & market could not be loaded: ${error.message}`, true);
  state.evidenceLoading = false;
  state.evidenceError = error.message;
  state.evidence = null;
  renderEvidence();
});

  window.addEventListener("pagehide", () => { evidenceTask.cancel(); state.assistant?.controller.destroy(); }, { once: true });
}

if (typeof document !== "undefined") initialise();
