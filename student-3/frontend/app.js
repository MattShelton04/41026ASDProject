import { trendPath } from "./trend.js";
import { escapeHtml, requestJsonResponse, createLatestTask } from "./browser/index.js";
import { createMap, createOpenFreeMapProvider, featureCollection, pointFeature } from "./mapping/index.js";
import { createAssistantClient, createAssistantSidecar, createFeatureAssistant, featureActivityHref } from "./ai-chat/index.js";

const API = "/api/suburb-analytics/v1";
const state = { suburbs: [], places: [], map: null, comparisons: [], assistant: null, mapAssistant: null, selectedLocality: "" };
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
let suburbSelection = 0;
let suburbFilterGeneration = 0;
let suburbSearchTimer;
const trendTask = createLatestTask();
let comparisonSaving = false;
const BOOKMARK_KEY = "propertyscope.suburb-analytics.bookmarks.v1";
let bookmarks = [];

function loadBookmarks() {
  try {
    const saved = JSON.parse(localStorage.getItem(BOOKMARK_KEY) || "[]");
    bookmarks = Array.isArray(saved) ? [...new Set(saved.filter((value) => typeof value === "string" && value.length <= 100))] : [];
  } catch { bookmarks = []; }
  updateBookmarkControls();
}

function updateBookmarkControls() {
  $("#show-bookmarks").textContent = `Bookmarked suburbs (${bookmarks.length})`;
  const button = $("#bookmark-suburb");
  if (button) {
    const saved = bookmarks.includes(button.dataset.locality);
    button.textContent = saved ? "Remove bookmark" : "Bookmark suburb";
    button.setAttribute("aria-pressed", String(saved));
  }
}

function toggleBookmark(locality) {
  const saved = bookmarks.includes(locality);
  const next = saved ? bookmarks.filter((item) => item !== locality) : [...bookmarks, locality];
  try { localStorage.setItem(BOOKMARK_KEY, JSON.stringify(next)); }
  catch { toast("Could not save bookmarks. Browser storage may be unavailable."); return; }
  bookmarks = next;
  updateBookmarkControls();
  toast(`${locality} ${saved ? "removed from" : "added to"} your bookmarks.`);
}

function renderBookmarks() {
  const list = $("#bookmark-list");
  list.replaceChildren();
  $("#bookmark-empty").hidden = bookmarks.length > 0;
  [...bookmarks].sort((a, b) => a.localeCompare(b)).forEach((locality) => {
    const row = document.createElement("li");
    const open = document.createElement("button");
    open.type = "button";
    open.className = "ps-button";
    open.textContent = locality;
    open.disabled = !state.suburbs.some((item) => item.locality === locality);
    open.addEventListener("click", () => {
      $("#bookmark-dialog").close();
      chooseSuburb(locality).then(() => {
        if (state.selectedLocality === locality && !$("#suburb-detail").hidden) {
          $("#suburb-detail").scrollIntoView({ block: "nearest" });
          $("#bookmark-suburb").focus({ preventScroll: true });
        }
      });
    });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "ps-button ps-button--small";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove ${locality} bookmark`);
    remove.addEventListener("click", () => {
      toggleBookmark(locality);
      renderBookmarks();
      (list.querySelector("button") || $("#close-bookmarks")).focus();
    });
    row.append(open, remove);
    list.append(row);
  });
}

function chooseSuburb(locality) {
  return selectSuburb(locality).catch((error) => {
    if (state.selectedLocality !== locality) return;
    announce(`Could not load ${locality}: ${error.message}`);
    const detail = $("#suburb-detail");
    detail.hidden = false;
    detail.setAttribute("aria-busy", "false");
    detail.innerHTML = `<div class="suburb-detail__body" role="alert"><h3>Could not load ${escapeHtml(locality)}</h3><p>${escapeHtml(error.message)}</p><button class="ps-button" type="button" data-retry-suburb>Try again</button></div>`;
    detail.querySelector("[data-retry-suburb]").onclick = () => chooseSuburb(locality);
  });
}

async function api(path, options = {}) {
  return (await requestJsonResponse(fetch, `${API}${path}`, options)).body;
}


function announce(message) { $("#live").textContent = message; }
let toastTimer;
function toast(message) { clearTimeout(toastTimer); const node = $("#toast"); node.textContent = message; node.dataset.visible = "true"; toastTimer = setTimeout(() => { node.dataset.visible = "false"; }, 2600); }

function route() {
  const requested = location.hash.slice(1) || "explore";
  const selected = ["explore", "trends", "published", "comparisons", "assistant"].includes(requested) ? requested : "explore";
  $(".hero").hidden = selected === "assistant";
  $$("[data-view]").forEach((view) => { view.hidden = view.dataset.view !== selected; });
  $$("[data-route]").forEach((link) => link.setAttribute("aria-current", link.dataset.route === selected ? "page" : "false"));
  if (selected === "comparisons") loadComparisons();
  if (selected === "trends" && state.suburbs.length) compareTrends();
  $("#main").focus({ preventScroll: true });
}

function optionMarkup(selected = "") {
  return state.suburbs.map((item) => `<option value="${escapeHtml(item.locality)}" ${item.locality === selected ? "selected" : ""}>${escapeHtml(item.locality)}${item.postcode ? ` · ${escapeHtml(item.postcode)}` : ""}</option>`).join("");
}

function populateSelectors() {
  $("#suburb-search-options").innerHTML = state.suburbs.map((item) => `<option value="${escapeHtml(item.locality)}"></option>`).join("");
  ["#locality-a", "#locality-b", "#comparison-a", "#comparison-b"].forEach((id, index) => { $(id).innerHTML = optionMarkup(state.suburbs[index % 2]?.locality); });
  const lgas = [...new Set(state.suburbs.map((item) => item.lga))].sort();
  $("#lga-filter").innerHTML = `<option value="">All areas</option>${lgas.map((item) => `<option>${escapeHtml(item)}</option>`).join("")}`;
}

function renderSuburbs(items) {
  $("#result-count").textContent = `${items.length} supported ${items.length === 1 ? "suburb" : "suburbs"}`;
  $("#suburb-cards").innerHTML = items.map((item) => `<article class="suburb-card"><button type="button" data-locality="${escapeHtml(item.locality)}"><span class="ps-badge ps-badge--confirmed">Published evidence</span><h3>${escapeHtml(item.locality)}</h3><span class="suburb-meta"><span>${escapeHtml(item.postcode || "Locality source")}</span><span>${escapeHtml(item.lga || "LGA shown after selection")}</span></span></button></article>`).join("");
  $$("[data-locality]").forEach((button) => button.addEventListener("click", () => chooseSuburb(button.dataset.locality)));
}

function localityItems(payload) {
  return (payload.items || []).map((entry) => {
    const locality = typeof entry === "string" ? entry : entry.locality;
    return locality ? { id: locality.toLowerCase().replaceAll(" ", "-"), locality, state: "NSW", postcode: "", lga: "", coverage_status: "published" } : null;
  }).filter(Boolean);
}

async function fetchAllPublishedSuburbs(query = "") {
  const items = [];
  let offset = 0;
  const seenOffsets = new Set();
  do {
    if (seenOffsets.has(offset)) break;
    seenOffsets.add(offset);
    const params = new URLSearchParams({ q: query, offset: String(offset) });
    const payload = await api(`/published/suburbs?${params}`);
    items.push(...localityItems(payload));
    if (payload.next_offset === null || payload.next_offset === undefined) break;
    offset = Number(payload.next_offset);
  } while (Number.isSafeInteger(offset) && offset >= 0 && seenOffsets.size < 1000);
  return items;
}

function selectedPlaceTypes() { return new Set($$(".map-filters input:checked").map((input) => input.value)); }

function suburbFeatures(items) {
  return featureCollection(items.filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude)).map((item) => pointFeature(
    item.longitude,
    item.latitude,
    { name: item.locality, postcode: item.postcode, kind: "Supported suburb" },
    item.id,
  )));
}

async function initialiseMap() {
  const suburbPoints = suburbFeatures(state.suburbs);
  try {
    state.map = await createMap({ container: $("#map"), provider: createOpenFreeMapProvider(), layers: [
      { id: "suburbs", label: "Supported suburbs", kind: "point", data: suburbPoints, style: { color: getComputedStyle(document.documentElement).getPropertyValue("--ps-ocean-700").trim(), radius: 7 }, onSelect: (feature) => chooseSuburb(feature.properties.name) },
      { id: "places", label: "Filtered places", kind: "point", data: featureCollection([]), style: { color: getComputedStyle(document.documentElement).getPropertyValue("--ps-coral-700").trim(), radius: 6 }, popup: { title: "name", fields: [{ label: "Type", property: "type" }] } },
    ], view: { center: [151.12, -33.88], zoom: 9 } });
    $("#map-legend").innerHTML = `<span>● Supported suburb</span><span>◆ Place</span>`;
  } catch (error) {
    $("#map").hidden = true; $("#map-fallback").hidden = false;
    $("#map-fallback").innerHTML = `<div><strong>Map renderer unavailable</strong><p>The map could not start in this browser. The suburb list and coordinates remain available.</p></div>`;
  }
}

async function selectSuburb(locality) {
  const selectedSuburb = state.suburbs.find((item) => item.locality === locality);
  if (!selectedSuburb) return;
  const selection = ++suburbSelection;
  state.mapAssistant?.destroy();
  state.mapAssistant = null;
  state.selectedLocality = locality;
  state.places = [];
  $("#suburb-detail").hidden = false;
  $("#suburb-detail").setAttribute("aria-busy", "true");
  $("#suburb-detail").innerHTML = `<div class="suburb-detail__body"><h3>Loading ${escapeHtml(locality)}</h3><p role="status">Reading the available suburb and amenity evidence…</p><div class="ps-skeleton-lines" aria-hidden="true"><span class="ps-skeleton"></span><span class="ps-skeleton"></span></div></div>`;
  state.map?.setLayerData("places", featureCollection([]));
  if (Number.isFinite(selectedSuburb.longitude) && Number.isFinite(selectedSuburb.latitude)) {
    state.map?.flyTo({ longitude: selectedSuburb.longitude, latitude: selectedSuburb.latitude, zoom: 14 });
  }
  announce(`Loading published suburb evidence for ${locality}…`);
  // Published context replaces the legacy demo area-series projections.
  const context = await api(`/published/context?locality=${encodeURIComponent(locality)}`);
  if (selection !== suburbSelection) return;
  state.selectedLocality = locality;
  const suburb = publishedSuburb(context);
  if (Number.isFinite(suburb.longitude) && Number.isFinite(suburb.latitude)) {
    state.map?.flyTo({ longitude: suburb.longitude, latitude: suburb.latitude, zoom: 14 });
  }
  const places = (context.schools || context.items || []).map((school) => ({
    id: school.school_code,
    name: school.school_name,
    place_type: "school",
    latitude: school.latitude,
    longitude: school.longitude,
    coverage_status: school.operational_status,
    source_release: school.provenance?.release_id,
  })).filter((place) => place.name && Number.isFinite(place.latitude) && Number.isFinite(place.longitude));
  state.places = places.filter((place) => selectedPlaceTypes().has(place.place_type));
  renderSuburbDetail(suburb, { schools: { value: places.length }, seifa: context.population?.[0] }, context);
  state.assistant?.controller.setContext({ route: "suburbs/detail", locality });
  const points = featureCollection(state.places.map((place) => pointFeature(place.longitude, place.latitude, { name: place.name, type: place.place_type }, place.id)));
  state.map?.setLayerData("places", points);
  announce(`${state.places.length} filtered places shown for ${locality}.`);
}

function publishedSuburb(context) {
  const population = context.population?.length === 1 ? context.population[0] : {};
  const schools = context.schools || context.items || [];
  const coordinates = schools.filter((item) => Number.isFinite(item.latitude) && Number.isFinite(item.longitude));
  const locality = population.sal_name || schools[0]?.locality_original || context.locality || "Selected locality";
  return {
    id: locality.toLowerCase().replaceAll(" ", "-"),
    state: population.state || "NSW",
    locality,
    postcode: "",
    lga: schools[0]?.lga || "Not available",
    latitude: coordinates.length ? coordinates.reduce((sum, item) => sum + item.latitude, 0) / coordinates.length : null,
    longitude: coordinates.length ? coordinates.reduce((sum, item) => sum + item.longitude, 0) / coordinates.length : null,
    source_release: (context.sources || []).map((item) => item.release_id).filter(Boolean).join(", ") || "published-source",
    coverage_status: "published",
    population: population.usual_resident_population,
    area_km2: null,
    description: "Published evidence for this NSW locality. Review source coverage and limitations before making decisions.",
    observed_at: (context.sources || []).map((item) => item.source_retrieved_at).filter(Boolean).sort().at(-1) || "",
  };
}

function renderSuburbDetail(suburb, metrics, context = {}) {
  const values = [
    [Number.isFinite(suburb.population) ? suburb.population.toLocaleString("en-AU") : "Not available", "2021 usual residents"],
    [suburb.lga || "Not available", "School-source LGA"],
    [metrics.seifa?.irsad_australia_decile ? `Decile ${metrics.seifa.irsad_australia_decile}` : "Not available", "SEIFA IRSAD decile"],
    [`${metrics.schools?.value ?? 0}`, "Published school locations"],
  ];
  const detail = $("#suburb-detail");
  detail.hidden = false;
  detail.setAttribute("aria-busy", "false");
  detail.innerHTML = `<div class="suburb-detail__body"><div class="suburb-detail__heading"><div><p class="ps-eyebrow">Selected published locality</p><h3>${escapeHtml(suburb.locality)}</h3><p>${escapeHtml(suburb.description)}</p></div><div class="row-actions"><button class="ps-button ps-button--small" data-compare-locality="${escapeHtml(suburb.locality)}">Use in comparison</button><button class="ps-button ps-button--small ps-button--primary" type="button" data-ask-locality="${escapeHtml(suburb.locality)}">Ask about ${escapeHtml(suburb.locality)}</button></div></div><div class="context-grid">${values.map(([value, label]) => `<article class="context-metric"><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></article>`).join("")}</div><div class="evidence-strip"><span class="ps-badge ps-badge--confirmed">${escapeHtml(suburb.coverage_status)} evidence</span><span>Source releases ${escapeHtml(suburb.source_release)}</span><span>Observed ${escapeHtml((suburb.observed_at || "").slice(0, 10) || "not stated")}</span><span>${metrics.schools?.value ?? 0} published schools; catchment status: not assessed</span></div></div>`;
  detail.querySelector?.("[data-compare-locality]")?.addEventListener("click", () => {
    $("#locality-a").value = suburb.locality;
    location.hash = "#trends";
  });
  const bookmark = document.createElement("button");
  bookmark.id = "bookmark-suburb";
  bookmark.type = "button";
  bookmark.className = "ps-button ps-button--small";
  bookmark.dataset.locality = suburb.locality;
  bookmark.addEventListener("click", () => toggleBookmark(suburb.locality));
  detail.querySelector?.(".suburb-detail__heading")?.append(bookmark);
  updateBookmarkControls();
  mountMapAssistant(suburb.locality, detail.querySelector("[data-ask-locality]"));
}

function mountMapAssistant(locality, trigger) {
  state.mapAssistant?.destroy();
  const client = createAssistantClient({ apiRoot: `${API}/assistant` });
  state.mapAssistant = createAssistantSidecar({
    root: $("#map-assistant-layout"),
    trigger,
    client,
    context: { route: "suburbs/detail", locality },
    scopes: [{ id: "feature", label: locality, description: `Published evidence for ${locality}.` }],
    suggestions: [
      `What published evidence is available for ${locality}?`,
      `Which evidence is missing for ${locality}?`,
      "What do the nearby school records establish?",
    ],
    activityHref: featureActivityHref({
      featureKey: "student-3-suburb-analytics",
      featureLabel: "Suburb context",
      returnTo: "/features/suburb-analytics/#explore",
    }),
    draftKey: `propertyscope:suburb-map-assistant:${locality}`,
    title: `Ask about ${locality}`,
    description: "Answers use published locality evidence and reviewed suburb guidance.",
    welcomeTitle: `Questions about ${locality}`,
    welcomeMessage: "I can explain the evidence shown here, its sources and its limits. Crime comparisons stay in the deterministic Crime trends workspace.",
    placeholder: `Ask about the evidence available for ${locality}…`,
    announce,
  });
}

async function search(event) {
  event.preventDefault();
  await filterSuburbs();
}

function scheduleSuburbSearch(event) {
  clearTimeout(suburbSearchTimer);
  ++suburbFilterGeneration;
  if (event.isComposing) return;
  $("#search-status").textContent = "Updating suburb results…";
  suburbSearchTimer = setTimeout(() => filterSuburbs(), 250);
}

async function filterSuburbs(query = $("#search").value.trim()) {
  clearTimeout(suburbSearchTimer);
  const generation = ++suburbFilterGeneration;
  $("#search-status").textContent = "Updating suburb results…";
  try {
  const items = await fetchAllPublishedSuburbs(query);
  const payload = { items, count: items.length, page: { total: items.length } };
  if (generation !== suburbFilterGeneration) return;
  renderSuburbs(payload.items);
  $("#search-status").textContent = payload.items.length
    ? `${payload.items.length} matching ${payload.items.length === 1 ? "suburb" : "suburbs"}.`
    : "No matching suburbs. Check the spelling, try a postcode, or clear the search and suburb filters.";
  if (generation !== suburbFilterGeneration) return;
  announce(`${payload.page?.total ?? payload.count} suburb results.`);
  } catch (error) {
    if (generation !== suburbFilterGeneration) return;
    $("#search-status").textContent = `Could not update suburbs: ${error.message} Previous results are still shown. Try again.`;
  }
}

async function compareTrends(event) {
  event?.preventDefault();
  const values = { a: $("#locality-a").value, b: $("#locality-b").value, from: $("#from-month").value, to: $("#to-month").value, measure: $("#measure").value, offence: $("#offence").value };
  const task = trendTask.start();
  const notice = $("#trend-notice");
  const chart = $(".chart-card");
  chart.setAttribute("aria-busy", "false");
  if (!values.a || !values.b || values.a === values.b) { notice.textContent = "Choose two different supported suburbs."; return; }
  if (!values.from || !values.to || values.from > values.to) { notice.textContent = "Choose a valid period with the start month before the end month."; $("#from-month").focus(); return; }
  chart.setAttribute("aria-busy", "true");
  notice.textContent = "Loading the requested comparison. Any chart still visible is the previously applied result.";
  try {
    const payload = await api(`/published/crime/compare?localities=${encodeURIComponent(values.a + "," + values.b)}&from=${values.from}&to=${values.to}&measure=${values.measure}&offence=${values.offence}`, { signal: task.signal });
    if (!task.isCurrent()) return;
    if (!Array.isArray(payload.series) || payload.series.length < 2) throw new Error("The service did not return both requested suburb series.");
    renderTrend(payload);
    notice.textContent = `${values.a} and ${values.b} · ${values.from} to ${values.to}. ${(payload.limitations || []).join(" ")}`;
  } catch (error) {
    if (task.isCurrent()) notice.textContent = `${error.message} Any chart still shown is the previous result, not the requested comparison. Retry with Compare trends.`;
  } finally {
    if (task.isCurrent()) chart.setAttribute("aria-busy", "false");
  }
}

function renderTrend(payload) {
  $("#chart-legend").innerHTML = payload.series.map((series, index) => `<span><i class="legend-line legend-line--${index ? "b" : "a"}" aria-hidden="true"></i>${escapeHtml(series.locality)} · ${index ? "dashed" : "solid"} line</span>`).join("");
  const all = payload.series.flatMap((series) => series.items.map((item) => item.value).filter(Number.isFinite));
  const maximum = Math.max(...all, 1); const months = [...new Set(payload.series.flatMap((series) => series.items.map((item) => item.month)))].sort();
  const sourceUnit = payload.series.flatMap((series) => series.items).find((item) => item.unit)?.unit;
  const unit = sourceUnit || (payload.measure === "rate" ? "per 100,000" : "count");
  const unitLabel = unit === "per 100,000" ? "per 100,000 people" : unit;
  const measureLabel = payload.measure === "rate" ? "Recorded offence rate" : "Recorded offences";
  const width = 760, height = 300, left = 58, right = 28, top = 24, bottom = 52;
  const x = (index) => left + index * ((width - left - right) / Math.max(months.length - 1, 1));
  const y = (value) => height - bottom - (value / maximum) * (height - top - bottom);
  const path = (items) => trendPath(items, months, x, y);
  $("#chart").innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-labelledby="chart-title chart-desc"><title id="chart-title">${escapeHtml(payload.offence)} ${escapeHtml(payload.measure)} comparison</title><desc id="chart-desc">Trend lines for ${payload.series.map((item) => escapeHtml(item.locality)).join(" and ")}. Horizontal axis: month. Vertical axis: ${escapeHtml(measureLabel)}, ${escapeHtml(unitLabel)}.</desc><text class="axis-title" x="${width / 2}" y="${height - 4}" text-anchor="middle">Month</text><text class="axis-title" transform="rotate(-90)" x="${-height / 2}" y="13" text-anchor="middle">${escapeHtml(measureLabel)} (${escapeHtml(unitLabel)})</text>${[0,.25,.5,.75,1].map((part) => `<line class="grid" x1="${left}" y1="${y(maximum*part)}" x2="${width-right}" y2="${y(maximum*part)}"></line><text x="${left-8}" y="${y(maximum*part)+4}" text-anchor="end">${Math.round(maximum*part)}</text>`).join("")}<path class="line-a" d="${path(payload.series[0].items)}"></path><path class="line-b" d="${path(payload.series[1].items)}"></path>${payload.series.map((series, seriesIndex) => series.items.filter((item) => Number.isFinite(item.value)).map((item) => `<circle class="point-${seriesIndex ? "b" : "a"}" cx="${x(months.indexOf(item.month))}" cy="${y(item.value)}" r="5"><title>${escapeHtml(series.locality)} ${escapeHtml(item.month)}: ${escapeHtml(item.value)} ${escapeHtml(unitLabel)}</title></circle>`).join("")).join("")}${months.map((month, index) => `<text x="${x(index)}" y="${height-bottom+20}" text-anchor="middle">${escapeHtml(month.slice(5))}</text>`).join("")}</svg>`;
  $("#summary-cards").innerHTML = payload.series.map((series) => { const observed = series.items.filter((item) => Number.isFinite(item.value)); const first = observed[0]?.value ?? null, last = observed.at(-1)?.value ?? null; const change = first === null || last === null ? "Unavailable" : `${last - first >= 0 ? "+" : ""}${(last - first).toFixed(1)}`; return `<article class="summary-card"><span>${escapeHtml(series.locality)} · ${escapeHtml(unitLabel)}</span><strong>${change}</strong><span>absolute change (${escapeHtml(unitLabel)}) across selected fixture period</span></article>`; }).join("");
  const table = $("#trend-head").closest?.("table");
  const caption = table?.querySelector("caption");
  if (caption) caption.textContent = `Accessible trend data in ${unitLabel}. A dash means missing evidence, never zero.`;
  $("#trend-head").innerHTML = `<tr><th scope="col">Month</th>${payload.series.map((series) => `<th scope="col">${escapeHtml(series.locality)} (${escapeHtml(unitLabel)})</th>`).join("")}</tr>`;
  $("#trend-body").innerHTML = months.map((month) => `<tr><th>${escapeHtml(month)}</th>${payload.series.map((series) => {
    const item = series.items.find((row) => row.month === month);
    const value = item?.value === null || item?.value === undefined ? "—" : item.value;
    const stateLabel = item?.zero_missing_state === "recorded_zero"
      ? " (recorded zero)"
      : item?.zero_missing_state === "missing" ? " (missing)" : "";
    return `<td>${escapeHtml(value)}${stateLabel}</td>`;
  }).join("")}</tr>`).join("");
}

async function loadComparisons() {
  try {
    const payload = await api("/suburb-comparisons"); state.comparisons = payload.items;
    $("#comparison-list").innerHTML = payload.items.map((item) => `<article class="comparison-card"><div><span class="ps-badge ps-badge--info">${escapeHtml(item.status)}</span><h3>${escapeHtml(item.name)}</h3><p>${item.localities.map(escapeHtml).join(" ↔ ")} · ${escapeHtml(item.from_month)} to ${escapeHtml(item.to_month)} · ${escapeHtml(item.measure)}</p><p>${escapeHtml(item.notes)}</p></div><div class="row-actions"><button class="ps-button ps-button--small ps-button--primary" data-load="${escapeHtml(item.id)}">Load in crime trends</button><button class="ps-button ps-button--small" data-edit="${escapeHtml(item.id)}">Edit</button><button class="ps-button ps-button--small ps-button--danger" data-delete="${escapeHtml(item.id)}">Delete</button></div></article>`).join("") || `<div class="notice">No saved comparisons yet.</div>`;
    $$('[data-load]').forEach((button) => button.onclick = () => loadComparison(state.comparisons.find((item) => item.id === button.dataset.load)));
    $$("[data-edit]").forEach((button) => button.onclick = () => openDialog(state.comparisons.find((item) => item.id === button.dataset.edit)));
    $$("[data-delete]").forEach((button) => button.onclick = () => deleteComparison(button.dataset.delete));
  } catch (error) { $("#comparison-list").innerHTML = `<div class="notice">${escapeHtml(error.message)}</div>`; }
}

function loadComparison(item) {
  if (!item || item.localities?.length !== 2 || !item.localities.every((locality) => state.suburbs.some((suburb) => suburb.locality === locality))) {
    toast("This saved comparison cannot be loaded. Choose exactly two currently available suburbs, then save it again.");
    return;
  }
  $("#locality-a").value = item.localities[0];
  $("#locality-b").value = item.localities[1];
  $("#from-month").value = item.from_month;
  $("#to-month").value = item.to_month;
  $("#measure").value = item.measure;
  $("#offence").value = "all_recorded";
  $("#trend-notice").textContent = `Loading saved comparison “${item.name}”…`;
  location.hash = "#trends";
}

function openDialog(item = null) {
  $("#dialog-title").textContent = item ? "Edit comparison" : "New comparison"; $("#comparison-id").value = item?.id || ""; $("#comparison-version").value = item?.version ?? "";
  $("#comparison-name").value = item?.name || ""; $("#comparison-a").innerHTML = optionMarkup(item?.localities?.[0]); $("#comparison-b").innerHTML = optionMarkup(item?.localities?.[1] || state.suburbs[1]?.locality);
  $("#comparison-from").value = item?.from_month || "2026-01"; $("#comparison-to").value = item?.to_month || "2026-06"; $("#comparison-measure").value = item?.measure || "count"; $("#comparison-status").value = item?.status || "saved"; $("#comparison-notes").value = item?.notes || ""; $("#form-error").textContent = ""; $("#comparison-dialog").showModal(); $("#comparison-name").focus();
}

async function saveComparison(event) {
  event.preventDefault(); if (event.submitter?.value !== "save") { $("#comparison-dialog").close(); return; }
  if (comparisonSaving) return;
  const id = $("#comparison-id").value; const payload = { name: $("#comparison-name").value.trim(), localities: [$("#comparison-a").value, $("#comparison-b").value], from_month: $("#comparison-from").value, to_month: $("#comparison-to").value, measure: $("#comparison-measure").value, selected_indicators: ["recorded_offences"], priorities: [], notes: $("#comparison-notes").value.trim(), status: $("#comparison-status").value };
  if (payload.localities[0] === payload.localities[1] || payload.from_month > payload.to_month) {
    $("#form-error").textContent = "Choose two different suburbs and a valid date period.";
    $("#form-error").focus(); return;
  }
  comparisonSaving = true;
  $("#save-comparison").disabled = true;
  if (id) payload.version = Number($("#comparison-version").value);
  try { await api(id ? `/suburb-comparisons/${id}` : "/suburb-comparisons", { method: id ? "PUT" : "POST", body: JSON.stringify(payload) }); $("#comparison-dialog").close(); toast(id ? "Comparison updated." : "Comparison created."); loadComparisons(); } catch (error) { $("#form-error").textContent = error.message; $("#form-error").focus(); } finally { comparisonSaving = false; $("#save-comparison").disabled = false; }
}

async function deleteComparison(id) { if (!confirm("Delete this saved comparison?")) return; try { await api(`/suburb-comparisons/${id}`, { method: "DELETE" }); toast("Comparison deleted."); loadComparisons(); } catch (error) { toast(error.message); } }
function initialiseAssistant() {
  state.assistant = createFeatureAssistant({
    root: $("#assistant-root"),
    apiRoot: `${API}/assistant`,
    featureKey: "student-3-suburb-analytics",
    featureLabel: "Suburb context",
    returnTo: "/features/suburb-analytics/#assistant",
    scopes: [{ id: "feature", label: "Suburb context", description: "Published suburb evidence, sources, methodology and limitations." }],
    contextOptions: [
      { id: "general", label: "General guidance", description: "Ask what suburb analytics covers, how evidence should be interpreted, or what it cannot establish.", context: { route: "assistant" } },
      { id: "locality", label: "Selected suburb", description: "Ground the question in one exact supported NSW locality.", context: { route: "suburbs/detail" }, parameter: { name: "locality", label: "Locality", placeholder: "Parramatta", help: "Enter one suburb shown in the supported locality list." } },
    ],
    suggestions: [
      "What is the difference between published and demonstration data?",
      "How does suburb analytics distinguish recorded zero from missing evidence?",
      "What can nearby-school evidence establish?",
    ],
    title: "Ask about suburb evidence",
    description: "Ask about one supported locality, Suburb context methodology, sources and evidence limits. Use Crime trends for deterministic suburb comparisons.",
    welcomeTitle: "What would you like to understand?",
    welcomeMessage: "I use published locality evidence and reviewed guidance. I do not compare or rank suburbs, predict crime or recommend where to buy.",
    placeholder: "Ask about a locality, source, methodology or evidence limitation…",
    announce,
  });
}

async function init() {
  $("#search").addEventListener("input", scheduleSuburbSearch);
  $("#search").addEventListener("compositionend", scheduleSuburbSearch);
  loadBookmarks();
  $("#show-bookmarks").addEventListener("click", () => { renderBookmarks(); $("#bookmark-dialog").showModal(); });
  $("#close-bookmarks").addEventListener("click", () => $("#bookmark-dialog").close());
  addEventListener("storage", (event) => {
    if (event.key === BOOKMARK_KEY || event.key === null) {
      loadBookmarks();
      if ($("#bookmark-dialog").open) renderBookmarks();
    }
  });
  addEventListener("hashchange", route); $("#search-form").addEventListener("submit", search); $("#trend-form").addEventListener("submit", compareTrends); $("#new-comparison").onclick = () => openDialog(); $("#comparison-form").addEventListener("submit", saveComparison); initialiseAssistant();
  ["#lga-filter", "#amenity-filter", "#sort-filter"].forEach((selector) => $(selector).addEventListener("change", () => filterSuburbs()));
  $$(".map-filters input").forEach((input) => input.addEventListener("change", () => {
    const current = state.selectedLocality || state.suburbs[0]?.locality;
    if (current) chooseSuburb(current);
  }));
  try { const [health, suburbs] = await Promise.all([requestJsonResponse(fetch, new URL("./health/ready", import.meta.url)).then(({body}) => body), fetchAllPublishedSuburbs()]); state.suburbs = suburbs; $("#service-state").className = "ps-badge ps-badge--confirmed"; $("#service-state").textContent = ["ready", "healthy"].includes(health.status) ? "Published data ready" : "Partial service"; populateSelectors(); renderSuburbs(state.suburbs); await initialiseMap(); } catch (error) { $("#service-state").textContent = "Service unavailable"; $("#result-count").textContent = error.message; }
  addEventListener("pagehide", () => { trendTask.cancel(); clearTimeout(suburbSearchTimer); state.mapAssistant?.destroy?.(); state.assistant?.destroy?.(); state.map?.destroy(); }, { once: true });
  route();
}

init();
