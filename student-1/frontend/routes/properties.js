import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { confidenceLabel, coverageRows, displayName, formatDate, formatNumber, humanise, reportReleaseRows, researchAreaLabel, statusTone } from "../core/formats.js";
import { propertySearchQuery } from "../core/forms.js";
import { createLatestRequestGuard } from "../core/polling.js";
import { disposeTableRegions } from "../browser/index.js";
import { parseRoute, routeQuery, readHistoryState as historyState, replaceHistoryState } from "../core/router.js";
import { badge, detailList, disclosurePanel, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable } from "../components/tables.js";
import { propertySections } from "../components/property-sections.js";
import { createMap, createOpenFreeMapProvider, featureCollection, mountMapHelp, pointFeature } from "../mapping/index.js";

const PROPERTY_SEARCH_PAGE_SIZE = 25;

export function createPropertyRoutes({ view, request, announce, generationGuard, rerender }) {
  let pendingSearchOrigin = null;

  async function renderProperties(propertyRef = "") {
    const routeEpoch = generationGuard.capture();
    if (propertyRef) return renderPropertyDetail(propertyRef, routeEpoch);
    view.replaceChildren();
    const hero = el("section", "discovery-hero");
    const searchCopy = el("div", "discovery-copy");
    append(searchCopy, el("p", "eyebrow", "Property data / Start with a place"), el("h1", "", "Find a NSW property"), el("p", "", "Search the current published address register by street, suburb, postcode or any combination you know."));
    const form = el("form", "search-box");
    form.setAttribute("role", "search");
    const searchField = el("label", "search-field");
    searchField.htmlFor = "property-search-query";
    append(searchField, el("span", "", "Address, suburb or postcode"));
    const input = el("input");
    input.id = "property-search-query";
    input.type = "search";
    input.name = "q";
    input.placeholder = 'Try "Parramatta", "2000" or "11 Example Street"';
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
    const searchHelp = el("p", "search-help", "Use a postcode, a distinctive locality, or a fuller street address. Punctuation is optional."); searchHelp.id = "property-search-help";
    append(searchCopy, form, searchError, searchHelp);
    const illustration = el("aside", "discovery-illustration");
    illustration.setAttribute("aria-hidden", "true");
    const parcels = el("div", "discovery-parcels");
    for (let index = 0; index < 12; index += 1) append(parcels, el("i"));
    append(illustration, el("span", "eyebrow", "Illustrative parcel view / NSW"), parcels, el("p", "", "A place. A record. A source."));
    append(hero, searchCopy, illustration);
    hero.classList.toggle("discovery-hero--results", Boolean(input.value));
    append(view, hero);
    const resultHost = el("div");
    append(resultHost, emptyState("Search current property records", "Use as much or as little of the address as you know. Add more detail only when you need to narrow the matches."));
    append(view, resultHost);

    const searches = createLatestRequestGuard();
    let pendingQuery = null;
    const submitSearch = async (query, { preserveReturn = false } = {}) => {
      if (pendingQuery === query) return;
      const task = searches.begin();
      const isCurrent = () => task.isCurrent() && canHydrate(routeEpoch, resultHost, "") && input.value.trim() === query;
      pendingQuery = query;
      hero.classList.add("discovery-hero--results");
      setSearchPending(true);
      updateSearchHistory(query, { preserveReturn });
      disposeTableRegions(resultHost);
      resultHost.replaceChildren(el("section", "loading-state", "Searching NSW property records…"));
      try {
        const result = await request(`properties/search${queryString({ q: query, state: "NSW", limit: PROPERTY_SEARCH_PAGE_SIZE, offset: 0 })}`, { signal: task.signal });
        if (!isCurrent()) return;
        let items = collection(result.body);
        let total = Number(result.body.total ?? items.length);
        let totalIsLowerBound = Boolean(result.body.total_is_lower_bound);
        let nextOffset = result.body.next_offset ?? null;
        if (result.body.supported === false) resultHost.replaceChildren(el("div", "notice warning", "This query is outside the supported NSW coverage. Try an NSW street address."));
        else if (!items.length) resultHost.replaceChildren(emptyState("No property found", "Check the spelling or try a broader part of the address, such as the suburb or postcode. Only current published NSW address records are searched."));
        else {
          const renderResults = () => renderPropertyResults(resultHost, items, query, {
            total,
            totalIsLowerBound,
            hasMore: nextOffset !== null,
            routeEpoch,
            onLoadMore: async (control, errorHost) => {
              if (!isCurrent() || control.disabled) return;
              control.disabled = true;
              control.textContent = "Loading…";
              errorHost.textContent = "";
              try {
                const page = await request(`properties/search${queryString({ q: query, state: "NSW", limit: PROPERTY_SEARCH_PAGE_SIZE, offset: nextOffset })}`, { signal: task.signal });
                if (!isCurrent()) return;
                const known = new Set(items.map((item) => item.property_ref));
                items = [...items, ...collection(page.body).filter((item) => !known.has(item.property_ref))];
                total = Number(page.body.total ?? total);
                totalIsLowerBound = Boolean(page.body.total_is_lower_bound);
                nextOffset = page.body.next_offset ?? null;
                renderResults();
                announce(`${items.length} of ${totalIsLowerBound ? "at least " : ""}${total} property matches shown.`);
              } catch (error) {
                if (!isCurrent()) return;
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
        if (!isCurrent()) return;
        resultHost.replaceChildren(errorState(error, () => form.requestSubmit()));
      } finally {
        if (task.isCurrent()) {
          pendingQuery = null;
          setSearchPending(false);
        }
      }
    };
    function setSearchPending(pending) {
      if (pending) {
        search.style.minWidth = `${Math.ceil(search.offsetWidth)}px`;
        search.textContent = "Searching…";
      } else {
        search.textContent = "Search";
        search.style.minWidth = "";
      }
      search.setAttribute("aria-disabled", String(pending));
      search.setAttribute("aria-busy", String(pending));
    }
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
      if (validateSearchInput({ report: true })) submitSearch(propertySearchQuery(input.value));
    });
    form.addEventListener("invalid", (event) => {
      if (event.target !== input) return;
      validateSearchInput();
    }, true);
    input.addEventListener("input", () => {
      const wasPending = pendingQuery !== null;
      searches.cancel();
      pendingQuery = null;
      setSearchPending(false);
      validateSearchInput();
      if (wasPending || resultHost.querySelector(".property-results")) {
        disposeTableRegions(resultHost);
        resultHost.replaceChildren(emptyState("Search changed", "Press Search when the address is ready. Results from the earlier request will not replace this query."));
      }
    });

    if (input.value) queueMicrotask(() => {
      if (routeEpoch.isCurrent() && validateSearchInput({ report: true })) {
        submitSearch(propertySearchQuery(input.value), { preserveReturn: true });
      }
    });
  }

  function renderPropertyResults(host, items, query, {
    total, totalIsLowerBound, hasMore, routeEpoch, onLoadMore,
  }) {
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
    if (hasMore) {
      const pagination = el("div", "property-results-pagination");
      const more = button("Show more matches", "button secondary");
      const moreError = el("p", "form-error");
      moreError.setAttribute("role", "alert");
      more.addEventListener("click", () => onLoadMore(more, moreError));
      append(pagination, el("p", "", `Showing ${formatNumber(items.length)} of ${totalIsLowerBound ? "at least " : ""}${formatNumber(total)} matches`), more, moreError);
      append(layout, pagination);
    }
    append(layout, disclosurePanel("Match details", "Property references and recorded coordinates", coordinateRows));
    disposeTableRegions(host);
    host.replaceChildren(layout);
    restoreSearchReturn(listBody, query, routeEpoch);
  }

  async function renderPropertyDetail(propertyRef, routeEpoch) {
    const query = routeQuery(location.hash).get("q") || "";
    const searchOrigin = matchingSearchOrigin(historyState().propertyDiscoveryOrigin || pendingSearchOrigin, { query, propertyRef });
    pendingSearchOrigin = null;
    if (searchOrigin) {
      replaceHistoryState({ ...historyState(), propertyDiscoveryOrigin: searchOrigin }, location.href);
    }
    view.replaceChildren(el("section", "loading-state", "Loading property details…"));
    const encodedRef = encodeURIComponent(propertyRef);
    const mapResult = settled(request(`properties/${encodedRef}/map-context`));
    const coverageResult = settled(request(`properties/${encodedRef}/coverage`));
    const saleHistoryResult = settled(request(`properties/${encodedRef}/sale-history?limit=50`));
    const seifaResult = settled(request(`properties/${encodedRef}/seifa`));
    const reportResult = settled(request(`properties/${encodedRef}/report-section`));
    try {
      const detailResult = await request(`properties/${encodedRef}`);
      if (!isCurrentRoute(routeEpoch, propertyRef)) return;
      const detailPayload = detailResult.body;
      const property = entity(detailPayload, "property");
      const initialCoverage = detailPayload.coverage || [];
      view.replaceChildren();
      const identityHero = el("section", "property-identity-hero");
      append(identityHero, pageHeading("Published property record", property.address_display || property.display_address || "Property record", `${property.locality || "NSW"} · ${property.state || "NSW"} ${property.postcode || ""} · Updated ${formatDate(property.updated_at)}`, [propertyBackLink(query, propertyRef)]));
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
      append(summaryColumn, panel("Location", "Recorded property point and surrounding street context", mapHost));
      const coverageHost = pendingSection("Loading available research coverage…");
      const coveragePanel = panel("Research available", "Published datasets currently linked to this property", coverageHost);
      const seifaHost = pendingSection("Loading accepted ABS SEIFA area evidence…");
      const seifaPanel = panel("Socio-economic area context", "ABS SEIFA 2021 evidence for the matched Suburb and Locality area", seifaHost);
      const saleHistoryHost = pendingSection("Loading accepted sale history…");
      const saleHistoryPanel = panel("Sale history", "Recorded transactions from the current published NSW sales release", saleHistoryHost);
      const technicalBody = el("div", "stack property-sources");
      append(technicalBody, detailList([["PropertyScope reference", el("code", "mono", property.property_ref)], ["Request ID", el("code", "mono", detailResult.requestId)]]));
      const coordinateHost = pendingSection("Loading recorded coordinates…");
      append(technicalBody, coordinateHost);
      append(technicalBody, evidenceRecords("Source identifiers", detailPayload.identifiers || [], [
        ["Scheme", (item) => item.scheme], ["Identifier", (item) => el("code", "mono", item.identifier_value)], ["Match method", (item) => humanise(item.match_method)], ["Confidence", (item) => item.match_confidence ?? "Unknown"], ["Current", (item) => item.is_current ? "Yes" : "No"], ["Details", (item) => item.evidence_json ? technicalDetails(item.evidence_json, "Inspect source evidence") : "Unknown"],
      ], "No source identifiers are recorded. Identity confidence is therefore unknown."));
      append(technicalBody, evidenceRecords("Address aliases", detailPayload.aliases || [], [
        ["Alias", (item) => item.alias_display], ["Kind", (item) => humanise(item.alias_kind)], ["Source identifier", (item) => item.source_identifier || "Unknown"], ["Current", (item) => item.is_current ? "Yes" : "No"],
      ], "No address aliases are recorded for this property."));
      const reportHost = pendingSection("Loading source summary…");
      append(technicalBody, reportHost);
      const sourcesPanel = panel("Sources and identifiers", "References, coordinates, aliases and report evidence", technicalBody);
      append(contentColumn, propertySections([
        { key: "research", label: "Research available", content: coveragePanel },
        { key: "sales", label: "Sale history", content: saleHistoryPanel },
        { key: "area", label: "Area context", content: seifaPanel },
        { key: "sources", label: "Sources and identifiers", content: sourcesPanel },
      ]));
      append(detailGrid, summaryColumn, contentColumn);
      append(view, detailGrid);

      void mapResult.then((result) => {
        if (!canHydrate(routeEpoch, mapHost, propertyRef)) return;
        const map = result.status === "fulfilled" ? entity(result.value.body) : {};
        const latitude = map.latitude ?? map.coordinates?.latitude ?? property.latitude ?? property.coordinates?.latitude;
        const longitude = map.longitude ?? map.coordinates?.longitude ?? property.longitude ?? property.coordinates?.longitude;
        resolvePendingSection(mapHost);
        resolvePendingSection(coordinateHost);
        mapHost.replaceChildren(propertyMap({ property, latitude, longitude, announce, routeEpoch }));
        coordinateHost.replaceChildren(coordinateDetails({ map, property, latitude, longitude }));
        if (result.status === "rejected") {
          append(mapHost, el("div", "notice warning", `Spatial context is temporarily unavailable; canonical identity remains usable.${problemSuffix(result.reason)}`));
        }
      });
      void coverageResult.then((result) => {
        if (!canHydrate(routeEpoch, coverageHost, propertyRef)) return;
        const responseCoverage = result.status === "fulfilled" ? coverageRows(result.value.body) : [];
        const coverage = responseCoverage.length ? responseCoverage : initialCoverage;
        coverageCount.textContent = `${coverage.length} research datasets available`;
        resolvePendingSection(coverageHost);
        coverageHost.replaceChildren(coverageSection(coverage, result));
      });
      void saleHistoryResult.then((result) => {
        if (!canHydrate(routeEpoch, saleHistoryHost, propertyRef)) return;
        if (result.status === "rejected") {
          resolvePendingSection(saleHistoryHost);
          saleHistoryHost.replaceChildren(el("div", "notice warning", `Sale history is temporarily unavailable; verified property identity remains usable.${problemSuffix(result.reason)}`));
          return;
        }
        const items = collection(result.value.body);
        if (!result.value.body.supported || !items.length) {
          resolvePendingSection(saleHistoryHost);
          saleHistoryHost.replaceChildren(emptyState("No published sale history", "No supported sale records were returned for this property. This does not establish that the property has never sold."));
          return;
        }
        resolvePendingSection(saleHistoryHost);
        saleHistoryHost.replaceChildren(saleHistorySection(result.value.body, items));
      });
      void seifaResult.then((result) => {
        if (!canHydrate(routeEpoch, seifaHost, propertyRef)) return;
        resolvePendingSection(seifaHost);
        if (result.status === "rejected") {
          seifaHost.replaceChildren(el("div", "notice warning", `SEIFA area evidence is temporarily unavailable.${problemSuffix(result.reason)}`));
          return;
        }
        seifaHost.replaceChildren(seifaSection(result.value.body));
      });
      void reportResult.then((result) => {
        if (!canHydrate(routeEpoch, reportHost, propertyRef)) return;
        resolvePendingSection(reportHost);
        reportHost.replaceChildren(renderPropertyReportSection(result.status === "fulfilled" ? result.value : { error: result.reason }));
      });
    } catch (error) {
      if (!isCurrentRoute(routeEpoch, propertyRef)) return;
      const failure = errorState(error, () => rerender({ focus: true }));
      const actions = el("div", "property-error-actions");
      const retry = failure.querySelector(".button");
      if (retry) { retry.style.marginTop = ""; append(actions, retry); }
      append(actions, propertyBackLink(query, propertyRef));
      append(failure.firstElementChild, actions);
      view.replaceChildren(failure);
    }
  }

  function restoreSearchReturn(listBody, query, routeEpoch) {
    const context = historyState().propertyDiscoveryReturn;
    if (!context || context.query !== query || typeof context.propertyRef !== "string") return;
    const target = [...listBody.querySelectorAll("[data-property-ref]")]
      .find((item) => item.dataset.propertyRef === context.propertyRef);
    if (!target) return;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!canHydrate(routeEpoch, listBody, "") || routeQuery(location.hash).get("q") !== query) return;
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
    const section = el("section", "property-source-section report-section");
    const heading = el("div");
    const copy = el("div");
    append(copy, el("h3", "", "Source summary"), el("p", "", "Property identity and published dataset details that can be reused in reports"));
    append(heading, copy);
    append(section, heading);
    const body = el("div", "stack");
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
    else append(body, sourceRecordList(
      releases,
      [
        ["Dataset", (item) => displayName(item.dataset_id || "—")],
        ["Research area", (item) => researchAreaLabel(item.target_feature)],
        ["Version", (item) => el("code", "mono", item.release_version || item.dataset_release_id || "—")],
        ["Status", (item) => badge(item.coverage_status)],
        ["Published", (item) => formatDate(item.accepted_at || item.checked_at)],
        ["Coverage", (item) => item.coverage_scope ? technicalDetails(item.coverage_scope, "Inspect coverage") : "—"],
      ],
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
  replaceHistoryState(next, `#properties${queryString({ q: query })}`);
}

function rememberSearchReturn(event, { query, propertyRef }) {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  if (routeQuery(location.hash).get("q") !== query) return null;
  const context = { query, propertyRef, scrollY: window.scrollY };
  replaceHistoryState({
    ...historyState(),
    propertyDiscoveryReturn: context,
  }, location.href);
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

function isCurrentRoute(routeEpoch, propertyRef) {
  const route = parseRoute(location.hash);
  return routeEpoch.isCurrent() && route.route === "properties" && route.id === propertyRef;
}

function canHydrate(routeEpoch, host, propertyRef) {
  return host.isConnected && isCurrentRoute(routeEpoch, propertyRef);
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

function coordinateDetails({ map, property, latitude, longitude }) {
  const section = el("section", "property-source-section");
  append(section, el("h3", "", "Coordinates"), detailList([
    ["Latitude", el("code", "mono", latitude ?? "Unknown")],
    ["Longitude", el("code", "mono", longitude ?? "Unknown")],
    ["Geometry type", map.geometry?.type || property.geometry?.type || "Unknown"],
  ]));
  return section;
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

function saleHistorySection(payload, items) {
  const section = el("section", "stack property-sale-history");
  const release = payload.release || {};
  append(section, el(
    "p",
    "field-help",
    `${payload.has_more ? "Latest " : ""}${formatNumber(items.length)} recorded sale${items.length === 1 ? "" : "s"}${release.release_version ? ` · published version ${release.release_version}` : ""}. Corrected publisher records are shown once at their latest revision.`,
  ));
  append(section, makeTable(
    [{ label: "Contract date" }, { label: "Price" }, { label: "Settlement" }, { label: "Land area" }, { label: "Source match" }],
    items,
    (item) => {
      const row = el("tr");
      append(
        row,
        cell(formatSaleDate(item.contract_date), "primary-cell"),
        cell(formatSalePrice(item.price_aud), "numeric"),
        cell(formatSaleDate(item.settlement_date)),
        cell(formatSaleArea(item), "numeric"),
        cell(confidenceLabel(item.match_confidence)),
      );
      return row;
    },
    "Accepted NSW property sale history",
  ));
  return section;
}

function seifaSection(payload) {
  const section = el("section", "stack property-seifa");
  if (!payload?.supported) {
    append(section, emptyState("SEIFA area evidence is not published", payload?.message || "No accepted ABS SEIFA 2021 release is available for this locality."));
    return section;
  }
  const area = payload.area || {};
  const release = payload.release || {};
  append(
    section,
    el("div", "notice info", "SEIFA describes the surrounding 2021 Suburb and Locality area. It is not a score for this property, household, or its residents."),
    el("p", "field-help", `${area.sal_name || payload.locality} · SAL ${area.sal_code || "not recorded"} · usual resident population ${formatNumber(area.usual_resident_population)}.`),
  );
  const indexes = [
    ["IRSAD", "Relative advantage and disadvantage", area.irsad_australia_decile, area.irsad_score],
    ["IRSD", "Relative disadvantage", area.irsd_australia_decile, area.irsd_score],
    ["IER", "Economic resources", area.ier_australia_decile, area.ier_score],
    ["IEO", "Education and occupation", area.ieo_australia_decile, area.ieo_score],
  ];
  append(section, makeTable(
    [{ label: "Index" }, { label: "Australia decile" }, { label: "Score" }],
    indexes,
    ([code, label, decile, score]) => {
      const row = el("tr");
      append(row, cell(`${code} — ${label}`, "primary-cell"), cell(decile == null ? "Not calculated" : `${decile} of 10`, "numeric"), cell(score == null ? "Not calculated" : formatNumber(score), "numeric"));
      return row;
    },
    "ABS SEIFA 2021 national deciles and scores",
  ));
  append(
    section,
    el("p", "field-help", "Decile 1 represents the lowest-scoring 10% of areas and decile 10 the highest-scoring 10% for that index. Scores are relative area measures; larger-area SAL values are population-weighted from SA1 scores."),
    detailList([
      ["Source", payload.attribution || "Based on Australian Bureau of Statistics data"],
      ["Reference year", area.reference_year || 2021],
      ["Published release", release.release_version || release.dataset_release_id || "Not recorded"],
      ["Area match", humanise(payload.match_method || "exact-normalised-locality-and-state")],
    ]),
  );
  if (Array.isArray(payload.limitations) && payload.limitations.length) {
    const limitations = el("ul", "evidence-list");
    for (const limitation of payload.limitations) append(limitations, el("li", "", limitation));
    append(section, disclosurePanel("How to interpret this evidence", "Area matching and interpretation limits", limitations));
  }
  return section;
}

function formatSaleDate(value) {
  if (!value) return "Not recorded";
  const isoDate = /^\d{4}-\d{2}-\d{2}$/.test(String(value))
    ? new Date(`${value}T00:00:00Z`)
    : new Date(value);
  return Number.isNaN(isoDate.valueOf())
    ? String(value)
    : new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeZone: "UTC" }).format(isoDate);
}

function formatSalePrice(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return `$${formatNumber(value)}`;
}

function formatSaleArea(item) {
  if (item.area_square_metres !== null && item.area_square_metres !== undefined) {
    return `${formatNumber(item.area_square_metres)} m²`;
  }
  if (item.area_original === null || item.area_original === undefined) return "Not recorded";
  return `${formatNumber(item.area_original)} ${item.area_unit || "unit not recorded"}`;
}

function propertyMap({ property, latitude, longitude, announce, routeEpoch }) {
  const host = el("div", "map-context ps-map");
  const canvas = el("div", "ps-map__canvas");
  const status = el("div", "ps-map__status", "Loading interactive map…");
  status.setAttribute("role", "status");
  status.dataset.state = "loading";
  append(host, canvas, status);
  mountMapHelp(host, {
    text: `Latitude ${latitude ?? "unknown"}, longitude ${longitude ?? "unknown"}. Drag to pan; Ctrl/Command + drag rotates. Scroll or use the controls to zoom.`,
  });
  const numericLatitude = Number(latitude);
  const numericLongitude = Number(longitude);
  if (!Number.isFinite(numericLatitude) || !Number.isFinite(numericLongitude)) {
    status.dataset.state = "error";
    status.textContent = "No valid map coordinate is available for this property.";
    return host;
  }
  queueMicrotask(async () => {
    if (!host.isConnected || !routeEpoch.isCurrent()) return;
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
          if (!routeEpoch.isCurrent()) return;
          status.dataset.state = event.state;
          status.textContent = event.message;
          if (event.state === "fallback") announce("The basemap is unavailable; the verified property point remains visible.");
        },
      });
    } catch (error) {
      if (error?.name === "AbortError" || !routeEpoch.isCurrent()) return;
      status.dataset.state = "error";
      status.textContent = "The interactive map could not start; coordinates remain available below.";
      console.warn("Interactive map unavailable; coordinate fallback is active.", error);
    }
  });
  return host;
}

function evidenceRecords(title, items, fields, emptyCopy) {
  const body = el("section", "property-source-section"); append(body, el("h3", "", title));
  if (!items.length) { append(body, el("p", "", emptyCopy)); return body; }
  append(body, sourceRecordList(items, fields));
  return body;
}

function sourceRecordList(items, fields) {
  const list = el("ul", "property-source-records");
  for (const item of items) {
    const record = el("li");
    append(record, detailList(fields.map(([label, value]) => [label, value(item)])));
    append(list, record);
  }
  return list;
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
