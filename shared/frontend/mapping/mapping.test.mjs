import assert from "node:assert/strict";
import test from "node:test";

import {
  MapDataError,
  NEUTRAL_STYLE,
  createMap,
  createOpenFreeMapProvider,
  createViewportLoader,
  featureBounds,
  featureCollection,
  loadMapLibreRenderer,
  pointFeature,
  validateFeatureCollection,
  validateLayerDefinition,
  validateProvider,
  viewportQuery,
} from "./index.js";

test("the vendored renderer is loaded once on first map use", async () => {
  const original = globalThis.maplibregl;
  delete globalThis.maplibregl;
  const appended = [];
  const documentRef = {
    head: {
      append(element) {
        appended.push(element);
        if (element.tagName === "LINK") {
          queueMicrotask(() => element.listeners.get("load")());
        } else if (element.tagName === "SCRIPT") {
          queueMicrotask(() => {
            globalThis.maplibregl = { Map: class {} };
            element.listeners.get("load")();
          });
        }
      },
    },
    querySelector: () => null,
    createElement(tagName) {
      return {
        tagName: tagName.toUpperCase(),
        dataset: {},
        listeners: new Map(),
        addEventListener(name, handler) { this.listeners.set(name, handler); },
      };
    },
  };
  try {
    const first = loadMapLibreRenderer({ documentRef });
    const second = loadMapLibreRenderer({ documentRef });
    assert.equal(first, second);
    assert.equal((await first).Map, globalThis.maplibregl.Map);
    assert.deepEqual(appended.map((element) => element.tagName), ["LINK", "SCRIPT"]);
    assert.match(appended[1].src, /mapping\/vendor\/maplibre-gl\.js\?v=5\.24\.0$/);
  } finally {
    if (original === undefined) delete globalThis.maplibregl;
    else globalThis.maplibregl = original;
  }
});

test("point helpers enforce WGS84 longitude-latitude coordinates", () => {
  const feature = pointFeature(151.21, -33.86, { name: "Sydney" }, "place-1");
  assert.deepEqual(feature.geometry.coordinates, [151.21, -33.86]);
  assert.equal(feature.id, "place-1");
  assert.throws(() => pointFeature(-33.86, 251.21), /WGS84 longitude, latitude order/);
  assert.throws(() => pointFeature(Number.NaN, -33.86), /finite longitude and latitude/);
});

test("polygons are closed and bounds cover points, lines, and areas", () => {
  const polygon = {
    type: "Feature",
    properties: { locality: "Example" },
    geometry: {
      type: "Polygon",
      coordinates: [[[151.1, -33.9], [151.3, -33.9], [151.3, -33.7], [151.1, -33.9]]],
    },
  };
  const collection = featureCollection([polygon, pointFeature(151.4, -33.8)]);
  assert.deepEqual(featureBounds(collection), [151.1, -33.9, 151.4, -33.7]);
  const openPolygon = structuredClone(polygon);
  openPolygon.geometry.coordinates[0][3] = [151.1, -33.8];
  assert.throws(() => validateFeatureCollection(featureCollection([openPolygon])), /rings must be closed/);
});

test("layer validation rejects mixed geometry and bounded browser limits", () => {
  const points = featureCollection([pointFeature(151.2, -33.8), pointFeature(151.21, -33.81)]);
  assert.throws(
    () => validateFeatureCollection(points, { maxFeatures: 1 }),
    (error) => error instanceof MapDataError && error.code === "map_feature_limit_exceeded",
  );
  assert.throws(
    () => validateLayerDefinition({ id: "schools", kind: "polygon", data: points }),
    (error) => error instanceof MapDataError && error.code === "map_geometry_mismatch",
  );
  assert.throws(() => validateLayerDefinition({ id: "Unsafe Layer", kind: "point" }), /kebab-case/);
  assert.throws(
    () => validateLayerDefinition({ id: "schools", kind: "point", data: points, load: async () => points }),
    /cannot define both data and load/,
  );
  const malformed = [
    { type: "MultiPoint", coordinates: [151.2, -33.8] },
    { type: "LineString", coordinates: [[151.2, -33.8]] },
    { type: "MultiLineString", coordinates: [[[151.2, -33.8]]] },
  ];
  for (const geometry of malformed) {
    assert.throws(() => validateFeatureCollection(featureCollection([
      { type: "Feature", properties: {}, geometry },
    ])), MapDataError);
  }
  assert.throws(
    () => validateFeatureCollection(points, { maxCoordinates: 1 }),
    (error) => error instanceof MapDataError && error.code === "map_coordinate_limit_exceeded",
  );
});

test("the default provider is swappable and always has a local fallback", () => {
  const provider = createOpenFreeMapProvider();
  assert.equal(provider.id, "openfreemap");
  assert.equal(provider.style, "https://tiles.openfreemap.org/styles/liberty");
  assert.equal(provider.fallbackStyle, NEUTRAL_STYLE);
  assert.equal(provider.attributionInStyle, true);
  assert.equal(validateProvider(provider), provider);
  assert.throws(() => validateProvider({ id: "broken", style: provider.style }), /local MapLibre fallback/);
  assert.throws(
    () => validateProvider({ ...provider, attribution: [{ label: "Unsafe", url: "javascript:alert(1)" }] }),
    /attribution/,
  );
});

test("viewport queries are deterministic, bounded, and encode filters", () => {
  const query = viewportQuery({
    bbox: [151.12345678, -33.98765432, 151.3, -33.7],
    zoom: 12.6,
    layers: ["schools", "suburb-boundary"],
    extra: { status: "open", empty: "" },
  });
  assert.equal(query.get("bbox"), "151.123457,-33.987654,151.300000,-33.700000");
  assert.equal(query.get("zoom"), "13");
  assert.equal(query.get("layers"), "schools,suburb-boundary");
  assert.equal(query.get("status"), "open");
  assert.equal(query.has("empty"), false);
  assert.throws(() => viewportQuery({ bbox: [151, -33, 150, -34], zoom: 5 }), /positive area/);
  assert.throws(() => viewportQuery({ bbox: [-181, -34, 152, -33], zoom: 5 }), /valid WGS84/);
  assert.throws(() => viewportQuery({ bbox: [151, -34, 152, -33], zoom: Number.NaN }), /finite zoom/);
  assert.throws(
    () => viewportQuery({ bbox: [151, -34, 152, -33], zoom: 5, layers: ["Unsafe Layer"] }),
    /lowercase kebab-case/,
  );
  assert.throws(
    () => viewportQuery({ bbox: [151, -34, 152, -33], zoom: 5, extra: { bbox: "override" } }),
    /cannot override bbox/,
  );
});

test("viewport loader requests named GeoJSON with cancellation and safe errors", async () => {
  let observed;
  const load = createViewportLoader({
    url: "/api/map-layers",
    layer: "schools",
    baseUrl: "https://propertyscope.test",
    extra: { status: "open" },
    fetchImpl: async (url, options) => {
      observed = { url, options };
      return {
        ok: true,
        status: 200,
        json: async () => ({ layers: { schools: featureCollection([pointFeature(151.2, -33.8)]) } }),
      };
    },
  });
  const abort = new AbortController();
  const data = await load({ bbox: [151.1, -33.9, 151.3, -33.7], zoom: 11, signal: abort.signal });
  assert.equal(data.features.length, 1);
  assert.equal(observed.url.origin, "https://propertyscope.test");
  assert.equal(observed.url.searchParams.get("layers"), "schools");
  assert.equal(observed.options.signal, abort.signal);
  assert.equal(observed.options.headers.Accept, "application/geo+json, application/json");

  const failing = createViewportLoader({
    url: "https://propertyscope.test/api/map",
    fetchImpl: async () => ({ ok: false, status: 413 }),
  });
  await assert.rejects(
    failing({ bbox: [151, -34, 152, -33], zoom: 8 }),
    (error) => error instanceof MapDataError && error.code === "map_api_error",
  );

  const oversized = createViewportLoader({
    url: "https://propertyscope.test/api/map",
    maxResponseBytes: 100,
    fetchImpl: async () => ({
      ok: true,
      status: 200,
      headers: { get: () => "101" },
      json: async () => { throw new Error("body should not be materialised"); },
    }),
  });
  await assert.rejects(
    oversized({ bbox: [151, -34, 152, -33], zoom: 8 }),
    (error) => error instanceof MapDataError && error.code === "map_payload_limit_exceeded",
  );
});

test("custom providers render validated attribution through MapLibre", async () => {
  const renderer = fakeRenderer();
  const provider = {
    id: "council-tiles",
    label: "Council tiles",
    style: { version: 8, sources: {}, layers: [] },
    fallbackStyle: NEUTRAL_STYLE,
    attribution: [{ label: "Council & community", url: "https://example.test/maps?use=public&v=1" }],
  };
  const controller = await createMap({ container: fakeContainer(), renderer, provider });
  assert.deepEqual(renderer.instances[0].options.attributionControl.customAttribution, [
    '<a href="https://example.test/maps?use=public&amp;v=1" target="_blank" rel="noopener noreferrer">Council &amp; community</a>',
  ]);
  controller.destroy();
});

test("map controller keeps polygons below points and supports data, visibility, camera, and cleanup", async () => {
  const renderer = fakeRenderer();
  const polygon = featureCollection([{
    type: "Feature",
    properties: { name: "Area" },
    geometry: { type: "Polygon", coordinates: [[[151, -34], [152, -34], [152, -33], [151, -34]]] },
  }]);
  const points = featureCollection([pointFeature(151.2, -33.8)]);
  const controller = await createMap({
    container: fakeContainer(),
    renderer,
    controls: false,
    view: { center: [151.2, -33.8], zoom: 16 },
    layers: [
      { id: "schools", label: "Schools", kind: "point", data: points, cluster: true },
      { id: "suburb", label: "Suburb", kind: "polygon", data: polygon },
    ],
  });
  const map = renderer.instances[0];
  assert.deepEqual(map.options.center, [151.2, -33.8]);
  assert.equal(map.options.zoom, 16);
  assert.equal(map.options.bounds, undefined);
  assert.deepEqual(
    map.layers.map((layer) => layer.id),
    ["ps-suburb-fill", "ps-suburb-outline", "ps-schools-cluster", "ps-schools-cluster-count", "ps-schools-point"],
  );
  assert.equal(controller.provider.id, "openfreemap");
  assert.equal(controller.provider.baseMapState, "ready");
  assert.equal(controller.layerState("schools").featureCount, 1);
  assert.equal(controller.setLayerVisible("schools", false), false);
  assert.equal(map.layout.get("ps-schools-point:visibility"), "none");
  assert.equal(controller.setLayerData("schools", featureCollection([pointFeature(151.3, -33.7)])), 1);
  assert.deepEqual(controller.fitToData(["schools"]), [151.3, -33.7, 151.3, -33.7]);
  controller.flyTo({ longitude: 151.25, latitude: -33.75, zoom: 15 });
  assert.deepEqual(map.lastFlyTo, { center: [151.25, -33.75], zoom: 15 });
  controller.resize();
  assert.equal(map.resizeCount, 1);
  controller.destroy();
  controller.destroy();
  assert.equal(map.removed, true);
});

test("a basemap load error activates the neutral fallback without losing layers", async () => {
  const renderer = fakeRenderer({ failInitialStyle: true });
  const statuses = [];
  const controller = await createMap({
    container: fakeContainer(),
    renderer,
    controls: false,
    layers: [{ id: "property", kind: "point", data: featureCollection([pointFeature(151.2, -33.8)]) }],
    onStatus: (status) => statuses.push(status.state),
  });
  assert.equal(controller.provider.baseMapState, "fallback");
  assert.equal(renderer.instances[0].style, NEUTRAL_STYLE);
  assert.ok(statuses.includes("fallback"));
  assert.equal(controller.layerState("property").featureCount, 1);
  controller.destroy();
});

test("viewport layers clear outside their zoom gate and reload when re-enabled", async () => {
  const renderer = fakeRenderer();
  let loads = 0;
  const data = featureCollection([pointFeature(151.2, -33.8)]);
  const controller = await createMap({
    container: fakeContainer(),
    renderer,
    controls: false,
    layers: [{ id: "schools", kind: "point", minZoom: 10, maxZoom: 18, load: async () => {
      loads += 1;
      return data;
    } }],
  });
  const map = renderer.instances[0];
  assert.equal(loads, 1);
  assert.equal(controller.layerState("schools").featureCount, 1);
  map.zoom = 8;
  await controller.refresh();
  assert.equal(controller.layerState("schools").featureCount, 0);
  controller.setLayerVisible("schools", false);
  map.zoom = 12;
  controller.setLayerVisible("schools", true);
  await tick();
  assert.equal(loads, 2);
  assert.equal(controller.layerState("schools").featureCount, 1);
  controller.destroy();
});

test("an obsolete refresh cannot clear the replacement request's loading state", async () => {
  const renderer = fakeRenderer();
  const waits = [];
  let call = 0;
  const controller = await createMap({
    container: fakeContainer(),
    renderer,
    controls: false,
    layers: [{ id: "schools", kind: "point", load: async () => {
      call += 1;
      if (call === 1) return featureCollection([]);
      const wait = deferred();
      waits.push(wait);
      return wait.promise;
    } }],
  });
  const first = controller.refresh();
  await tick();
  const second = controller.refresh();
  await tick();
  waits[0].resolve(featureCollection([]));
  await first;
  assert.equal(controller.layerState("schools").loading, true);
  waits[1].resolve(featureCollection([pointFeature(151.2, -33.8)]));
  await second;
  assert.equal(controller.layerState("schools").loading, false);
  assert.equal(controller.layerState("schools").featureCount, 1);
  controller.destroy();
});

test("aborting startup removes a map that has not loaded its style", async () => {
  const renderer = fakeRenderer({ autoLoad: false });
  const abort = new AbortController();
  const result = createMap({
    container: fakeContainer(), renderer, controls: false, signal: abort.signal, styleTimeoutMs: 50_000,
  });
  abort.abort();
  await assert.rejects(result, (error) => error?.name === "AbortError");
  assert.equal(renderer.instances[0].removed, true);
});

function fakeContainer() {
  return { isConnected: true, ownerDocument: null };
}

function fakeRenderer({ failInitialStyle = false, autoLoad = true } = {}) {
  const instances = [];
  class FakeMap {
    constructor(options) {
      this.options = options;
      this.style = options.style;
      this.sources = new Map();
      this.layers = [];
      this.layout = new Map();
      this.handlers = new Map();
      this.zoom = options.zoom ?? 12;
      this.bounds = options.bounds
        ? flatBounds(options.bounds)
        : [options.center[0] - 0.1, options.center[1] - 0.1, options.center[0] + 0.1, options.center[1] + 0.1];
      this.canvas = { style: {} };
      this.resizeCount = 0;
      instances.push(this);
      if (autoLoad) queueMicrotask(() => this.emit(failInitialStyle ? "error" : "load", {}));
    }
    on(event, layerOrHandler, possibleHandler) {
      const layer = typeof layerOrHandler === "string" ? layerOrHandler : "";
      const handler = possibleHandler ?? layerOrHandler;
      const key = `${event}:${layer}`;
      this.handlers.set(key, [...(this.handlers.get(key) ?? []), handler]);
    }
    off(event, handler) {
      const key = `${event}:`;
      this.handlers.set(key, (this.handlers.get(key) ?? []).filter((item) => item !== handler));
    }
    emit(event, payload, layer = "") {
      for (const handler of this.handlers.get(`${event}:${layer}`) ?? []) handler(payload);
    }
    addControl() {}
    setStyle(style) { this.style = style; queueMicrotask(() => this.emit("load", {})); }
    addSource(id, source) {
      this.sources.set(id, {
        ...source,
        setData(data) { this.data = data; },
        async getClusterExpansionZoom() { return 14; },
      });
    }
    getSource(id) { return this.sources.get(id); }
    addLayer(layer) { this.layers.push(layer); }
    getLayer(id) { return this.layers.find((layer) => layer.id === id); }
    setLayoutProperty(id, property, value) { this.layout.set(`${id}:${property}`, value); }
    getBounds() {
      const [west, south, east, north] = this.bounds;
      return { getWest: () => west, getSouth: () => south, getEast: () => east, getNorth: () => north };
    }
    getZoom() { return this.zoom; }
    fitBounds(bounds, options) { this.lastFitBounds = { bounds, options }; }
    flyTo(options) { this.lastFlyTo = options; }
    easeTo(options) { this.lastEaseTo = options; }
    getCanvas() { return this.canvas; }
    resize() { this.resizeCount += 1; }
    remove() { this.removed = true; }
  }
  return { Map: FakeMap, instances };
}

function flatBounds(bounds) {
  return [bounds[0][0], bounds[0][1], bounds[1][0], bounds[1][1]];
}

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}

function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}
