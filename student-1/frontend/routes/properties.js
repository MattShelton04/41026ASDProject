import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { confidenceLabel, coverageRows, displayName, formatDate, formatNumber, humanise, reportReleaseRows, researchAreaLabel, statusTone } from "../core/formats.js?v=17";
import { createSubmissionGuard, propertySearchQuery } from "../core/forms.js";
import { routeQuery } from "../core/router.js";
import { badge, detailList, disclosurePanel, pageHeading, panel, technicalDetails } from "../components/layout.js?v=17";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable } from "../components/tables.js";
import { createMap, createOpenFreeMapProvider, featureCollection, pointFeature } from "../mapping/index.js";

export function createPropertyRoutes({ view, request, announce }) {
  async function renderProperties(propertyRef = "") {
    if (propertyRef) return renderPropertyDetail(propertyRef);
    view.replaceChildren();
    const hero = el("section", "discovery-hero");
    append(hero, el("p", "eyebrow", "Property search"), el("h1", "", "Explore NSW properties"), el("p", "", "Find a NSW address and see which sources and research data are available for it."));
    const form = el("form", "search-box");
    form.setAttribute("role", "search");
    const searchField = el("label", "search-field");
    searchField.htmlFor = "property-search-query";
    append(searchField, el("span", "", "NSW street address (required)"));
    const input = el("input");
    input.id = "property-search-query";
    input.type = "search";
    input.name = "q";
    input.placeholder = "Try 11 Example Street, Sydney NSW 2000";
    input.autocomplete = "street-address";
    input.minLength = 2;
    input.maxLength = 200;
    input.required = true;
    input.setAttribute("aria-describedby", "property-search-help property-search-error");
    input.value = routeQuery(location.hash).get("q") || "";
    append(searchField, input);
    const search = button("Search", "button primary");
    search.type = "submit";
    append(form, searchField, search);
    const searchError = el("p", "form-error"); searchError.id = "property-search-error"; searchError.setAttribute("role", "alert");
    const searchHelp = el("p", "search-help", "NSW addresses · 2–200 characters · Best matches first · Address matching does not depend on AI"); searchHelp.id = "property-search-help";
    append(hero, form, searchError, searchHelp);
    append(view, hero);
    const resultHost = el("div");
    append(resultHost, emptyState("Start with a street address", "Include a street number and suburb or postcode for the clearest match."));
    append(view, resultHost);

    let queryGeneration = 0;
    const submission = createSubmissionGuard(async (query) => {
      const generation = ++queryGeneration;
      history.replaceState(null, "", `#properties${queryString({ q: query })}`);
      resultHost.replaceChildren(el("section", "loading-state", "Searching NSW property records…"));
      try {
        const result = await request(`properties/search${queryString({ q: query, state: "NSW", limit: 25 })}`);
        if (generation !== queryGeneration || input.value.trim() !== query) return;
        const items = collection(result.body);
        if (result.body.supported === false) resultHost.replaceChildren(el("div", "notice warning", "This query is outside the supported NSW coverage. Try an NSW street address."));
        else if (!items.length) resultHost.replaceChildren(emptyState("No property found", "Try including a street number, suburb and four-digit postcode. We will not silently broaden your search."));
        else {
          renderPropertyResults(resultHost, items, query);
          announce(`${items.length} property matches found.`);
        }
      } catch (error) {
        if (generation !== queryGeneration || input.value.trim() !== query) return;
        resultHost.replaceChildren(errorState(error, () => form.requestSubmit()));
      }
    }, (pending) => {
      if (pending) {
        search.dataset.label = search.textContent;
        search.style.minWidth = `${Math.ceil(search.offsetWidth)}px`;
        search.textContent = "Searching…";
      } else {
        search.textContent = search.dataset.label || "Search";
        search.style.minWidth = "";
      }
      search.disabled = pending;
      search.setAttribute("aria-busy", String(pending));
    });
    const validateSearchInput = ({ report = false } = {}) => {
      try {
        propertySearchQuery(input.value);
        input.setCustomValidity("");
        input.removeAttribute("aria-invalid");
        searchError.textContent = "";
        return true;
      } catch (error) {
        input.setCustomValidity(error.message);
        input.setAttribute("aria-invalid", "true");
        searchError.textContent = error.message;
        if (report) {
          input.focus();
          input.reportValidity();
        }
        return false;
      }
    };
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (validateSearchInput({ report: true })) submission.submit(propertySearchQuery(input.value));
    });
    form.addEventListener("invalid", (event) => {
      if (event.target !== input) return;
      validateSearchInput();
    }, true);
    input.addEventListener("input", () => {
      queryGeneration += 1;
      validateSearchInput();
      if (submission.pending) resultHost.replaceChildren(emptyState("Search changed", "Press Search when the address is ready. Results from the earlier request will not replace this query."));
    });

    if (input.value) queueMicrotask(() => form.requestSubmit());
  }

  function renderPropertyResults(host, items, query) {
    const layout = el("div", "property-results");
    const listBody = el("div", "result-list");
    listBody.setAttribute("aria-label", "Property matches");
    items.slice(0, 5).forEach((item) => {
      const result = el("button", "result-card");
      result.type = "button";
      result.setAttribute("aria-label", `Open ${item.address_display}`);
      append(result, el("strong", "", item.address_display), el("span", "", `${confidenceLabel(item.score ?? item.match?.score)} · ${item.locality || ""} ${item.state || "NSW"} ${item.postcode || ""}`));
      result.addEventListener("click", () => { location.hash = `#properties/${encodeURIComponent(item.property_ref)}${queryString({ q: query })}`; });
      append(listBody, result);
    });
    const coordinateRows = makeTable(
      [{ label: "Address" }, { label: "Property reference" }, { label: "Latitude" }, { label: "Longitude" }, { label: "Resolution" }], items,
      (item) => { const row = el("tr"); append(row, cell(item.address_display, "primary-cell"), cell(item.property_ref, "mono"), cell(item.latitude ?? "Unknown"), cell(item.longitude ?? "Unknown"), cell(badge(item.resolution_status || "unknown"))); return row; },
    );
    append(layout, panel(`${items.length} ${items.length === 1 ? "match" : "matches"}`, items.length > 5 ? "Showing the five best matches · choose one to continue" : "Choose a property to continue", listBody), disclosurePanel("All match details", "Property references and coordinates", coordinateRows));
    host.replaceChildren(layout);
  }

  async function renderPropertyDetail(propertyRef) {
    view.replaceChildren(el("section", "loading-state", "Loading property details…"));
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
      const identityHero = el("section", "property-identity-hero");
      append(identityHero, pageHeading("Verified NSW property", property.address_display || property.display_address || "Property record", `${property.locality || "NSW"} · ${property.state || "NSW"} ${property.postcode || ""} · Updated ${formatDate(property.updated_at)}`, [link("Back to search", `#properties${queryString({ q: query })}`, "button secondary")]));
      const referenceStrip = el("div", "property-reference-strip");
      append(referenceStrip, el("span", "", humanise(property.resolution_status || "unknown")), el("span", "", `${detailPayload.identifiers?.length || 0} source identifiers checked`), el("span", "", `${coverage.length} research datasets available`));
      append(identityHero, referenceStrip);
      append(view, identityHero);
      const body = el("div", "stack");
      const latitude = map.latitude ?? map.coordinates?.latitude ?? property.latitude ?? property.coordinates?.latitude;
      const longitude = map.longitude ?? map.coordinates?.longitude ?? property.longitude ?? property.coordinates?.longitude;
      append(body, propertyMap({ property, latitude, longitude, announce }));
      append(body, detailList([["Address", property.address_display || property.display_address], ["Locality", property.locality], ["State", property.state], ["Postcode", property.postcode], ["Match status", badge(property.resolution_status || "unknown")], ["Last updated", formatDate(property.updated_at)]]));
      const technicalBody = el("div", "stack");
      append(technicalBody, detailList([["PropertyScope reference", el("code", "mono", property.property_ref)], ["Request ID", el("code", "mono", detailResult.value.requestId)]]));
      append(technicalBody, makeTable([{ label: "Coordinate" }, { label: "Value" }], [{ label: "Latitude", value: latitude ?? "Unknown" }, { label: "Longitude", value: longitude ?? "Unknown" }, { label: "Geometry type", value: map.geometry?.type || property.geometry?.type || "Unknown" }], (item) => { const row = el("tr"); append(row, cell(item.label, "primary-cell"), cell(String(item.value), item.label === "Geometry type" ? "" : "mono")); return row; }));
      append(technicalBody, evidenceTable("Source identifiers", detailPayload.identifiers || [], [
        ["Scheme", (item) => item.scheme], ["Identifier", (item) => item.identifier_value], ["Match method", (item) => humanise(item.match_method)], ["Confidence", (item) => item.match_confidence ?? "Unknown"], ["Current", (item) => item.is_current ? "Yes" : "No"], ["Details", (item) => item.evidence_json ? technicalDetails(item.evidence_json, "Inspect") : "Unknown"],
      ], "No source identifiers are recorded. Identity confidence is therefore unknown."));
      append(technicalBody, evidenceTable("Address aliases", detailPayload.aliases || [], [
        ["Alias", (item) => item.alias_display], ["Kind", (item) => humanise(item.alias_kind)], ["Source identifier", (item) => item.source_identifier || "Unknown"], ["Current", (item) => item.is_current ? "Yes" : "No"],
      ], "No address aliases are recorded for this property."));
      const cards = el("div", "coverage-grid");
      for (const item of coverage) {
        const card = el("div", `coverage-card ${statusTone(item.status || item.coverage_status || item.state)}`);
        append(card, el("strong", "", displayName(item.dataset || item.dataset_id || researchAreaLabel(item.feature || item.target_feature))), el("span", "", `${humanise(item.status || item.coverage_status || item.state)}${item.release_version ? ` · ${item.release_version}` : ""}${item.limitation ? ` · ${item.limitation}` : ""}`));
        append(cards, card);
      }
      if (coverage.length) append(body, el("h2", "", "Available research coverage"), cards);
      else append(body, emptyState("Coverage is unknown", coverageResult.status === "rejected" ? `Coverage details are temporarily unavailable.${problemSuffix(coverageResult.reason)}` : "No published coverage has been recorded for this property."));
      append(technicalBody, renderPropertyReportSection(reportResult.status === "fulfilled" ? reportResult.value : { error: reportResult.reason }));
      append(body, disclosurePanel("Property identifiers and coordinates", "Source identifiers, coordinates and address aliases", technicalBody));
      if (mapResult.status === "rejected") append(body, el("div", "notice warning", `Spatial context is temporarily unavailable; canonical identity remains usable.${problemSuffix(mapResult.reason)}`));
      append(view, panel("Property details", "Address, location and available research data", body));
    } catch (error) {
      view.replaceChildren(errorState(error, () => renderPropertyDetail(propertyRef)));
    }
  }

  function renderPropertyReportSection(result) {
    const section = el("section", "panel report-section");
    const heading = el("div", "panel-heading");
    const copy = el("div");
    append(copy, el("h3", "", "Source summary"), el("p", "", "Property identity and published dataset details that can be reused in reports"));
    append(heading, copy);
    append(section, heading);
    const body = el("div", "panel-body");
    if (result?.error) {
      append(body, el("div", "notice warning", `The source summary is temporarily unavailable. Property search remains usable.${result.error.requestId ? ` Request ID ${result.error.requestId}` : ""}`));
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
      ["Sources recorded", formatNumber(report.evidence_count)],
    ]));
    const releases = reportReleaseRows(report);
    if (!releases.length) append(body, el("p", "", "No published datasets are available for this summary."));
    else append(body, makeTable(
      [{ label: "Dataset" }, { label: "Research area" }, { label: "Version" }, { label: "Status" }, { label: "Published" }, { label: "Coverage" }],
      releases,
      (item) => {
        const row = el("tr");
        append(row, cell(displayName(item.dataset_id || "—"), "primary-cell"), cell(researchAreaLabel(item.target_feature)), cell(item.release_version || item.dataset_release_id || "—"), cell(badge(item.coverage_status)), cell(formatDate(item.accepted_at || item.checked_at)), cell(item.coverage_scope ? technicalDetails(item.coverage_scope, "Inspect") : "—"));
        return row;
      },
    ));
    if (identity.geometry) append(body, technicalDetails(identity.geometry, "Report coordinates"));
    append(section, body);
    return section;
  }

  return { renderProperties };
}

function propertyMap({ property, latitude, longitude, announce }) {
  const host = el("div", "map-context ps-map");
  const canvas = el("div", "ps-map__canvas");
  const status = el("div", "ps-map__status", "Loading interactive map…");
  status.setAttribute("role", "status");
  status.dataset.state = "loading";
  const caption = el(
    "div",
    "ps-map__caption",
    `${latitude ?? "Unknown latitude"}, ${longitude ?? "unknown longitude"} · Drag to pan, scroll or use the controls to zoom.`,
  );
  append(host, canvas, status, caption);
  const numericLatitude = Number(latitude);
  const numericLongitude = Number(longitude);
  if (!Number.isFinite(numericLatitude) || !Number.isFinite(numericLongitude)) {
    status.dataset.state = "error";
    status.textContent = "No valid map coordinate is available for this property.";
    return host;
  }
  queueMicrotask(async () => {
    if (!host.isConnected) return;
    try {
      await createMap({
        container: canvas,
        provider: createOpenFreeMapProvider(),
        layers: [{
          id: "selected-property",
          label: "Selected property",
          kind: "point",
          data: featureCollection([pointFeature(
            numericLongitude,
            numericLatitude,
            {
              address: property.address_display || property.display_address || "Selected property",
              locality: property.locality || "NSW",
            },
            property.property_ref,
          )]),
          popup: {
            title: "address",
            fields: [{ label: "Locality", property: "locality" }],
          },
        }],
        view: { center: [numericLongitude, numericLatitude], zoom: 16 },
        onStatus(event) {
          status.dataset.state = event.state;
          status.textContent = event.message;
          if (event.state === "fallback") announce("The basemap is unavailable; the verified property point remains visible.");
        },
      });
    } catch (error) {
      if (error?.name === "AbortError") return;
      status.dataset.state = "error";
      status.textContent = "The interactive map could not start; coordinates remain available below.";
      console.error("property map failed", error);
    }
  });
  return host;
}

function evidenceTable(title, items, columns, emptyCopy) {
  const body = el("div", "stack"); append(body, el("h2", "", title));
  if (!items.length) { append(body, el("p", "", emptyCopy)); return body; }
  append(body, makeTable(columns.map(([label]) => ({ label })), items, (item) => { const row = el("tr"); columns.forEach(([, value], index) => append(row, cell(value(item), index === 0 ? "primary-cell" : ""))); return row; }));
  return body;
}

function problemSuffix(error) { return error?.requestId ? ` Request ID ${error.requestId}.` : ""; }
