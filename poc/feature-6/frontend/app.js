import { append, el, withRequestLifecycle } from "./browser/index.js";
import { evidenceLabel, evidenceState, formatCurrency, listItems, routeName } from "./model.js";

const API = "/api/integration-poc/v1";
const routeRoot = document.querySelector("#route");
const toast = document.querySelector("#toast");
let routeController = null;

function setAttributes(node, attributes) {
  for (const [name, value] of Object.entries(attributes)) {
    if (value !== undefined && value !== null) node.setAttribute(name, String(value));
  }
  return node;
}

function field(label, name, options = {}) {
  const wrapper = el("label", `poc-field${options.wide ? " poc-field--wide" : ""}`);
  const caption = el("span", "", label);
  const input = options.multiline ? el("textarea") : el("input");
  input.name = name;
  if (options.type) input.type = options.type;
  if (options.required) input.required = true;
  if (options.placeholder) input.placeholder = options.placeholder;
  if (options.value) input.value = options.value;
  append(wrapper, caption, input);
  return wrapper;
}

function heading(kicker, title, description) {
  const block = el("header", "poc-hero ps-stack");
  append(block, el("p", "ps-badge ps-badge--info", kicker), el("h1", "", title), el("p", "", description));
  return block;
}

function card(title, value, detail = "", state = "") {
  const node = el("article", "ps-card poc-evidence");
  if (state) node.dataset.state = state;
  append(node, el("h2", "ps-card__title", title), el("p", "poc-card-value", value));
  if (detail) append(node, el("p", "", detail));
  return node;
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  window.setTimeout(() => { toast.hidden = true; }, 4000);
}

async function request(path, options = {}, signal = null) {
  return withRequestLifecycle(async (requestSignal) => {
    const response = await fetch(`${API}${path}`, {
      ...options,
      signal: requestSignal,
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}), ...options.headers },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.title || `Request failed (${response.status})`);
    return payload;
  }, { signal, timeoutMs: 10000 });
}

function errorPanel(error) {
  const panel = el("section", "ps-card poc-evidence");
  panel.dataset.state = "needs_verification";
  append(panel, el("h2", "", "This view is unavailable"), el("p", "", error?.message || "Unknown request failure"));
  return panel;
}

function table(headers, rows) {
  const wrap = el("div", "poc-table-wrap");
  const node = el("table", "poc-table");
  const head = el("thead");
  const headRow = el("tr");
  for (const header of headers) append(headRow, el("th", "", header));
  append(head, headRow);
  const body = el("tbody");
  for (const values of rows) {
    const row = el("tr");
    for (const value of values) append(row, el("td", "", value ?? "—"));
    append(body, row);
  }
  append(node, head, body);
  append(wrap, node);
  return wrap;
}

async function readiness(signal) {
  const root = el("div", "ps-stack");
  append(root, heading("Provider integration", "Data readiness", "Compare Feature 1 catalogue state with the POC's independently imported release ledger."));
  try {
    const [status, imports] = await Promise.all([request("/provider/status", {}, signal), request("/imports", {}, signal)]);
    const grid = el("section", "poc-grid");
    append(grid,
      card("Feature 1", status.feature_1?.ready ? "Ready" : "Unavailable", status.feature_1?.detail || "Public HTTP boundary", status.feature_1?.ready ? "complete" : "unavailable"),
      card("POC database", status.store?.ready ? "Ready" : "Unavailable", "Exclusive SQLite owner", status.store?.ready ? "complete" : "unavailable"),
      card("Imported releases", String(listItems(imports).length), "Accepted immutable products only", listItems(imports).length ? "confirmed" : "partial"),
    );
    append(root, grid);
    const rows = listItems(imports).map((item) => [item.dataset_id, item.schema_version, item.target_feature, item.record_count ?? item.rows_accepted, item.provider_release_id || item.release_id]);
    append(root, el("h2", "", "Release ledger"), rows.length ? table(["Dataset", "Schema", "Original target", "Rows", "Release"], rows) : el("p", "poc-empty", "No accepted products have been imported yet. Publication and reconciliation remain explicit operations."));
    const details = el("details");
    append(details, el("summary", "", "Provider catalogue response"), el("pre", "poc-code", JSON.stringify(status.catalogue || {}, null, 2)));
    append(root, details);
  } catch (error) { append(root, errorPanel(error)); }
  return root;
}

async function propertyFinder(signal) {
  const root = el("div", "ps-stack");
  append(root, heading("Feature 1 HTTP consumer", "Property finder", "Search accepted G-NAF-backed identity without downloading or opening Feature 1 data."));
  const form = el("form", "poc-form");
  append(form, field("Address or locality", "q", { required: true, placeholder: "Sydney NSW" }), setAttributes(el("button", "ps-button ps-button--primary", "Search"), { type: "submit" }));
  const results = el("section", "ps-stack");
  append(root, form, results);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    results.replaceChildren(el("p", "", "Searching accepted property identity…"));
    try {
      const query = new FormData(form).get("q");
      const payload = await request(`/properties/search?q=${encodeURIComponent(query)}`, {}, signal);
      const items = listItems(payload);
      if (!items.length) return results.replaceChildren(el("p", "poc-empty", "No supported property identity matched this search."));
      const rows = items.map((item) => {
        const action = el("button", "ps-button ps-button--small", "Research");
        action.type = "button";
        action.addEventListener("click", () => loadResearch(item.property_ref || item.id, results, signal));
        return [item.display_address || item.address_display, item.locality, item.postcode, action];
      });
      const wrap = table(["Address", "Locality", "Postcode", "Action"], rows);
      for (const [index, row] of wrap.querySelectorAll("tbody tr").entries()) row.lastElementChild.replaceChildren(rows[index][3]);
      results.replaceChildren(wrap);
    } catch (error) { results.replaceChildren(errorPanel(error)); }
  });
  return root;
}

async function loadResearch(propertyRef, target, signal) {
  target.replaceChildren(el("p", "", "Composing bounded evidence sections…"));
  try {
    const payload = await request(`/properties/${encodeURIComponent(propertyRef)}/research`, {}, signal);
    const title = el("h2", "", payload.identity?.display_address || payload.identity?.address_display || propertyRef);
    const grid = el("div", "poc-grid");
    for (const [name, section] of Object.entries(payload.sections || {})) {
      const state = evidenceState(section);
      append(grid, card(name.replaceAll("_", " "), evidenceLabel(state), section.summary || section.limitation || "See evidence payload", state));
    }
    const details = el("details");
    append(details, el("summary", "", "Full bounded response"), el("pre", "poc-code", JSON.stringify(payload, null, 2)));
    const aiForm = el("form", "poc-form");
    append(
      aiForm,
      field("Optional AI question", "question", {
        required: true,
        wide: true,
        value: "Summarise the available evidence and list what still needs verification.",
      }),
      setAttributes(el("button", "ps-button", "Request bounded explanation"), { type: "submit" }),
    );
    const aiResult = el(
      "p",
      "poc-callout",
      "AI-mode is optional. Deterministic research above remains usable when the provider is offline.",
    );
    aiForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      aiResult.textContent = "Creating a POC-scoped AI run…";
      const question = new FormData(aiForm).get("question");
      try {
        const run = await request(
          "/agent-runs",
          {
            method: "POST",
            body: JSON.stringify({ property_ref: propertyRef, question }),
            headers: { "Idempotency-Key": `poc-ui-${crypto.randomUUID()}` },
          },
          signal,
        );
        aiResult.textContent = `AI run ${run.run?.run_id || run.run?.id || "created"} is ${run.run?.status || run.ai_state || "queued"}.`;
      } catch (error) {
        aiResult.textContent = `${error.message}. The evidence sections remain available.`;
      }
    });
    target.replaceChildren(title, grid, details, el("h2", "", "Optional AI explanation"), aiForm, aiResult);
  } catch (error) { target.replaceChildren(errorPanel(error)); }
}

const RESOURCE_CONFIG = {
  market: { path: "/market-cases", title: "Sales case", description: "Representative market-case CRUD and transparent deterministic summaries. Comparable and exclusion policy is explicitly unapproved.", property: true },
  place: { path: "/saved-places", title: "Place context", description: "Saved place CRUD with postcode crime observations and school points. No safety score, catchment or liveability ranking.", property: false },
  site: { path: "/site-reviews", title: "Site review", description: "A checklist and evidence-state workspace. Planning, hazards, strata and building evidence remain unavailable until registered products exist.", property: true },
  buyer: { path: "/buyer-cases", title: "Buyer workspace", description: "Representative buyer-case CRUD that composes independent property, sales, place and site sections without erasing gaps.", property: false },
};

async function resourcePage(kind, signal) {
  const config = RESOURCE_CONFIG[kind];
  const root = el("div", "ps-stack");
  append(root, heading("Representative workflow", config.title, config.description));
  const form = el("form", "poc-form");
  append(form, field("Title", "title", { required: true }), field(config.property ? "Property ref" : "Locality / case context", config.property ? "property_ref" : "context", { required: config.property }), field("Notes", "notes", { multiline: true, wide: true }), setAttributes(el("button", "ps-button ps-button--primary", "Create"), { type: "submit" }));
  const list = el("section", "ps-stack");
  append(root, form, list);

  async function refresh() {
    list.replaceChildren(el("p", "", "Loading…"));
    try {
      const payload = await request(config.path, {}, signal);
      const items = listItems(payload);
      if (!items.length) return list.replaceChildren(el("p", "poc-empty", "No user-owned records yet."));
      const rows = items.map((item) => {
        const remove = el("button", "ps-button ps-button--danger ps-button--small", "Delete");
        remove.type = "button";
        remove.addEventListener("click", async () => {
          await request(`${config.path}/${encodeURIComponent(item.id)}`, { method: "DELETE" }, signal);
          showToast(`${config.title} deleted`);
          await refresh();
        });
        return [item.title || item.name, item.status || item.stage || "active", item.property_ref || item.context || "—", remove];
      });
      const wrap = table(["Title", "State", "Context", "Action"], rows);
      for (const [index, row] of wrap.querySelectorAll("tbody tr").entries()) row.lastElementChild.replaceChildren(rows[index][3]);
      list.replaceChildren(wrap);
    } catch (error) { list.replaceChildren(errorPanel(error)); }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const values = Object.fromEntries(new FormData(form));
    try {
      await request(config.path, { method: "POST", body: JSON.stringify(values) }, signal);
      form.reset();
      showToast(`${config.title} created`);
      await refresh();
    } catch (error) { showToast(error.message); }
  });
  await refresh();
  return root;
}

function frictionPage() {
  const root = el("div", "ps-stack");
  append(root, heading("Onboarding findings", "Integration friction", "The POC records concrete gaps encountered while consuming Shared and Feature 1."));
  const findings = [
    "The prose consumer guide and reference HTTP test describe legacy JSON while the live runner emits gzip NDJSON with newer builder versions.",
    "Provider JSON Schemas are owned under student-1 rather than a published consumer contract package.",
    "Feature publication destinations and schema target enums are fixed to Features 1–5; this lab must impersonate Feature 2 and 3 destinations.",
    "Shared navigation, edge routing, checks and Compose onboarding are manually enumerated rather than manifest-driven.",
    "PSI has separate bounded-product and complete-year paging paths with different checkpoint semantics.",
    "There is no shared authentication or user-ownership convention for user-specific CRUD.",
    "Feature 1 correctly has no planning, hazard, strata or building products, so the due-diligence flow remains needs-verification.",
  ];
  const list = el("ol", "ps-stack");
  for (const finding of findings) append(list, el("li", "", finding));
  append(
    root,
    list,
    el(
      "p",
      "poc-callout",
      "Full evidence and suggested sanding are recorded locally in docs/architecture/feature-6-integration-poc.md.",
    ),
  );
  return root;
}

async function render() {
  routeController?.abort();
  routeController = new AbortController();
  const route = routeName(window.location.hash);
  for (const link of document.querySelectorAll(".poc-nav a")) {
    if (link.getAttribute("href") === `#${route}`) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  routeRoot.replaceChildren(el("p", "", "Loading integration view…"));
  try {
    let node;
    if (route === "readiness") node = await readiness(routeController.signal);
    else if (route === "property") node = await propertyFinder(routeController.signal);
    else if (route === "friction") node = frictionPage();
    else node = await resourcePage(route, routeController.signal);
    routeRoot.replaceChildren(node);
    routeRoot.querySelector("h1")?.focus?.();
  } catch (error) {
    if (error?.name !== "AbortError") routeRoot.replaceChildren(errorPanel(error));
  }
}

window.addEventListener("hashchange", render);
render();
