import { append, button, el } from "../core/dom.js";
import { humanise } from "../core/formats.js?v=18";

export function filterToolbar({ search = "", status = "", statuses = [], placeholder = "Filter results", onApply }) {
  const form = el("form", "toolbar");
  const fields = el("div", "filter-row");
  const searchLabel = el("label", "field");
  append(searchLabel, el("span", "", "Search (optional)"));
  const searchInput = el("input");
  searchInput.type = "search";
  searchInput.name = "q";
  searchInput.placeholder = placeholder;
  searchInput.autocomplete = "off";
  searchInput.value = search;
  append(searchLabel, searchInput);
  append(fields, searchLabel);
  if (statuses.length) {
    const statusLabel = el("label", "field");
    append(statusLabel, el("span", "", "Status (optional)"));
    const select = el("select");
    select.name = "status";
    for (const value of statuses) {
      const option = el("option", "", value === "all" || !value ? "All statuses" : humanise(value));
      option.value = value;
      option.selected = value === status;
      append(select, option);
    }
    append(statusLabel, select);
    append(fields, statusLabel);
  }
  const apply = button("Apply filters", "button secondary");
  apply.type = "submit";
  const resetStatus = statuses.includes("all") ? "all" : "";
  const reset = button("Reset filters", "button secondary");
  const actions = el("div", "button-row");
  append(actions, apply, reset);
  append(form, fields, actions);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    onApply(Object.fromEntries(new FormData(form)));
  });
  reset.addEventListener("click", () => onApply({ q: "", status: resetStatus }));
  const active = [];
  if (search) active.push({ key: "q", label: `Search: ${search}`, values: { q: "", status } });
  if (status && status !== "all") active.push({ key: "status", label: `Status: ${humanise(status)}`, values: { q: search, status: resetStatus } });
  if (active.length) {
    const summary = el("div", "active-filters");
    append(summary, el("span", "field-help", `${active.length} active ${active.length === 1 ? "filter" : "filters"}`));
    for (const item of active) {
      const chip = button(`${item.label} ×`, "filter-chip");
      chip.setAttribute("aria-label", `Remove ${item.label} filter`);
      chip.addEventListener("click", () => onApply(item.values));
      append(summary, chip);
    }
    append(form, summary);
  }
  return form;
}

export function formField(definition, value = "") {
  const label = el("label", definition.wide ? "wide" : "");
  const title = el("span", "", `${definition.label} (${definition.required ? "required" : "optional"})`);
  let input;
  if (["textarea", "json", "json_array"].includes(definition.type)) input = el("textarea");
  else if (definition.options) {
    input = el("select");
    for (const optionValue of definition.options) {
      const option = el("option", "", humanise(optionValue));
      option.value = optionValue;
      append(input, option);
    }
  } else {
    input = el("input");
    input.type = definition.type || "text";
  }
  input.name = definition.name;
  input.id = `form-field-${definition.name}`;
  input.required = Boolean(definition.required);
  input.disabled = Boolean(definition.disabled);
  if (definition.min !== undefined) input.min = definition.min;
  if (definition.max !== undefined) input.max = definition.max;
  if (definition.minLength !== undefined) input.minLength = definition.minLength;
  if (definition.maxLength !== undefined) input.maxLength = definition.maxLength;
  if (definition.step !== undefined) input.step = definition.step;
  else if (definition.type === "number") input.step = "1";
  if (definition.inputMode) input.inputMode = definition.inputMode;
  else if (definition.type === "number") input.inputMode = "numeric";
  if (definition.autocomplete) input.autocomplete = definition.autocomplete;
  if (definition.pattern) input.pattern = definition.pattern;
  if (definition.type === "json") input.value = JSON.stringify(value || {}, null, 2);
  else if (definition.type === "json_array") input.value = JSON.stringify(value || [], null, 2);
  else input.value = value ?? "";
  append(label, title, input);
  if (definition.help) append(label, el("small", "field-help", definition.help));
  return label;
}
