/** Immutable-release pagination with one in-flight read and explicit DOM ownership. */
import { queryString } from "../core/api.js";
import { append, button, el } from "../core/dom.js";
import { formatNumber, humanise } from "../core/formats.js";
import { disposeTableRegions } from "../browser/index.js";
import { technicalDetails } from "../components/layout.js";
import { emptyState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

export function releasePreviewPanel(releaseId, initialPage, { request, isCurrent, displayState }) {
  const host = el("section", "panel");
  const heading = el("div", "panel-heading");
  const copy = el("div");
  append(copy, el("h2", "", "Dataset preview"), el("p", "", "Rows from this version only"));
  append(heading, copy);
  const body = el("div", "panel-body");
  append(host, heading, body);
  let pending = false;

  const renderPage = (page, { focus = false } = {}) => {
    disposeTableRegions(body);
    body.replaceChildren();
    const release = page.release || {};
    append(body, el("div", "notice", `${humanise(displayState || release.status)} version · ${formatNumber(page.total)} previewable ${humanise(page.profile)} records. No other version is included.`));
    if (!page.items?.length) {
      append(body, emptyState("No preview rows", "This release has no rows in its registered warehouse projection."));
      return;
    }
    const columns = page.columns || Object.keys(page.items[0]);
    const table = makeTable(columns.map((column) => ({ label: humanise(column) })), page.items, (item) => {
      const row = el("tr");
      columns.forEach((column, index) => {
        const value = previewValue(item[column]);
        append(row, cell(index === 0 && !(value instanceof Node) ? primaryCell(value) : value, index === 0 ? "primary-cell" : ""));
      });
      return row;
    }, "Dataset preview records");
    append(body, table);
    const controls = el("div", "dialog-actions");
    const previous = button("Previous page", "button secondary");
    const next = button("Next page", "button secondary");
    const errorHost = el("div", "notice warning");
    errorHost.setAttribute("role", "alert");
    errorHost.hidden = true;
    const syncControls = () => {
      previous.disabled = pending || page.offset <= 0;
      next.disabled = pending || page.next_offset === null || page.next_offset === undefined;
      body.setAttribute("aria-busy", String(pending));
    };
    const load = async (offset) => {
      if (pending || !host.isConnected || !isCurrent()) return;
      pending = true;
      syncControls();
      errorHost.hidden = true;
      try {
        const result = await request(`dataset-releases/${releaseId}/records${queryString({ limit: page.limit || 25, offset })}`);
        if (!host.isConnected || !isCurrent()) return;
        pending = false;
        renderPage(result.body, { focus: true });
      } catch (error) {
        if (!host.isConnected || !isCurrent()) return;
        errorHost.textContent = `${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`;
        errorHost.hidden = false;
      } finally {
        pending = false;
        syncControls();
      }
    };
    previous.addEventListener("click", () => load(Math.max(0, page.offset - page.limit)));
    next.addEventListener("click", () => load(page.next_offset));
    const summary = el("span", "field-help", `Showing ${formatNumber(page.offset + 1)}–${formatNumber(page.offset + page.count)} of ${formatNumber(page.total)}`);
    summary.tabIndex = -1;
    summary.setAttribute("role", "status");
    append(controls, summary, previous, next);
    append(body, errorHost, controls);
    syncControls();
    if (focus) summary.focus({ preventScroll: true });
  };
  renderPage(initialPage);
  return host;
}

function previewValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    const encoded = JSON.stringify(value);
    return encoded.length > 80 ? technicalDetails(value, "Inspect value") : el("code", "mono", encoded);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}
