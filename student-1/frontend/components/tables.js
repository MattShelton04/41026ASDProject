import { append, el } from "../core/dom.js";

export function makeTable(columns, rows, rowBuilder, captionText = "Data results") {
  const wrap = el("div", "table-wrap");
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
  append(wrap, table);
  return wrap;
}

export function cell(content, className = "") {
  const node = el("td", className);
  append(node, content instanceof Node ? content : document.createTextNode(String(content ?? "—")));
  return node;
}

export function primaryCell(primary, secondary = "") {
  const node = el("span", "primary-cell", primary || "Untitled");
  if (secondary) append(node, el("span", "sub-cell", secondary));
  return node;
}
