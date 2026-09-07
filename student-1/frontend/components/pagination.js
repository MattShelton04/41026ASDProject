import { append, el, link } from "../core/dom.js";
import { queryString } from "../core/api.js";
import { formatNumber } from "../core/formats.js";

export function pageOffset(params) {
  const value = Number(params.get("offset") || 0);
  return Number.isInteger(value) && value >= 0 && value <= 1000000 ? value : 0;
}

/** Keep list navigation bounded and filters encoded in native, bookmarkable links. */
export function collectionPagination(route, filters, body, offset) {
  const root = el("nav", "collection-pagination");
  root.setAttribute("aria-label", "Result pages");
  const count = Number(body.count ?? body.items?.length ?? 0);
  const limit = Number(body.limit || 100);
  const href = (value) => `#${route}${queryString({ ...filters, offset: value || "" })}`;
  if (offset > 0) append(root, link("Previous page", href(Math.max(0, offset - limit)), "button secondary"));
  append(root, el("span", "field-help", count
    ? `Showing ${formatNumber(offset + 1)}–${formatNumber(offset + count)}`
    : "No more results on this page."));
  const next = body.next_offset;
  if (Number.isInteger(next) && next > offset && next <= 1000000) {
    append(root, link("Next page", href(next), "button secondary"));
  }
  return root;
}
