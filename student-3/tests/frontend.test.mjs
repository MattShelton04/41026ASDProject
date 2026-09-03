import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { crimeValue, populationLabel } from "../frontend/published.js";

test("published evidence distinguishes zero, missing and incompatible population", () => {
  const series = {observations: [{month: "2026-01-01", count: 3}], observed_months: ["2026-01-01", "2026-02-01"], blank_means_observed_zero: true};
  assert.equal(crimeValue(series, "2026-01-01"), 3);
  assert.equal(crimeValue(series, "2026-02-01"), 0);
  assert.equal(crimeValue(series, "2026-03-01"), null);
  assert.equal(crimeValue({...series, blank_means_observed_zero: false}, "2026-02-01"), null);
  assert.match(populationLabel([]), /unavailable/);
  assert.match(populationLabel([{}, {}]), /ambiguous/);
  assert.match(populationLabel([{usual_resident_population: 1234, reference_year: 2021, sal_code: "10001"}]), /2021 Census/);
});

const html = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
const js = readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");

test("live search replaces prior queries, restores cleared results and ignores stale responses", async () => {
  const nodes = new Map();
  const renders = [];
  const updates = [];
  const selections = [];
  const timers = new Map();
  let timerId = 0;
  const context = vm.createContext({
    document: {querySelector: (id) => { if (!nodes.has(id)) nodes.set(id, {value: ""}); return nodes.get(id); }},
    URLSearchParams,
    setTimeout: (callback) => { timers.set(++timerId, callback); return timerId; },
    clearTimeout: (id) => timers.delete(id),
    featureCollection: (features) => ({features}),
    renders, updates, selections,
  });
  vm.runInContext(js.replace(/^import .*;\r?\n/gm, "").replaceAll('import.meta.url', '"http://localhost/app.js"').replace(/init\(\);\s*$/, "") + `
    renderSuburbs = (items) => renders.push(items.map((item) => item.locality));
    suburbFeatures = (items) => items;
    chooseSuburb = async (locality) => { selections.push(locality); state.selectedLocality = locality; };
    state.map = {layerIds: ["suburbs"], setLayerData: (id, data) => updates.push({id, data})};
  `, context);
  const all = [{locality: "Burwood"}, {locality: "Parramatta"}];
  const requests = [];
  context.fetch = async (url) => {
    const q = new URL(url, "http://localhost").searchParams.get("q");
    requests.push(q);
    return {ok: true, json: async () => ({items: all.filter((item) => item.locality.toLowerCase().includes(q.toLowerCase()))})};
  };
  for (const query of ["Burwood", "Parramatta", "paramatta", "", "p"]) {
    vm.runInContext(`$("#search").value = ${JSON.stringify(query)}; scheduleSuburbSearch({});`, context);
    assert.equal(timers.size, 1);
    const callback = [...timers.values()][0];
    timers.clear();
    await callback();
  }
  assert.deepEqual(requests, ["Burwood", "Parramatta", "paramatta", "", "p"]);
  assert.equal(JSON.stringify(renders), JSON.stringify([["Burwood"], ["Parramatta"], [], ["Burwood", "Parramatta"], ["Parramatta"]]));
  let release;
  context.fetch = async () => { await new Promise((resolve) => { release = resolve; }); return {ok: true, json: async () => ({items: all})}; };
  const older = vm.runInContext('filterSuburbs("Burwood")', context);
  vm.runInContext('scheduleSuburbSearch({}); scheduleSuburbSearch({});', context);
  assert.equal(timers.size, 1);
  const before = renders.length;
  const beforeUpdates = updates.length;
  release();
  await older;
  assert.equal(renders.length, before);
  assert.equal(updates.length, beforeUpdates);
  context.fetch = async () => { throw new Error("offline"); };
  await vm.runInContext('filterSuburbs("Parramatta")', context);
  assert.match(nodes.get("#search-status").textContent, /Could not update suburbs.*offline/);
  context.fetch = async () => ({ok: true, json: async () => ({items: all})});
  await vm.runInContext('search({preventDefault() {}})', context);
  assert.equal(renders.length, before + 1);
  assert.equal(timers.size, 0);
  assert.deepEqual(selections, [], "typing and submitting must not select a suburb");
  assert.equal(vm.runInContext("state.selectedLocality", context), "");
  vm.runInContext('state.selectedLocality = "Burwood"; $("#suburb-detail").hidden = false;', context);
  await vm.runInContext('filterSuburbs("")', context);
  assert.equal(vm.runInContext("state.selectedLocality", context), "Burwood");
  assert.equal(nodes.get("#suburb-detail").hidden, false);
  context.fetch = async () => ({ok: true, json: async () => ({items: [{locality: "Parramatta"}]})});
  await vm.runInContext('filterSuburbs("Parramatta")', context);
  assert.equal(vm.runInContext("state.selectedLocality", context), "");
  assert.equal(nodes.get("#suburb-detail").hidden, true);
  assert.deepEqual(selections, [], "filtering out a selection must not select its replacement");
});

test("suburb search belongs only to overview, below the map and above suburb cards", () => {
  const overview = html.split('id="explore-view"')[1].split('id="trends-view"')[0];
  const hero = html.split('<section class="hero">')[1].split('</section>')[0];
  assert.doesNotMatch(hero, /id="search-form"/);
  assert.equal(html.match(/id="search-form"/g).length, 1);
  assert.ok(overview.indexOf('id="search-form"') > overview.indexOf('id="suburb-detail"'));
  assert.ok(overview.indexOf('id="search-form"') < overview.indexOf('id="suburb-cards"'));
  assert.match(overview, /aria-label="Search overview suburbs"/);
});

test("published evidence has its own tab and routes independently of overview", () => {
  assert.match(html, /href="#published" data-route="published">Published evidence/);
  assert.match(html, /id="published-view"[^>]*data-view="published"[^>]*hidden/);
  const overview = html.split('id="explore-view"')[1].split('id="trends-view"')[0];
  assert.doesNotMatch(overview, /id="published-/);
  assert.match(overview, /id="map"/);
  const views = ["explore", "published", "trends", "comparisons", "assistant"].map((name) => ({dataset: {view: name}}));
  const links = views.map((view) => ({dataset: {route: view.dataset.view}, setAttribute(_key, value) { this.current = value; }}));
  const context = vm.createContext({
    location: {hash: "#published"},
    document: {querySelector: () => ({focus() {}}), querySelectorAll: (selector) => selector === "[data-view]" ? views : links},
  });
  vm.runInContext(js.replace(/^import .*;\r?\n/gm, "").replaceAll('import.meta.url', '"http://localhost/app.js"').replace(/init\(\);\s*$/, ""), context);
  for (const hash of ["#published", "#explore", "#published", "#suburbs"]) {
    context.location.hash = hash;
    vm.runInContext("route()", context);
    const expected = hash === "#published" ? "published" : "explore";
    assert.deepEqual(views.filter((view) => !view.hidden).map((view) => view.dataset.view), [expected]);
    assert.deepEqual(links.filter((link) => link.current === "page").map((link) => link.dataset.route), [expected]);
  }
});

test("map fallback remains hidden until the map fails", () => {
  const css = readFileSync(new URL("../frontend/styles.css", import.meta.url), "utf8");
  assert.match(html, /id="map-fallback" class="map-fallback" hidden/);
  assert.match(css, /#map-fallback\[hidden\]\s*\{\s*display:\s*none;/);
});

test("bookmarks persist, deduplicate, reopen and remove with storage failures handled", async () => {
  function node() {
    return {dataset: {}, children: [], attributes: {}, listeners: {},
      setAttribute(key, value) { this.attributes[key] = value; },
      addEventListener(key, handler) { this.listeners[key] = handler; },
      append(...items) { this.children.push(...items); },
      replaceChildren() { this.children = []; },
      querySelector() { return this.children[0]?.children[0]; },
      focus() {}, close() { this.closed = true; }, scrollIntoView() {},
    };
  }
  const nodes = new Map(["#show-bookmarks", "#bookmark-suburb", "#bookmark-list", "#bookmark-empty", "#bookmark-dialog", "#close-bookmarks", "#toast", "#suburb-detail"].map((id) => [id, node()]));
  nodes.get("#bookmark-suburb").dataset.locality = "Newtown";
  let stored = '["Newtown","Newtown",null,3]';
  const context = vm.createContext({
    document: {querySelector: (id) => nodes.get(id), createElement: node},
    localStorage: {getItem: () => stored, setItem: (_key, value) => { stored = value; }},
    setTimeout: () => {},
  });
  vm.runInContext(js.replace(/^import .*;\r?\n/gm, "").replaceAll('import.meta.url', '"http://localhost/app.js"').replace(/init\(\);\s*$/, "") + '\nstate.suburbs = [{locality:"Newtown"}]; chooseSuburb = async (locality) => { state.selectedLocality = locality; };', context);
  vm.runInContext("loadBookmarks(); renderBookmarks();", context);
  assert.equal(nodes.get("#show-bookmarks").textContent, "Bookmarked suburbs (1)");
  assert.equal(nodes.get("#bookmark-suburb").attributes["aria-pressed"], "true");
  nodes.get("#bookmark-list").children[0].children[0].listeners.click();
  await Promise.resolve();
  assert.equal(nodes.get("#bookmark-dialog").closed, true);
  assert.equal(vm.runInContext("state.selectedLocality", context), "Newtown");
  nodes.get("#bookmark-list").children[0].children[1].listeners.click();
  assert.equal(stored, "[]");
  assert.equal(nodes.get("#bookmark-empty").hidden, false);
  assert.equal(nodes.get("#bookmark-suburb").attributes["aria-pressed"], "false");
  vm.runInContext('toggleBookmark("Newtown"); loadBookmarks();', context);
  assert.equal(stored, '["Newtown"]');
  context.localStorage.setItem = () => { throw new Error("quota"); };
  vm.runInContext('toggleBookmark("Newtown")', context);
  assert.equal(nodes.get("#bookmark-suburb").attributes["aria-pressed"], "true");
  assert.match(nodes.get("#toast").textContent, /Could not save/);
  for (const invalid of ["{", "{}", "null"]) {
    stored = invalid;
    vm.runInContext("loadBookmarks()", context);
    assert.equal(nodes.get("#show-bookmarks").textContent, "Bookmarked suburbs (0)");
  }
  assert.match(html, /aria-labelledby="bookmark-title"/);
});

test("map pin selection loads amenities and zooms without rebuilding the map", async () => {
  const nodes = new Map();
  const updates = [];
  const flights = [];
  let definition;
  let creations = 0;
  const controller = { layerIds: ["suburbs", "places"], setLayerData: (id, data) => updates.push({id, data}), flyTo: (view) => flights.push(view) };
  const context = vm.createContext({
    document: {querySelector: (id) => { if (!nodes.has(id)) nodes.set(id, {}); return nodes.get(id); }, querySelectorAll: () => [{value: "school"}]},
    createMap: async (options) => { definition = options; creations++; return controller; },
    createOpenFreeMapProvider: () => ({}),
    featureCollection: (features) => ({features}),
    pointFeature: (longitude, latitude, properties, id) => ({geometry: {coordinates: [longitude, latitude]}, properties, id}),
    fetch: async (url) => ({ok: true, json: async () => url.includes("/places?") ? {items: [{id: "school", name: "School", place_type: "school", longitude: 151, latitude: -33.8}, {id: "park", place_type: "park"}]} : {suburb: {}, items: []}}),
  });
  vm.runInContext(js.replace(/^import .*;\r?\n/gm, "").replaceAll('import.meta.url', '"http://localhost/app.js"').replace(/init\(\);\s*$/, "") + '\nrenderSuburbDetail = () => {}; state.suburbs = [{id:"parramatta",locality:"Parramatta",longitude:151,latitude:-33.8}];', context);
  await vm.runInContext("initialiseMap()", context);
  const layer = definition.layers.find((item) => item.id === "suburbs");
  await layer.onSelect({properties: {name: "Parramatta"}});
  assert.equal(creations, 1);
  assert.equal(flights[0].zoom, 14);
  assert.equal(flights[0].longitude, 151);
  assert.equal(updates.at(-1).id, "places");
  assert.equal(updates.at(-1).data.features.length, 1);
  assert.equal(updates.at(-1).data.features[0].properties.type, "school");
  assert.match(nodes.get("#live").textContent, /1 filtered places shown for Parramatta/);
  vm.runInContext('state.suburbs.push({id:"newtown",locality:"Newtown",longitude:151.1,latitude:-33.9});', context);
  const pending = [];
  context.fetch = async (url) => {
    if (url.includes("Parramatta")) await new Promise((resolve) => pending.push(resolve));
    return {ok: true, json: async () => url.includes("/places?") ? {items: [{id:"latest",name:"Latest school",place_type:"school",longitude:151.1,latitude:-33.9}]} : {suburb: {},items: []}};
  };
  const older = layer.onSelect({properties: {name: "Parramatta"}});
  await layer.onSelect({properties: {name: "Newtown"}});
  const updateCount = updates.length;
  pending.forEach((resolve) => resolve());
  await older;
  assert.equal(updates.length, updateCount);
  assert.match(nodes.get("#live").textContent, /Newtown/);
});

test("sync controls are optional collapsed operator tools", () => {
  assert.match(html, /<details id="data-maintenance"><summary>Data maintenance \(operators\)<\/summary>/);
  const maintenance = html.split('<details id="data-maintenance">')[1].split("</details>")[0];
  assert.match(maintenance, /data-sync="bocsar-crime"/);
  assert.doesNotMatch(html.split('<details id="data-maintenance">')[0], /data-sync=/);
});

test("readiness follows the feature ingress on both direct and shared hosts", () => {
  assert.match(js, /fetch\(new URL\("\.\/health\/ready", import\.meta\.url\)\)/);
  assert.doesNotMatch(js, /fetch\("\/health\/ready"\)/);
  assert.equal(new URL("./health/ready", "http://localhost:5600/app.js").href,
    "http://localhost:5600/health/ready");
  assert.equal(new URL("./health/ready", "http://localhost:5100/features/suburb-analytics/app.js").href,
    "http://localhost:5100/features/suburb-analytics/health/ready");
});

test("frontend exposes map, chart table, CRUD and responsible-use language", () => {
  assert.match(html, /id="map"/);
  assert.match(html, /id="suburb-detail"/);
  assert.match(html, /id="offence"/);
  assert.match(html, /id="assistant-root"/);
  assert.match(html, /<table>/);
  assert.match(html, /New comparison/);
  assert.match(html, /does not label suburbs safe, unsafe, good or bad/);
  assert.match(js, /crime\/compare/);
  assert.match(js, /area-series/);
  assert.match(js, /createFeatureAssistant/);
  assert.match(js, /\(missing\)/);
  assert.match(js, /setLayerData\("suburbs"/);
  assert.match(js, /createMap/);
});
