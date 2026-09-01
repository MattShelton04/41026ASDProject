import {
  featureBounds,
  featureCollection,
  mergeBounds,
  validateFeatureCollection,
} from "./geojson.js";
import { createOpenFreeMapProvider, validateProvider } from "./provider.js";
import { loadMapLibreRenderer } from "./renderer.js";

const EMPTY_COLLECTION = Object.freeze(featureCollection([]));
const LAYER_ORDER = Object.freeze({ polygon: 0, line: 1, point: 2 });

/**
 * Create a MapLibre-backed map while keeping provider, data, and interaction details behind
 * a small shared controller. Feature code owns layer meaning; this module owns rendering policy.
 */
export async function createMap({
  container,
  layers = [],
  provider = createOpenFreeMapProvider(),
  view = {},
  renderer,
  controls = true,
  styleTimeoutMs = 7_000,
  viewportDebounceMs = 250,
  onStatus = () => {},
  onLayerStatus = () => {},
  signal,
} = {}) {
  if (!container) throw new TypeError("createMap needs a container element.");
  renderer ??= await loadMapLibreRenderer();
  if (!renderer?.Map) {
    throw new TypeError("The MapLibre GL JS renderer is unavailable.");
  }
  validateProvider(provider);
  if (signal?.aborted) throw abortError();
  const definitions = layers.map(validateLayerDefinition);
  const initialBounds = view.bounds ?? (view.center ? null : mergeBounds(
    definitions.map((layer) => layer.data ? featureBounds(layer.data) : null),
  ));
  const options = {
    container,
    style: provider.style,
    center: view.center ?? [151.2093, -33.8688],
    zoom: view.zoom ?? 12,
    minZoom: view.minZoom ?? 3,
    maxZoom: view.maxZoom ?? 20,
    attributionControl: controls ? {
      customAttribution: provider.attributionInStyle ? [] : provider.attribution?.map(formatAttribution) ?? [],
    } : false,
  };
  if (initialBounds) {
    options.bounds = boundsLike(initialBounds);
    options.fitBoundsOptions = { padding: view.padding ?? 42, maxZoom: view.fitMaxZoom ?? 17 };
    delete options.center;
    delete options.zoom;
  }

  onStatus({ state: "loading", provider: provider.id, message: `Loading ${provider.label ?? provider.id}.` });
  const startupAbort = new AbortController();
  let map;
  let disconnectObserver;
  let controller;
  let destroyed = false;
  let disconnectCtrlDragPan = () => {};
  const abortForDisconnect = () => {
    if (controller) controller.destroy();
    else startupAbort.abort();
  };
  const abortForSignal = () => abortForDisconnect();
  try {
    map = new renderer.Map(options);
  } catch (error) {
    throw error;
  }
  if (signal) signal.addEventListener("abort", abortForSignal, { once: true });
  if (globalThis.MutationObserver && container.ownerDocument?.documentElement) {
    disconnectObserver = new globalThis.MutationObserver(() => {
      if (!container.isConnected) abortForDisconnect();
    });
    disconnectObserver.observe(container.ownerDocument.documentElement, { childList: true, subtree: true });
  }
  if (container.isConnected === false) startupAbort.abort();
  try {
  if (map.addImage && map.hasImage) {
    map.on("styleimagemissing", (event) => {
      if (!map.hasImage(event.id)) {
        map.addImage(event.id, { width: 1, height: 1, data: new Uint8Array([0, 0, 0, 0]) });
      }
    });
  }
  if (controls && renderer.NavigationControl) map.addControl(new renderer.NavigationControl(), "top-right");
  if (controls && renderer.ScaleControl) map.addControl(new renderer.ScaleControl({ unit: "metric" }), "bottom-right");
  disconnectCtrlDragPan = wireCtrlDragPan(map, container);
  const baseMapState = await waitForStyle(map, provider, styleTimeoutMs, onStatus, startupAbort.signal);

  const layerState = new Map();
  for (const definition of [...definitions].sort((left, right) => LAYER_ORDER[left.kind] - LAYER_ORDER[right.kind])) {
    addLayer(map, definition, renderer, layerState);
  }

  let refreshTimer;
  let refreshSequence = 0;
  const pending = new Map();

  controller = Object.freeze({
    provider: Object.freeze({
      id: provider.id,
      label: provider.label ?? provider.id,
      attribution: Object.freeze([...(provider.attribution ?? [])]),
      baseMapState,
    }),
    layerIds: Object.freeze(definitions.map((layer) => layer.id)),
    setLayerData(id, data) {
      const state = requireLayer(layerState, id);
      const collection = validateFeatureCollection(data, {
        layerKind: state.definition.kind,
        maxFeatures: state.definition.maxFeatures,
        maxCoordinates: state.definition.maxCoordinates,
      });
      state.data = collection;
      const source = map.getSource(state.sourceId);
      if (!source?.setData) throw new Error(`Map source for ${id} is unavailable.`);
      source.setData(collection);
      return collection.features.length;
    },
    setLayerVisible(id, visible) {
      const state = requireLayer(layerState, id);
      state.visible = Boolean(visible);
      for (const rendererId of state.rendererIds) {
        if (map.getLayer(rendererId)) {
          map.setLayoutProperty(rendererId, "visibility", state.visible ? "visible" : "none");
        }
      }
      if (!state.visible) {
        abortAndClearLayer(state, pending, map);
        onLayerStatus({ id, state: "hidden", featureCount: 0 });
      } else if (state.definition.load) {
        void controller.refresh();
      }
      return state.visible;
    },
    layerState(id) {
      const state = requireLayer(layerState, id);
      return Object.freeze({
        id,
        label: state.definition.label,
        visible: state.visible,
        featureCount: state.data.features.length,
        loading: state.loading,
      });
    },
    getViewport() {
      return viewport(map);
    },
    async refresh() {
      if (destroyed) return [];
      const current = viewport(map);
      const sequence = ++refreshSequence;
      return Promise.allSettled(definitions.filter((layer) => layer.load).map(async (definition) => {
        const state = requireLayer(layerState, definition.id);
        if (!state.visible || current.zoom < definition.minZoom || current.zoom > definition.maxZoom) {
          abortAndClearLayer(state, pending, map);
          const reason = state.visible ? "gated" : "hidden";
          onLayerStatus({ id: definition.id, state: reason, featureCount: 0 });
          return { id: definition.id, skipped: true, reason };
        }
        pending.get(definition.id)?.abort();
        const abort = new AbortController();
        pending.set(definition.id, abort);
        state.loading = true;
        onLayerStatus({ id: definition.id, state: "loading" });
        try {
          const data = await definition.load({ ...current, signal: abort.signal });
          if (destroyed || abort.signal.aborted || sequence !== refreshSequence) return { id: definition.id, stale: true };
          const count = controller.setLayerData(definition.id, data);
          onLayerStatus({ id: definition.id, state: "ready", featureCount: count });
          return { id: definition.id, featureCount: count };
        } catch (error) {
          if (abort.signal.aborted) return { id: definition.id, stale: true };
          onLayerStatus({ id: definition.id, state: "error", error });
          throw error;
        } finally {
          if (pending.get(definition.id) === abort) {
            state.loading = false;
            pending.delete(definition.id);
          }
        }
      }));
    },
    fitToData(ids = definitions.map((layer) => layer.id), { padding = 42, maxZoom = 17 } = {}) {
      const bounds = mergeBounds(ids.map((id) => featureBounds(requireLayer(layerState, id).data)));
      if (bounds) map.fitBounds(boundsLike(bounds), { padding, maxZoom });
      return bounds;
    },
    flyTo({ longitude, latitude, zoom = Math.max(map.getZoom(), 15) }) {
      map.flyTo({ center: [longitude, latitude], zoom });
    },
    resize() {
      map.resize();
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      clearTimeout(refreshTimer);
      for (const abort of pending.values()) abort.abort();
      pending.clear();
      disconnectCtrlDragPan();
      disconnectObserver?.disconnect();
      signal?.removeEventListener("abort", abortForSignal);
      map.remove();
    },
  });

  const scheduleRefresh = () => {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => void controller.refresh(), viewportDebounceMs);
  };
  if (definitions.some((layer) => layer.load)) {
    map.on("moveend", scheduleRefresh);
    await controller.refresh();
  }
  if (destroyed) throw abortError();
  onStatus({
    state: baseMapState,
    provider: provider.id,
    message: baseMapState === "fallback"
      ? "Basemap unavailable; data layers remain interactive on a neutral background."
      : `${provider.label ?? provider.id} ready.`,
  });
  return controller;
  } catch (error) {
    disconnectCtrlDragPan();
    disconnectObserver?.disconnect();
    signal?.removeEventListener("abort", abortForSignal);
    if (!destroyed) {
      destroyed = true;
      map.remove?.();
    }
    throw error;
  }
}

function wireCtrlDragPan(map, container) {
  const eventTarget = container.ownerDocument?.defaultView;
  if (!eventTarget?.addEventListener || typeof map.panBy !== "function") return () => {};
  let previousPoint = null;
  const mouseDown = (event) => {
    const original = event.originalEvent;
    if (!original || original.button !== 0 || (!original.ctrlKey && !original.metaKey)) return;
    event.preventDefault();
    previousPoint = [original.clientX, original.clientY];
  };
  const mouseMove = (event) => {
    if (!previousPoint) return;
    const nextPoint = [event.clientX, event.clientY];
    const offset = [nextPoint[0] - previousPoint[0], nextPoint[1] - previousPoint[1]];
    previousPoint = nextPoint;
    event.preventDefault();
    map.panBy(offset, { duration: 0 }, { originalEvent: event });
  };
  const mouseUp = () => { previousPoint = null; };
  map.on("mousedown", mouseDown);
  eventTarget.addEventListener("mousemove", mouseMove);
  eventTarget.addEventListener("mouseup", mouseUp);
  eventTarget.addEventListener("blur", mouseUp);
  return () => {
    previousPoint = null;
    map.off?.("mousedown", mouseDown);
    eventTarget.removeEventListener("mousemove", mouseMove);
    eventTarget.removeEventListener("mouseup", mouseUp);
    eventTarget.removeEventListener("blur", mouseUp);
  };
}

export function validateLayerDefinition(layer) {
  if (!layer || !/^[a-z][a-z0-9-]{0,62}$/.test(layer.id ?? "")) {
    throw new TypeError("Map layer ids must be lowercase kebab-case and at most 63 characters.");
  }
  if (!Object.hasOwn(LAYER_ORDER, layer.kind)) {
    throw new TypeError(`Map layer ${layer.id} must use kind point, line, or polygon.`);
  }
  if (layer.data && layer.load) throw new TypeError(`Map layer ${layer.id} cannot define both data and load.`);
  if (layer.load && typeof layer.load !== "function") throw new TypeError(`Map layer ${layer.id} load must be a function.`);
  const maxFeatures = boundedInteger(layer.maxFeatures, 10_000, 1, 50_000, "maxFeatures");
  const maxCoordinates = boundedInteger(layer.maxCoordinates, 250_000, 1, 1_000_000, "maxCoordinates");
  const data = validateFeatureCollection(layer.data ?? EMPTY_COLLECTION, {
    layerKind: layer.kind,
    maxFeatures,
    maxCoordinates,
  });
  return Object.freeze({
    ...layer,
    label: String(layer.label ?? layer.id),
    data,
    visible: layer.visible !== false,
    interactive: layer.interactive !== false,
    minZoom: Number.isFinite(layer.minZoom) ? layer.minZoom : 0,
    maxZoom: Number.isFinite(layer.maxZoom) ? layer.maxZoom : 24,
    maxFeatures,
    maxCoordinates,
    style: Object.freeze({ ...defaultStyle(layer.kind), ...(layer.style ?? {}) }),
  });
}

function addLayer(map, definition, renderer, stateById) {
  const sourceId = `ps-source-${definition.id}`;
  const rendererIds = [];
  const source = { type: "geojson", data: definition.data };
  if (definition.kind === "point" && definition.cluster) {
    source.cluster = true;
    source.clusterMaxZoom = definition.clusterMaxZoom ?? 14;
    source.clusterRadius = definition.clusterRadius ?? 48;
  }
  map.addSource(sourceId, source);
  const visibility = definition.visible ? "visible" : "none";
  if (definition.kind === "polygon") {
    rendererIds.push(addRendererLayer(map, {
      id: `ps-${definition.id}-fill`, type: "fill", source: sourceId,
      layout: { visibility },
      paint: { "fill-color": definition.style.color, "fill-opacity": definition.style.opacity },
    }));
    rendererIds.push(addRendererLayer(map, {
      id: `ps-${definition.id}-outline`, type: "line", source: sourceId,
      layout: { visibility },
      paint: {
        "line-color": definition.style.strokeColor,
        "line-width": definition.style.strokeWidth,
        "line-opacity": definition.style.strokeOpacity,
      },
    }));
  } else if (definition.kind === "line") {
    rendererIds.push(addRendererLayer(map, {
      id: `ps-${definition.id}-line`, type: "line", source: sourceId,
      layout: { visibility, "line-cap": "round", "line-join": "round" },
      paint: {
        "line-color": definition.style.color,
        "line-width": definition.style.width,
        "line-opacity": definition.style.opacity,
      },
    }));
  } else {
    if (definition.cluster) addClusterLayers(map, definition, sourceId, visibility, rendererIds);
    const pointId = addRendererLayer(map, {
      id: `ps-${definition.id}-point`, type: "circle", source: sourceId,
      filter: definition.cluster ? ["!", ["has", "point_count"]] : undefined,
      layout: { visibility },
      paint: {
        "circle-radius": definition.style.radius,
        "circle-color": definition.style.color,
        "circle-opacity": definition.style.opacity,
        "circle-stroke-color": definition.style.strokeColor,
        "circle-stroke-width": definition.style.strokeWidth,
      },
    });
    rendererIds.push(pointId);
  }
  const state = {
    definition,
    sourceId,
    rendererIds,
    data: definition.data,
    visible: definition.visible,
    loading: false,
  };
  stateById.set(definition.id, state);
  if (definition.interactive && (definition.popup || definition.onSelect)) {
    const targetId = `ps-${definition.id}-${definition.kind === "polygon" ? "fill" : definition.kind === "line" ? "line" : "point"}`;
    wireInteraction(map, targetId, definition, renderer);
  }
}

function addClusterLayers(map, definition, sourceId, visibility, rendererIds) {
  rendererIds.push(addRendererLayer(map, {
    id: `ps-${definition.id}-cluster`, type: "circle", source: sourceId,
    filter: ["has", "point_count"], layout: { visibility },
    paint: {
      "circle-radius": ["step", ["get", "point_count"], 15, 100, 20, 750, 26],
      "circle-color": definition.style.color,
      "circle-opacity": Math.min(definition.style.opacity + 0.1, 1),
      "circle-stroke-color": definition.style.strokeColor,
      "circle-stroke-width": definition.style.strokeWidth,
    },
  }));
  rendererIds.push(addRendererLayer(map, {
    id: `ps-${definition.id}-cluster-count`, type: "symbol", source: sourceId,
    filter: ["has", "point_count"], layout: {
      visibility,
      "text-field": ["get", "point_count_abbreviated"],
      "text-size": 11,
    },
    paint: { "text-color": "#ffffff" },
  }));
  map.on("click", `ps-${definition.id}-cluster`, async (event) => {
    const feature = event.features?.[0];
    const source = map.getSource(sourceId);
    if (!feature || !source?.getClusterExpansionZoom) return;
    const zoom = await source.getClusterExpansionZoom(feature.properties.cluster_id);
    map.easeTo({ center: feature.geometry.coordinates, zoom });
  });
}

function wireInteraction(map, rendererId, definition, renderer) {
  const popup = definition.popup && renderer.Popup
    ? new renderer.Popup({ closeButton: false, closeOnClick: false, offset: 10 })
    : null;
  map.on("mousemove", rendererId, (event) => {
    map.getCanvas().style.cursor = "pointer";
    const feature = event.features?.[0];
    if (popup && feature) {
      popup.setLngLat(event.lngLat).setDOMContent(popupContent(definition.popup, feature)).addTo(map);
    }
  });
  map.on("mouseleave", rendererId, () => {
    map.getCanvas().style.cursor = "";
    popup?.remove();
  });
  if (definition.onSelect) {
    map.on("click", rendererId, (event) => {
      const feature = event.features?.[0];
      if (feature) definition.onSelect(feature, event.lngLat);
    });
  }
}

function popupContent(specification, feature) {
  const documentRef = globalThis.document;
  if (!documentRef) throw new Error("Map popups need a browser document.");
  const root = documentRef.createElement("div");
  root.className = "ps-map-popup";
  const properties = feature.properties ?? {};
  const titleValue = readPopupValue(specification.title, properties, feature);
  if (titleValue !== undefined && titleValue !== null && titleValue !== "") {
    const title = documentRef.createElement("strong");
    title.textContent = String(titleValue);
    root.append(title);
  }
  for (const field of specification.fields ?? []) {
    const value = readPopupValue(field.value ?? field.property, properties, feature);
    if (value === undefined || value === null || value === "") continue;
    const row = documentRef.createElement("span");
    row.textContent = field.label ? `${field.label}: ${value}` : String(value);
    root.append(row);
  }
  return root;
}

function readPopupValue(accessor, properties, feature) {
  if (typeof accessor === "function") return accessor(properties, feature);
  return accessor ? properties[accessor] : undefined;
}

async function waitForStyle(map, provider, timeoutMs, onStatus, signal) {
  return new Promise((resolve, reject) => {
    let fallback = false;
    let settled = false;
    const cleanup = () => {
      clearTimeout(timer);
      map.off?.("load", loaded);
      map.off?.("error", failed);
      signal?.removeEventListener("abort", aborted);
    };
    const loaded = () => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(fallback ? "fallback" : "ready");
    };
    const useFallback = (reason) => {
      if (fallback || settled) return;
      fallback = true;
      onStatus({ state: "fallback", provider: provider.id, message: reason });
      try {
        map.setStyle(provider.fallbackStyle);
      } catch (error) {
        settled = true;
        cleanup();
        reject(error);
      }
    };
    const failed = () => useFallback("Basemap request failed; loading the neutral fallback.");
    const aborted = () => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(abortError());
    };
    const timer = setTimeout(() => useFallback("Basemap timed out; loading the neutral fallback."), timeoutMs);
    map.on("load", loaded);
    map.on("error", failed);
    signal?.addEventListener("abort", aborted, { once: true });
    if (signal?.aborted) aborted();
  });
}

function abortAndClearLayer(state, pending, map) {
  pending.get(state.definition.id)?.abort();
  pending.delete(state.definition.id);
  state.loading = false;
  state.data = EMPTY_COLLECTION;
  map.getSource(state.sourceId)?.setData?.(EMPTY_COLLECTION);
}

function formatAttribution({ label, url }) {
  const safeLabel = escapeHtml(label);
  return url
    ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${safeLabel}</a>`
    : safeLabel;
}

function escapeHtml(value) {
  return String(value).replaceAll("&", "&amp;").replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function abortError() {
  return new DOMException("Map startup was aborted.", "AbortError");
}

function viewport(map) {
  const bounds = map.getBounds();
  return {
    bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()],
    zoom: map.getZoom(),
  };
}

function boundsLike([west, south, east, north]) {
  const epsilon = 0.0008;
  if (west === east && south === north) {
    return [[west - epsilon, south - epsilon], [east + epsilon, north + epsilon]];
  }
  return [[west, south], [east, north]];
}

function requireLayer(states, id) {
  const state = states.get(id);
  if (!state) throw new RangeError(`Unknown map layer: ${id}`);
  return state;
}

function addRendererLayer(map, definition) {
  if (definition.filter === undefined) delete definition.filter;
  map.addLayer(definition);
  return definition.id;
}

function defaultStyle(kind) {
  if (kind === "polygon") {
    return { color: "#0f766e", opacity: 0.2, strokeColor: "#0f5f59", strokeWidth: 1.5, strokeOpacity: 0.85 };
  }
  if (kind === "line") return { color: "#0f766e", width: 3, opacity: 0.85 };
  return { color: "#c2414f", radius: 7, opacity: 0.9, strokeColor: "#ffffff", strokeWidth: 2 };
}

function boundedInteger(value, fallback, minimum, maximum, name) {
  const resolved = value ?? fallback;
  if (!Number.isInteger(resolved) || resolved < minimum || resolved > maximum) {
    throw new TypeError(`${name} must be an integer from ${minimum} to ${maximum}.`);
  }
  return resolved;
}
