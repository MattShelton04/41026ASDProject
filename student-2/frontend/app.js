const API = "/api/market-intelligence/v1";
const EXAMPLE_PROPERTY = {
  reference: "a0000000-0000-0000-0000-000000000001",
  address: "11 Example Street, Sydney NSW 2000",
};
const UUID_PATTERN = /\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b/gi;
const money = new Intl.NumberFormat("en-AU", {
  style: "currency",
  currency: "AUD",
  maximumFractionDigits: 0,
});

const state = { cases: [], selectedId: null, evidence: null, editing: false };
const byId = (id) => document.getElementById(id);

function text(node, value) {
  node.textContent = value == null || value === "" ? "Not available" : String(value);
}

function clear(node) {
  while (node.firstChild) node.firstChild.remove();
}

function el(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (value != null) node.textContent = String(value);
  return node;
}

function humanise(value) {
  return String(value || "unknown").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function redactInternalIdentifiers(value) {
  return String(value)
    .replace(UUID_PATTERN, "[internal reference hidden]")
    .replace(/\bmarket_case_id\b/gi, "market case")
    .replace(/\bproperty_ref\b/gi, "property");
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
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const body = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
  if (!response.ok) throw new Error(body.detail || body.title || "Request failed");
  return body;
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
    const level = Math.max(1, Math.ceil((Number(item.transactions) / maximum) * 6));
    const bar = el("div", `volume-bar volume-bar--${level}`);
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", `${item.transactions} transactions in ${item.period}`);
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
  byId("empty-state").hidden = Boolean(evidence);
  byId("case-detail").hidden = !evidence;
  if (!evidence) return;
  const item = evidence.market_case;
  const summary = evidence.summary;
  text(byId("case-title"), item.name);
  text(byId("case-address"), item.address_display);
  text(byId("case-status"), humanise(item.status));
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
  if (!state.selectedId) {
    state.evidence = null;
    renderEvidence();
    return;
  }
  state.evidence = await api(`/market-cases/${state.selectedId}/evidence`);
  renderEvidence();
  renderCases();
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
  byId("case-dialog").showModal();
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
  byId("case-dialog").showModal();
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
}

async function deleteCase() {
  if (!state.evidence) return;
  const item = state.evidence.market_case;
  if (!window.confirm(`Delete “${item.name}”? This cannot be undone.`)) return;
  await api(`/market-cases/${item.id}`, { method: "DELETE" });
  state.selectedId = null;
  notify(`Deleted “${item.name}”.`);
  await loadCases();
}

function answerText(result) {
  if (!result || typeof result !== "object") return "The run completed without a displayable answer.";
  const preferred = ["summary", "findings", "recommended_next_step", "safety_note", "evidence"];
  const lines = [];
  for (const key of preferred) {
    const value = result[key];
    if (value == null) continue;
    lines.push(`${humanise(key)}:\n${redactInternalIdentifiers(Array.isArray(value) ? value.join("\n") : value)}`);
  }
  return lines.join("\n\n") || redactInternalIdentifiers(JSON.stringify(result, null, 2));
}

async function pollAssistant(runId) {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    const detail = await api(`/assistant/turns/${runId}`);
    const run = detail.run || detail;
    text(byId("assistant-answer"), `${humanise(run.status)} · run ${runId.slice(0, 8)}…`);
    if (run.status === "succeeded") {
      text(byId("assistant-answer"), answerText(run.final_result));
      return;
    }
    if (["failed", "cancelled", "timed_out"].includes(run.status)) {
      throw new Error(run.error?.message || `AI run ${humanise(run.status)}`);
    }
    await new Promise((resolve) => window.setTimeout(resolve, 1200));
  }
  throw new Error("AI run is still active; check AI-mode activity for its durable status.");
}

async function askAssistant(event) {
  event.preventDefault();
  if (!state.selectedId) return;
  const button = event.submitter;
  button.disabled = true;
  text(byId("assistant-answer"), "Starting a bounded Plan → Act → Observe → Adapt run…");
  try {
    const run = await api("/assistant/turns", {
      method: "POST",
      body: JSON.stringify({ case_id: state.selectedId, message: byId("assistant-message").value }),
    });
    await pollAssistant(run.id);
  } catch (error) {
    text(byId("assistant-answer"), `${error.message}\n\nThe deterministic case summary above remains available.`);
  } finally {
    button.disabled = false;
  }
}

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
byId("assistant-form").addEventListener("submit", askAssistant);

loadCases().catch((error) => {
  notify(`Feature 2 could not load: ${error.message}`, true);
  state.evidence = null;
  renderEvidence();
});
