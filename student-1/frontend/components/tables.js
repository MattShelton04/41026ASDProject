import { append, el } from "../core/dom.js";
import { createTableRegion } from "../browser/index.js?v=2";

export function makeTable(columns, rows, rowBuilder, captionText = "Data results") {
  const table = el("table");
  const caption = el("caption", "visually-hidden", captionText);
  const thead = el("thead");
  const headingRow = el("tr");
  for (const column of columns) {
    const heading = el("th", column.className || "", column.label);
    heading.scope = "col";
    append(headingRow, heading);
  }
  append(thead, headingRow);
  const tbody = el("tbody");
  rows.forEach((item, index) => append(tbody, rowBuilder(item, index)));
  append(table, caption, thead, tbody);
  return createTableRegion(table, captionText, { className: "table-wrap" });
}

export function cell(content, className = "") {
  const node = el("td", className);
  append(node, content instanceof Node ? content : document.createTextNode(String(content ?? "—")));
  return node;
}

export function primaryCell(primary, secondary = "") {
  const node = el("span", "primary-cell");
  append(node, primary instanceof Node ? primary : document.createTextNode(String(primary || "Untitled")));
  if (secondary) append(node, el("span", "sub-cell", secondary));
  return node;
}
