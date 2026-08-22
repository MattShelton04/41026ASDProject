import { append, button, el } from "../core/dom.js";
import { humanise } from "../core/formats.js?v=17";

export function filterToolbar({ search = "", status = "", statuses = [], placeholder = "Filter results", onApply }) {
  const form = el("form", "toolbar");
  const fields = el("div", "filter-row");
  const searchLabel = el("label", "field");
  append(searchLabel, el("span", "", "Search"));
  const searchInput = el("input");
  searchInput.type = "search";
  searchInput.name = "q";
  searchInput.placeholder = placeholder;
  searchInput.value = search;
  append(searchLabel, searchInput);
  append(fields, searchLabel);
  if (statuses.length) {
    const statusLabel = el("label", "field");
    append(statusLabel, el("span", "", "Status"));
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
  append(form, fields, apply);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    onApply(Object.fromEntries(new FormData(form)));
  });
  return form;
}

export function formField(definition, value = "") {
  const label = el("label", definition.wide ? "wide" : "");
  const title = el("span", "", definition.label);
  if (definition.help) append(title, document.createTextNode(" "), el("small", "", definition.help));
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
  input.required = Boolean(definition.required);
  input.disabled = Boolean(definition.disabled);
  if (definition.min !== undefined) input.min = definition.min;
  if (definition.max !== undefined) input.max = definition.max;
  if (definition.pattern) input.pattern = definition.pattern;
  if (definition.type === "json") input.value = JSON.stringify(value || {}, null, 2);
  else if (definition.type === "json_array") input.value = JSON.stringify(value || [], null, 2);
  else input.value = value ?? "";
  append(label, title, input);
  return label;
}
