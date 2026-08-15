import { collection, entity, queryString } from "../core/api.js";
import { append, button, el } from "../core/dom.js";
import { coverageRows, formatDate, formatNumber, humanise, reportReleaseRows, researchAreaLabel, statusTone } from "../core/formats.js";
import { routeQuery } from "../core/router.js";
import { badge, detailList, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable } from "../components/tables.js";

export function createPropertyRoutes({ view, request, announce }) {
  async function renderProperties() {
    view.replaceChildren();
    const hero = el("section", "discovery-hero");
    append(hero, el("p", "eyebrow", "Explore properties"), el("h1", "", "Trace an NSW address to the evidence behind it"), el("p", "", "Search the accepted property registry, inspect match provenance and see which research areas have usable evidence."));
    const form = el("form", "search-box");
    const input = el("input");
    input.type = "search";
    input.name = "q";
    input.placeholder = "Try 11 Example Street, Sydney NSW 2000";
    input.autocomplete = "street-address";
    input.maxLength = 250;
    input.required = true;
    input.value = routeQuery(location.hash).get("q") || "";
    const search = button("Search", "button primary");
    search.type = "submit";
    append(form, input, search);
    append(hero, form, el("p", "search-help", "NSW only · Maximum 25 matches · Search works without AI"));
    append(view, hero);
    const resultHost = el("div");
    append(resultHost, emptyState("Start with a street address", "Results include an accessible list and table-based coordinate context. No map interaction is required."));
    append(view, resultHost);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const query = input.value.trim();
      history.replaceState(null, "", `#properties${queryString({ q: query })}`);
      resultHost.replaceChildren(el("section", "loading-state", "Searching the accepted property registry…"));
      try {
        const result = await request(`properties/search${queryString({ q: query, state: "NSW", limit: 25 })}`);
        const items = collection(result.body);
        if (result.body.supported === false) resultHost.replaceChildren(el("div", "notice warning", "This query is outside the supported NSW coverage. Try an NSW street address."));
        else if (!items.length) resultHost.replaceChildren(emptyState("No canonical property found", "Try including a street number, suburb and four-digit postcode. PropertyScope will not invent or silently broaden a match."));
        else {
          renderPropertyResults(resultHost, items);
          announce(`${items.length} property matches found.`);
        }
      } catch (error) {
        resultHost.replaceChildren(errorState(error, () => form.requestSubmit()));
      }
    });

    if (input.value) queueMicrotask(() => form.requestSubmit());
  }

  function renderPropertyResults(host, items) {
    const layout = el("div", "property-results");
    const listBody = el("div", "result-list");
    listBody.setAttribute("aria-label", "Property matches");
    const detailHost = el("div");
    items.forEach((item, index) => {
      const result = el("button", "result-card");
      result.type = "button";
      append(result, el("strong", "", item.address_display), el("span", "", `${item.locality || ""} ${item.state || "NSW"} ${item.postcode || ""} · ${humanise(item.resolution_status || item.match?.status)}`));
      result.addEventListener("click", () => selectProperty(item, detailHost, result, listBody));
      append(listBody, result);
      if (index === 0) queueMicrotask(() => result.click());
    });
    append(layout, panel(`${items.length} matches`, "Select a result to inspect evidence", listBody), detailHost);
    host.replaceChildren(layout);
  }

  async function selectProperty(summary, host, selectedButton, list) {
    for (const item of list.querySelectorAll(".result-card")) item.removeAttribute("aria-current");
    selectedButton.setAttribute("aria-current", "true");
    host.replaceChildren(panel("Property evidence", "Loading accepted snapshot…", el("div", "loading-state", "Loading…")));
    try {
      const [detailResult, mapResult, coverageResult, reportResult] = await Promise.all([
        request(`properties/${encodeURIComponent(summary.property_ref)}`),
        request(`properties/${encodeURIComponent(summary.property_ref)}/map-context`),
        request(`properties/${encodeURIComponent(summary.property_ref)}/coverage`),
        request(`properties/${encodeURIComponent(summary.property_ref)}/report-section`).catch((error) => ({ error })),
      ]);
      const property = entity(detailResult.body, "property");
      const map = entity(mapResult.body);
      const coverage = coverageRows(coverageResult.body).length ? coverageRows(coverageResult.body) : (detailResult.body.coverage || []);
      const body = el("div", "stack");
      append(body, el("div", "notice", `Canonical property reference: ${property.property_ref}. Match evidence is shown explicitly; aliases are not silently merged.`));
      const mapPanel = el("div", "map-context");
      const latitude = map.latitude ?? map.coordinates?.latitude ?? property.latitude ?? property.coordinates?.latitude;
      const longitude = map.longitude ?? map.coordinates?.longitude ?? property.longitude ?? property.coordinates?.longitude;
      append(mapPanel, el("span", "map-pin", "⌖"), el("div", "map-caption", `${latitude ?? "Unknown latitude"}, ${longitude ?? "unknown longitude"} · Map-style context with accessible evidence below`));
      append(body, mapPanel, detailList([["Canonical address", property.address_display || property.display_address], ["Locality", property.locality], ["Postcode", property.postcode], ["Resolution", badge(property.resolution_status || summary.resolution_status || property.match?.tier)], ["Match source", summary.match?.source || property.match?.source], ["Match score", summary.match?.score ?? summary.match?.confidence ?? property.match?.score ?? property.match?.confidence ?? "Not supplied"]]));
      const cards = el("div", "coverage-grid");
      for (const item of coverage) {
        const card = el("div", `coverage-card ${statusTone(item.status || item.coverage_status || item.state)}`);
        append(card, el("strong", "", item.dataset || item.dataset_id || researchAreaLabel(item.feature || item.target_feature)), el("span", "", `${humanise(item.status || item.coverage_status || item.state)}${item.release_version ? ` · ${item.release_version}` : ""}${item.limitation ? ` · ${item.limitation}` : ""}`));
        append(cards, card);
      }
      if (coverage.length) append(body, el("h3", "", "Evidence coverage"), cards);
      append(body, renderPropertyReportSection(reportResult));
      append(body, technicalDetails({ identifiers: detailResult.body.identifiers || [], aliases: detailResult.body.aliases || [], map }, "Identifiers, aliases and coordinate evidence"));
      host.replaceChildren(panel("Property evidence", "Accepted snapshot and provenance", body));
    } catch (error) {
      host.replaceChildren(errorState(error, () => selectProperty(summary, host, selectedButton, list)));
    }
  }

  function renderPropertyReportSection(result) {
    const section = el("section", "panel report-section");
    const heading = el("div", "panel-heading");
    const copy = el("div");
    append(copy, el("h3", "", "Evidence summary"), el("p", "", "Bounded identity and accepted dataset facts for reuse in reports"));
    append(heading, copy);
    append(section, heading);
    const body = el("div", "panel-body");
    if (result?.error) {
      append(body, el("div", "notice warning", `Report evidence is temporarily unavailable. Property discovery remains usable.${result.error.requestId ? ` Request ID ${result.error.requestId}` : ""}`));
      append(section, body);
      return section;
    }
    const report = result?.body || {};
    const identity = report.identity || {};
    append(body, detailList([
      ["Property reference", el("code", "mono", report.property_ref || "Not supplied")],
      ["Address", report.address_display || "Not supplied"],
      ["G-NAF PID", identity.gnaf_pid || "Not supplied"],
      ["Resolution", humanise(identity.resolution_status)],
      ["Locality", identity.locality || "Not supplied"],
      ["Evidence entries", formatNumber(report.evidence_count)],
    ]));
    const releases = reportReleaseRows(report);
    if (!releases.length) append(body, el("p", "", "No accepted dataset evidence is available for this summary."));
    else append(body, makeTable(
      [{ label: "Dataset" }, { label: "Research area" }, { label: "Release" }, { label: "Status" }, { label: "Accepted" }, { label: "Coverage" }],
      releases,
      (item) => {
        const row = el("tr");
        append(row, cell(item.dataset_id || "—", "primary-cell"), cell(researchAreaLabel(item.target_feature)), cell(item.release_version || item.dataset_release_id || "—"), cell(badge(item.coverage_status)), cell(formatDate(item.accepted_at || item.checked_at)), cell(item.coverage_scope ? technicalDetails(item.coverage_scope, "Inspect") : "—"));
        return row;
      },
    ));
    if (identity.geometry) append(body, technicalDetails(identity.geometry, "Report coordinate evidence"));
    append(section, body);
    return section;
  }

  return { renderProperties };
}
