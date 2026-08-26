import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { confidenceLabel, coverageRows, displayName, formatDate, formatNumber, humanise, reportReleaseRows, researchAreaLabel, statusTone } from "../core/formats.js?v=18";
import { createSubmissionGuard, propertySearchQuery } from "../core/forms.js?v=18";
import { parseRoute, routeQuery } from "../core/router.js";
import { badge, detailList, disclosurePanel, pageHeading, panel, technicalDetails } from "../components/layout.js?v=17";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable } from "../components/tables.js";
import { createMap, createOpenFreeMapProvider, featureCollection, pointFeature } from "../mapping/index.js";

const PROPERTY_SEARCH_PAGE_SIZE = 25;

export function createPropertyRoutes({ view, request, announce, rerender }) {
  let routeGeneration = 0;
  let pendingSearchOrigin = null;

  async function renderProperties(propertyRef = "") {
    const generation = ++routeGeneration;
    if (propertyRef) return renderPropertyDetail(propertyRef, generation);
    view.replaceChildren();
    const hero = el("section", "discovery-hero");
    append(hero, el("p", "eyebrow", "Property search"), el("h1", "", "Find a NSW property"), el("p", "", "Search the current published address register by street, suburb, postcode or any combination you know."));
    const form = el("form", "search-box");
    form.setAttribute("role", "search");
    const searchField = el("label", "search-field");
    searchField.htmlFor = "property-search-query";
    append(searchField, el("span", "", "Address, suburb or postcode"));
    const input = el("input");
    input.id = "property-search-query";
    input.type = "search";
    input.name = "q";
    input.placeholder = 'Try "Sydney", "2000" or "11 Example Street"';
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
    const searchHelp = el("p", "search-help", "Type at least 2 characters. Punctuation and word order are optional; close spelling matches are included."); searchHelp.id = "property-search-help";
    append(hero, form, searchError, searchHelp);
    append(view, hero);
    const resultHost = el("div");
    append(resultHost, emptyState("Search current property records", "Use as much or as little of the address as you know. Add more detail only when you need to narrow the matches."));
    append(view, resultHost);

    let queryGeneration = 0;
    const submission = createSubmissionGuard(async (query, { preserveReturn = false } = {}) => {
      const searchGeneration = ++queryGeneration;
      updateSearchHistory(query, { preserveReturn });
      resultHost.replaceChildren(el("section", "loading-state", "Searching NSW property records…"));
      try {
        const result = await request(`properties/search${queryString({ q: query, state: "NSW", limit: PROPERTY_SEARCH_PAGE_SIZE, offset: 0 })}`);
        if (searchGeneration !== queryGeneration || !canHydrate(generation, routeGeneration, resultHost, "") || input.value.trim() !== query) return;
        let items = collection(result.body);
        let total = Number(result.body.total ?? items.length);
        let totalIsLowerBound = Boolean(result.body.total_is_lower_bound);
        if (result.body.supported === false) resultHost.replaceChildren(el("div", "notice warning", "This query is outside the supported NSW coverage. Try an NSW street address."));
        else if (!items.length) resultHost.replaceChildren(emptyState("No property found", "Check the spelling or try a broader part of the address, such as the suburb or postcode. Only current published NSW address records are searched."));
        else {
          const renderResults = () => renderPropertyResults(resultHost, items, query, {
            total,
            totalIsLowerBound,
            onLoadMore: async (control, errorHost) => {
              control.disabled = true;
              control.textContent = "Loading…";
              errorHost.textContent = "";
              try {
                const page = await request(`properties/search${queryString({ q: query, state: "NSW", limit: PROPERTY_SEARCH_PAGE_SIZE, offset: items.length })}`);
                if (searchGeneration !== queryGeneration || !canHydrate(generation, routeGeneration, resultHost, "") || input.value.trim() !== query) return;
                const known = new Set(items.map((item) => item.property_ref));
                items = [...items, ...collection(page.body).filter((item) => !known.has(item.property_ref))];
                total = Number(page.body.total ?? total);
                totalIsLowerBound = Boolean(page.body.total_is_lower_bound);
                renderResults();
                announce(`${items.length} of ${totalIsLowerBound ? "at least " : ""}${total} property matches shown.`);
              } catch (error) {
                control.disabled = false;
                control.textContent = "Show more matches";
                errorHost.textContent = `More matches could not be loaded.${problemSuffix(error)}`;
              }
            },
          });
          renderResults();
          announce(`${totalIsLowerBound ? "At least " : ""}${total} property ${total === 1 ? "match" : "matches"} found.`);
        }
      } catch (error) {
        if (searchGeneration !== queryGeneration || !canHydrate(generation, routeGeneration, resultHost, "") || input.value.trim() !== query) return;
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
      search.setAttribute("aria-disabled", String(pending));
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

    if (input.value) queueMicrotask(() => {
      if (validateSearchInput({ report: true })) {
        submission.submit(propertySearchQuery(input.value), { preserveReturn: true });
      }
    });
  }

  function renderPropertyResults(host, items, query, { total, totalIsLowerBound, onLoadMore }) {
    const layout = el("section", "property-results");
    const summary = el("header", "property-results-heading");
    append(summary, el("p", "eyebrow", "Search results"), el("h2", "", `${totalIsLowerBound ? "At least " : ""}${formatNumber(total)} ${total === 1 ? "property" : "properties"} found`), el("p", "", `Best matches for \u201c${query}\u201d. Search covers the current published NSW address records.`));
    const listBody = el("div", "result-list");
    listBody.setAttribute("aria-label", "Property matches");
    items.forEach((item) => {
      const target = `#properties/${encodeURIComponent(item.property_ref)}${queryString({ q: query })}`;
      const result = link("", target, "result-card");
      result.dataset.propertyRef = item.property_ref;
      result.setAttribute("aria-label", `Open ${item.address_display}`);
      const copy = el("span", "result-card-copy");
      append(copy, el("strong", "", item.address_display));
      const meta = el("span", "result-card-meta");
      append(meta, el("span", "", `${humanise(item.locality)} NSW ${item.postcode}`), el("span", "", propertyMatchLabel(item)), badge(item.resolution_status || "unknown"));
      append(copy, meta);
      if (item.match_kind === "alias" && item.matched_address && item.matched_address !== item.address_display) append(copy, el("span", "result-card-alias", `Matched address alias: ${item.matched_address}`));
      append(result, copy, el("span", "result-card-arrow", "\u2192"));
      result.addEventListener("click", (event) => {
        pendingSearchOrigin = rememberSearchReturn(event, { query, propertyRef: item.property_ref });
      });
      append(listBody, result);
    });
    const coordinateRows = makeTable(
      [{ label: "Address" }, { label: "Property reference" }, { label: "Latitude" }, { label: "Longitude" }, { label: "Resolution" }], items,
      (item) => { const row = el("tr"); append(row, cell(item.address_display, "primary-cell"), cell(item.property_ref, "mono"), cell(item.latitude ?? "Unknown"), cell(item.longitude ?? "Unknown"), cell(badge(item.resolution_status || "unknown"))); return row; },
    );
    append(layout, summary, listBody);
    if (totalIsLowerBound || items.length < total) {
      const pagination = el("div", "property-results-pagination");
      const more = button("Show more matches", "button secondary");
      const moreError = el("p", "form-error");
      moreError.setAttribute("role", "alert");
      more.addEventListener("click", () => onLoadMore(more, moreError));
      append(pagination, el("p", "", `Showing ${formatNumber(items.length)} of ${totalIsLowerBound ? "at least " : ""}${formatNumber(total)} matches`), more, moreError);
      append(layout, pagination);
    }
    append(layout, disclosurePanel("Match details", "Property references and recorded coordinates", coordinateRows));
    host.replaceChildren(layout);
    restoreSearchReturn(listBody, query, routeGeneration);
  }

  async function renderPropertyDetail(propertyRef, generation) {
    const query = routeQuery(location.hash).get("q") || "";
    const searchOrigin = matchingSearchOrigin(historyState().propertyDiscoveryOrigin || pendingSearchOrigin, { query, propertyRef });
    pendingSearchOrigin = null;
    if (searchOrigin) {
      history.replaceState({ ...historyState(), propertyDiscoveryOrigin: searchOrigin }, "", location.href);
    }
    view.replaceChildren(el("section", "loading-state", "Loading property details…"));
    const encodedRef = encodeURIComponent(propertyRef);
    const mapResult = settled(request(`properties/${encodedRef}/map-context`));
    const coverageResult = settled(request(`properties/${encodedRef}/coverage`));
    const reportResult = settled(request(`properties/${encodedRef}/report-section`));
    try {
      const detailResult = await request(`properties/${encodedRef}`);
      if (!isCurrentRoute(generation, routeGeneration, propertyRef)) return;
      const detailPayload = detailResult.body;
      const property = entity(detailPayload, "property");
      const initialCoverage = detailPayload.coverage || [];
      view.replaceChildren();
      const identityHero = el("section", "property-identity-hero");
      append(identityHero, pageHeading("Verified NSW property", property.address_display || property.display_address || "Property record", `${property.locality || "NSW"} · ${property.state || "NSW"} ${property.postcode || ""} · Updated ${formatDate(property.updated_at)}`, [propertyBackLink(query, propertyRef)]));
      const referenceStrip = el("div", "property-reference-strip");
      const coverageCount = el("span", "", `${initialCoverage.length} research datasets available`);
      append(referenceStrip, el("span", "", humanise(property.resolution_status || "unknown")), el("span", "", `${detailPayload.identifiers?.length || 0} source identifiers checked`), coverageCount);
      append(identityHero, referenceStrip);
      append(view, identityHero);
      const detailGrid = el("div", "property-detail-grid");
      const summaryColumn = el("aside", "property-summary-column");
      const summaryBody = detailList([["Canonical address", property.address_display || property.display_address], ["Locality", humanise(property.locality)], ["Postcode", property.postcode], ["Identity status", badge(property.resolution_status || "unknown")], ["Last updated", formatDate(property.updated_at)]]);
      append(summaryColumn, panel("Property at a glance", "Canonical identity from current published records", summaryBody));
      const contentColumn = el("div", "property-content-column");
      const mapHost = pendingSection("Loading spatial context…");
      append(contentColumn, panel("Location", "Verified property point and surrounding street context", mapHost));
      const coverageHost = pendingSection("Loading available research coverage…");
      append(contentColumn, panel("Research available", "Published datasets currently linked to this property", coverageHost));
      const technicalBody = el("div", "stack");
      append(technicalBody, detailList([["PropertyScope reference", el("code", "mono", property.property_ref)], ["Request ID", el("code", "mono", detailResult.requestId)]]));
      const coordinateHost = pendingSection("Loading recorded coordinates…");
      append(technicalBody, coordinateHost);
      append(technicalBody, evidenceTable("Source identifiers", detailPayload.identifiers || [], [
        ["Scheme", (item) => item.scheme], ["Identifier", (item) => item.identifier_value], ["Match method", (item) => humanise(item.match_method)], ["Confidence", (item) => item.match_confidence ?? "Unknown"], ["Current", (item) => item.is_current ? "Yes" : "No"], ["Details", (item) => item.evidence_json ? technicalDetails(item.evidence_json, "Inspect") : "Unknown"],
      ], "No source identifiers are recorded. Identity confidence is therefore unknown."));
      append(technicalBody, evidenceTable("Address aliases", detailPayload.aliases || [], [
        ["Alias", (item) => item.alias_display], ["Kind", (item) => humanise(item.alias_kind)], ["Source identifier", (item) => item.source_identifier || "Unknown"], ["Current", (item) => item.is_current ? "Yes" : "No"],
      ], "No address aliases are recorded for this property."));
      const reportHost = pendingSection("Loading source summary…");
      append(technicalBody, reportHost);
      append(summaryColumn, disclosurePanel("Sources and identifiers", "References, coordinates, aliases and report evidence", technicalBody));
      append(detailGrid, summaryColumn, contentColumn);
      append(view, detailGrid);

      void mapResult.then((result) => {
        if (!canHydrate(generation, routeGeneration, mapHost, propertyRef)) return;
        const map = result.status === "fulfilled" ? entity(result.value.body) : {};
        const latitude = map.latitude ?? map.coordinates?.latitude ?? property.latitude ?? property.coordinates?.latitude;
        const longitude = map.longitude ?? map.coordinates?.longitude ?? property.longitude ?? property.coordinates?.longitude;
        resolvePendingSection(mapHost);
        resolvePendingSection(coordinateHost);
        mapHost.replaceChildren(propertyMap({ property, latitude, longitude, announce }));
        coordinateHost.replaceChildren(coordinateTable({ map, property, latitude, longitude }));
        if (result.status === "rejected") {
          append(mapHost, el("div", "notice warning", `Spatial context is temporarily unavailable; canonical identity remains usable.${problemSuffix(result.reason)}`));
        }
      });
      void coverageResult.then((result) => {
        if (!canHydrate(generation, routeGeneration, coverageHost, propertyRef)) return;
        const responseCoverage = result.status === "fulfilled" ? coverageRows(result.value.body) : [];
        const coverage = responseCoverage.length ? responseCoverage : initialCoverage;
        coverageCount.textContent = `${coverage.length} research datasets available`;
        resolvePendingSection(coverageHost);
        coverageHost.replaceChildren(coverageSection(coverage, result));
      });
      void reportResult.then((result) => {
        if (!canHydrate(generation, routeGeneration, reportHost, propertyRef)) return;
        resolvePendingSection(reportHost);
        reportHost.replaceChildren(renderPropertyReportSection(result.status === "fulfilled" ? result.value : { error: result.reason }));
      });
    } catch (error) {
      if (!isCurrentRoute(generation, routeGeneration, propertyRef)) return;
      const failure = errorState(error, () => rerender({ focus: true }));
      const actions = el("div", "property-error-actions");
      const retry = failure.querySelector(".button");
      if (retry) { retry.style.marginTop = ""; append(actions, retry); }
      append(actions, propertyBackLink(query, propertyRef));
      append(failure.firstElementChild, actions);
      view.replaceChildren(failure);
    }
  }

  function restoreSearchReturn(listBody, query, generation) {
    const context = historyState().propertyDiscoveryReturn;
    if (!context || context.query !== query || typeof context.propertyRef !== "string") return;
    const target = [...listBody.querySelectorAll("[data-property-ref]")]
      .find((item) => item.dataset.propertyRef === context.propertyRef);
    if (!target) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!canHydrate(generation, routeGeneration, listBody, "") || routeQuery(location.hash).get("q") !== query) return;
      target.focus({ preventScroll: true });
      const maximum = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      const top = Math.min(maximum, Math.max(0, Number(context.scrollY) || 0));
      const priorScrollBehavior = document.documentElement.style.scrollBehavior;
      document.documentElement.style.scrollBehavior = "auto";
      window.scrollTo(0, top);
      document.documentElement.style.scrollBehavior = priorScrollBehavior;
    }));
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

function updateSearchHistory(query, { preserveReturn }) {
  const next = { ...historyState() };
  if (!preserveReturn || next.propertyDiscoveryReturn?.query !== query) {
    delete next.propertyDiscoveryReturn;
  }
  history.replaceState(next, "", `#properties${queryString({ q: query })}`);
}

function rememberSearchReturn(event, { query, propertyRef }) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  if (routeQuery(location.hash).get("q") !== query) return null;
  const context = { query, propertyRef, scrollY: window.scrollY };
  history.replaceState({
    ...historyState(),
    propertyDiscoveryReturn: context,
  }, "", location.href);
  return context;
}

function matchingSearchOrigin(context, { query, propertyRef }) {
  return context?.query === query && context?.propertyRef === propertyRef ? context : null;
}

function propertyBackLink(query, propertyRef) {
  const back = link("Back to search", `#properties${queryString({ q: query })}`, "button secondary");
  back.addEventListener("click", (event) => {
    const origin = matchingSearchOrigin(historyState().propertyDiscoveryOrigin, { query, propertyRef });
    if (!origin || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    history.back();
  });
  return back;
}

function historyState() {
  return history.state && typeof history.state === "object" ? history.state : {};
}

function isCurrentRoute(generation, currentGeneration, propertyRef) {
  const route = parseRoute(location.hash);
  return generation === currentGeneration && route.route === "properties" && route.id === propertyRef;
}

function canHydrate(generation, currentGeneration, host, propertyRef) {
  return host.isConnected && isCurrentRoute(generation, currentGeneration, propertyRef);
}

function settled(promise) {
  return promise.then(
    (value) => ({ status: "fulfilled", value }),
    (reason) => ({ status: "rejected", reason }),
  );
}

function pendingSection(message) {
  const status = el("div", "notice property-section-loading", message);
  status.setAttribute("role", "status");
  return status;
}

function resolvePendingSection(section) {
  section.classList.remove("notice", "property-section-loading");
  section.removeAttribute("role");
}

function coordinateTable({ map, property, latitude, longitude }) {
  return makeTable(
    [{ label: "Coordinate" }, { label: "Value" }],
    [
      { label: "Latitude", value: latitude ?? "Unknown" },
      { label: "Longitude", value: longitude ?? "Unknown" },
      { label: "Geometry type", value: map.geometry?.type || property.geometry?.type || "Unknown" },
    ],
    (item) => {
      const row = el("tr");
      append(row, cell(item.label, "primary-cell"), cell(String(item.value), item.label === "Geometry type" ? "" : "mono"));
      return row;
    },
    "Property coordinates",
  );
}

function coverageSection(coverage, result) {
  const section = el("section", "stack property-coverage");
  if (result.status === "rejected" && coverage.length) {
    append(section, el("div", "notice warning", `Coverage details are temporarily unavailable; recorded property coverage remains below.${problemSuffix(result.reason)}`));
  }
  if (!coverage.length) {
    append(section, emptyState("Coverage is unknown", result.status === "rejected" ? `Coverage details are temporarily unavailable.${problemSuffix(result.reason)}` : "No published coverage has been recorded for this property."));
    return section;
  }
  const cards = el("div", "coverage-grid");
  for (const item of coverage) {
    const card = el("div", `coverage-card ${statusTone(item.status || item.coverage_status || item.state)}`);
    append(card, el("strong", "", displayName(item.dataset || item.dataset_id || researchAreaLabel(item.feature || item.target_feature))), el("span", "", `${humanise(item.status || item.coverage_status || item.state)}${item.release_version ? ` · ${item.release_version}` : ""}${item.limitation ? ` · ${item.limitation}` : ""}`));
    append(cards, card);
  }
  append(section, cards);
  return section;
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

function propertyMatchLabel(item) {
  const labels = {
    exact: "Exact address match",
    prefix: "Address starts with search",
    contains: "Address contains search",
    all_terms: "All search terms matched",
    fuzzy: "Close spelling match",
  };
  return labels[item.match_method] || confidenceLabel(item.score ?? item.match?.score);
}

function problemSuffix(error) { return error?.requestId ? ` Request ID ${error.requestId}.` : ""; }
