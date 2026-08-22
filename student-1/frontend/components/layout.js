import { append, el } from "../core/dom.js";
import { stateLabel } from "../core/formats.js?v=17";

export function pageHeading(kicker, title, description, actions = []) {
  const heading = el("header", "page-heading");
  const copy = el("div");
  append(copy, el("p", "eyebrow", kicker), el("h1", "", title), el("p", "lede", description));
  append(heading, copy);
  if (actions.length) {
    const controls = el("div", "heading-actions");
    append(controls, actions);
    append(heading, controls);
  }
  return heading;
}

export function panel(title, subtitle = "", body = null, action = null) {
  const section = el("section", "panel");
  const heading = el("div", "panel-heading");
  const copy = el("div");
  append(copy, el("h2", "", title));
  if (subtitle) append(copy, el("p", "", subtitle));
  append(heading, copy, action);
  append(section, heading);
  if (body) {
    if (!body.classList.contains("table-wrap")) body.classList.add("panel-body");
    append(section, body);
  }
  return section;
}

export function disclosurePanel(title, subtitle = "", body = null, { open = false } = {}) {
  const details = el("details", "panel disclosure-panel");
  details.open = open;
  const summary = el("summary", "panel-heading");
  const copy = el("span", "disclosure-copy");
  append(copy, el("span", "disclosure-title", title));
  if (subtitle) append(copy, el("span", "disclosure-subtitle", subtitle));
  append(summary, copy, el("span", "disclosure-action", "Show details"));
  append(details, summary);
  if (body) {
    if (!body.classList.contains("table-wrap")) body.classList.add("panel-body");
    append(details, body);
  }
  return details;
}

export function badge(status) {
  const display = stateLabel(status);
  const node = el("span", `badge ${display.tone}`);
  append(node, el("span", "symbol", display.symbol), document.createTextNode(display.text));
  return node;
}

export function technicalDetails(data, label = "Technical details") {
  const details = el("details", "technical");
  append(details, el("summary", "", label), el("pre", "json", JSON.stringify(data, null, 2)));
  return details;
}

export function detailList(entries) {
  const list = el("dl", "detail-list");
  for (const [label, value] of entries) {
    const item = el("div");
    append(item, el("dt", "", label));
    const description = el("dd");
    append(description, value instanceof Node ? value : document.createTextNode(String(value ?? "Not recorded")));
    append(item, description);
    append(list, item);
  }
  return list;
}
