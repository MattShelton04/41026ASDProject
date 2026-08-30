import { append, el } from "../core/dom.js";
import { createTableRegion } from "../browser/index.js";

export function makeTable(columns, rows, rowBuilder, captionText = "Data results", { responsive = false } = {}) {
  const table = el("table", responsive ? "responsive-table" : "");
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
  rows.forEach((item, index) => {
    const row = rowBuilder(item, index);
    [...row.children].forEach((cellNode, columnIndex) => {
      if (cellNode.tagName === "TD") cellNode.dataset.label = columns[columnIndex]?.label || "Value";
    });
    append(tbody, row);
  });
  append(table, caption, thead, tbody);
  const region = createTableRegion(table, captionText, { className: "table-wrap" });
  if (responsive) region.classList.add("table-wrap--responsive");
  return region;
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

export function technicalReference(value, limit = 18) {
  const full = String(value || "Not recorded");
  const visible = full.length > limit ? `${full.slice(0, limit)}…` : full;
  const code = el("code", "mono technical-reference", visible);
  code.title = full;
  code.setAttribute("aria-label", full);
  return code;
}

export function actionMenu(label, controls) {
  const root = el("span", "action-menu");
  const trigger = el("button", "button secondary small action-menu__trigger", "⋯");
  trigger.type = "button";
  trigger.setAttribute("aria-label", label);
  trigger.setAttribute("aria-haspopup", "true");
  trigger.setAttribute("aria-expanded", "false");

  const panel = el("span", "action-menu__panel");
  panel.hidden = true;
  panel.setAttribute("role", "group");
  panel.setAttribute("aria-label", label);
  for (const control of controls) {
    control.classList.add("action-menu__item");
    append(panel, control);
  }

  const position = () => {
    if (panel.hidden) return;
    const triggerRect = trigger.getBoundingClientRect();
    const panelRect = panel.getBoundingClientRect();
    const gutter = 8;
    const left = Math.max(gutter, Math.min(window.innerWidth - panelRect.width - gutter, triggerRect.right - panelRect.width));
    let top = triggerRect.bottom + 6;
    if (top + panelRect.height > window.innerHeight - gutter) top = Math.max(gutter, triggerRect.top - panelRect.height - 6);
    panel.style.left = `${left}px`;
    panel.style.top = `${top}px`;
  };
  const outsidePointer = (event) => {
    if (!root.contains(event.target)) close();
  };
  const reposition = () => position();
  const close = ({ restoreFocus = false } = {}) => {
    if (panel.hidden) return;
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    document.removeEventListener("pointerdown", outsidePointer, true);
    window.removeEventListener("resize", reposition);
    window.removeEventListener("scroll", reposition, true);
    if (restoreFocus) trigger.focus();
  };
  const open = ({ focusFirst = false } = {}) => {
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    position();
    document.addEventListener("pointerdown", outsidePointer, true);
    window.addEventListener("resize", reposition);
    window.addEventListener("scroll", reposition, true);
    if (focusFirst) panel.querySelector("a, button")?.focus();
  };

  trigger.addEventListener("click", () => panel.hidden ? open() : close({ restoreFocus: true }));
  trigger.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowDown") return;
    event.preventDefault();
    open({ focusFirst: true });
  });
  panel.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    close({ restoreFocus: true });
  });
  panel.addEventListener("click", (event) => {
    if (event.target.closest("a, button")) close();
  });
  append(root, trigger, panel);
  return root;
}
