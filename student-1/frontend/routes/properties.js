import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { coverageRows, formatDate, formatNumber, humanise, reportReleaseRows, researchAreaLabel, statusTone } from "../core/formats.js";
import { routeQuery } from "../core/router.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable } from "../components/tables.js";

export function createPropertyRoutes({ view, request, announce }) {
  async function renderProperties(propertyRef = "") {
    if (propertyRef) return renderPropertyDetail(propertyRef);
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
          renderPropertyResults(resultHost, items, query);
          announce(`${items.length} property matches found.`);
        }
      } catch (error) {
        resultHost.replaceChildren(errorState(error, () => form.requestSubmit()));
      }
    });

    if (input.value) queueMicrotask(() => form.requestSubmit());
  }

  function renderPropertyResults(host, items, query) {
    const layout = el("div", "property-results");
    const listBody = el("div", "result-list");
    listBody.setAttribute("aria-label", "Property matches");
    items.forEach((item) => {
      const result = el("button", "result-card");
      result.type = "button";
      result.setAttribute("aria-label", `Open ${item.address_display}`);
      append(result, el("strong", "", item.address_display), el("span", "", `${item.locality || ""} ${item.state || "NSW"} ${item.postcode || ""} · ${humanise(item.resolution_status || item.match?.status)} · match score ${item.score ?? item.match?.score ?? "not supplied"}`));
      result.addEventListener("click", () => { location.hash = `#properties/${encodeURIComponent(item.property_ref)}${queryString({ q: query })}`; });
      append(listBody, result);
    });
    const coordinateRows = makeTable(
      [{ label: "Address" }, { label: "Property reference" }, { label: "Latitude" }, { label: "Longitude" }, { label: "Resolution" }], items,
      (item) => { const row = el("tr"); append(row, cell(item.address_display, "primary-cell"), cell(item.property_ref, "mono"), cell(item.latitude ?? "Unknown"), cell(item.longitude ?? "Unknown"), cell(badge(item.resolution_status || "unknown"))); return row; },
    );
    append(layout, panel(`${items.length} matches`, "Stable identities, not listing duplicates", listBody), panel("Coordinate evidence", "Accessible text alternative to spatial context", coordinateRows));
    host.replaceChildren(layout);
  }

  async function renderPropertyDetail(propertyRef) {
    view.replaceChildren(el("section", "loading-state", "Loading canonical property evidence…"));
    try {
      const [detailResult, mapResult, coverageResult, reportResult] = await Promise.allSettled([
        request(`properties/${encodeURIComponent(propertyRef)}`),
        request(`properties/${encodeURIComponent(propertyRef)}/map-context`),
        request(`properties/${encodeURIComponent(propertyRef)}/coverage`),
        request(`properties/${encodeURIComponent(propertyRef)}/report-section`),
      ]);
      if (detailResult.status === "rejected") throw detailResult.reason;
      const detailPayload = detailResult.value.body;
      const property = entity(detailPayload, "property");
      const map = mapResult.status === "fulfilled" ? entity(mapResult.value.body) : {};
      const coverage = coverageResult.status === "fulfilled" && coverageRows(coverageResult.value.body).length ? coverageRows(coverageResult.value.body) : (detailPayload.coverage || []);
      const query = routeQuery(location.hash).get("q") || "";
      view.replaceChildren();
      append(view, pageHeading("Verified property identity", property.address_display || property.display_address || "Property record", "Canonical NSW address evidence with explicit aliases, identifiers, coordinates and accepted-release coverage.", [link("Back to property search", `#properties${queryString({ q: query })}`, "button secondary")]));
      append(view, el("div", "notice", `Stable property reference ${property.property_ref}. Other research areas receive only this reference and remain independently owned.`));
      const body = el("div", "stack");
      const mapPanel = el("div", "map-context");
      const latitude = map.latitude ?? map.coordinates?.latitude ?? property.latitude ?? property.coordinates?.latitude;
      const longitude = map.longitude ?? map.coordinates?.longitude ?? property.longitude ?? property.coordinates?.longitude;
      append(mapPanel, el("span", "map-pin", "⌖"), el("div", "map-caption", `${latitude ?? "Unknown latitude"}, ${longitude ?? "unknown longitude"} · Visual coordinate context; the table below is the authoritative accessible fallback.`));
      append(body, mapPanel, makeTable([{ label: "Coordinate evidence" }, { label: "Value" }], [{ label: "Latitude", value: latitude ?? "Unknown" }, { label: "Longitude", value: longitude ?? "Unknown" }, { label: "Geometry type", value: map.geometry?.type || property.geometry?.type || "Unknown" }], (item) => { const row = el("tr"); append(row, cell(item.label, "primary-cell"), cell(String(item.value), item.label === "Geometry type" ? "" : "mono")); return row; }));
      append(body, detailList([["Canonical address", property.address_display || property.display_address], ["Property reference", el("code", "mono", property.property_ref)], ["Locality", property.locality], ["State", property.state], ["Postcode", property.postcode], ["Resolution", badge(property.resolution_status || "unknown")], ["Last updated", formatDate(property.updated_at)], ["Request ID", el("code", "mono", detailResult.value.requestId)]]));
      append(body, evidenceTable("Identifiers and match evidence", detailPayload.identifiers || [], [
        ["Scheme", (item) => item.scheme], ["Identifier", (item) => item.identifier_value], ["Match method", (item) => humanise(item.match_method)], ["Confidence", (item) => item.match_confidence ?? "Unknown"], ["Current", (item) => item.is_current ? "Yes" : "No"], ["Evidence", (item) => item.evidence_json ? technicalDetails(item.evidence_json, "Inspect") : "Unknown"],
      ], "No source identifiers are recorded. Identity confidence is therefore unknown."));
      append(body, evidenceTable("Address aliases", detailPayload.aliases || [], [
        ["Alias", (item) => item.alias_display], ["Kind", (item) => humanise(item.alias_kind)], ["Source identifier", (item) => item.source_identifier || "Unknown"], ["Current", (item) => item.is_current ? "Yes" : "No"],
      ], "No address aliases are recorded for this property."));
      const cards = el("div", "coverage-grid");
      for (const item of coverage) {
        const card = el("div", `coverage-card ${statusTone(item.status || item.coverage_status || item.state)}`);
        append(card, el("strong", "", item.dataset || item.dataset_id || researchAreaLabel(item.feature || item.target_feature)), el("span", "", `${humanise(item.status || item.coverage_status || item.state)}${item.release_version ? ` · ${item.release_version}` : ""}${item.limitation ? ` · ${item.limitation}` : ""}`));
        append(cards, card);
      }
      if (coverage.length) append(body, el("h2", "", "Research-area coverage"), cards);
      else append(body, emptyState("Coverage is unknown", coverageResult.status === "rejected" ? `Coverage evidence is temporarily unavailable.${problemSuffix(coverageResult.reason)}` : "No accepted coverage entries are recorded. This does not confirm absence."));
      append(body, renderPropertyReportSection(reportResult.status === "fulfilled" ? reportResult.value : { error: reportResult.reason }));
      if (mapResult.status === "rejected") append(body, el("div", "notice warning", `Spatial context is temporarily unavailable; canonical identity remains usable.${problemSuffix(mapResult.reason)}`));
      append(view, panel("Canonical identity and evidence", "Accepted snapshot with bounded provenance", body));
    } catch (error) {
      view.replaceChildren(errorState(error, () => renderPropertyDetail(propertyRef)));
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

function evidenceTable(title, items, columns, emptyCopy) {
  const body = el("div", "stack"); append(body, el("h2", "", title));
  if (!items.length) { append(body, el("p", "", emptyCopy)); return body; }
  append(body, makeTable(columns.map(([label]) => ({ label })), items, (item) => { const row = el("tr"); columns.forEach(([, value], index) => append(row, cell(value(item), index === 0 ? "primary-cell" : ""))); return row; }));
  return body;
}

function problemSuffix(error) { return error?.requestId ? ` Request ID ${error.requestId}.` : ""; }
