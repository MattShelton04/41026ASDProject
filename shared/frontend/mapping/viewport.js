import { MapDataError, validateFeatureCollection } from "./geojson.js";

const RESERVED_PARAMETERS = new Set(["bbox", "zoom", "layers"]);

export function viewportQuery({ bbox, zoom, layers = [], extra = {} }) {
  if (!Array.isArray(bbox) || bbox.length !== 4 || !bbox.every(Number.isFinite)) {
    throw new MapDataError("A viewport query needs [west, south, east, north] bounds.");
  }
  const [west, south, east, north] = bbox;
  if (west >= east || south >= north) throw new MapDataError("Viewport bounds must have positive area.");
  if (west < -180 || east > 180 || south < -90 || north > 90) {
    throw new MapDataError("Viewport bounds must use valid WGS84 longitude and latitude values.");
  }
  if (!Number.isFinite(zoom)) throw new MapDataError("A viewport query needs a finite zoom level.");
  if (!Array.isArray(layers) || layers.some((layer) => !/^[a-z][a-z0-9-]{0,62}$/.test(layer))) {
    throw new MapDataError("Viewport layer names must be lowercase kebab-case.");
  }
  const query = new URLSearchParams();
  query.set("bbox", bbox.map((value) => value.toFixed(6)).join(","));
  query.set("zoom", String(Math.max(0, Math.min(24, Math.round(zoom)))));
  if (layers.length) query.set("layers", layers.join(","));
  for (const [key, value] of Object.entries(extra)) {
    if (RESERVED_PARAMETERS.has(key)) {
      throw new MapDataError(`Viewport extra parameters cannot override ${key}.`);
    }
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  }
  return query;
}

export function createViewportLoader({
  url,
  layer,
  layers = layer ? [layer] : [],
  extra = {},
  select = layer ? (payload) => payload.layers?.[layer] ?? payload[layer] : (payload) => payload,
  fetchImpl = globalThis.fetch,
  baseUrl = globalThis.location?.origin,
  maxFeatures = 10_000,
  maxCoordinates = 250_000,
  maxResponseBytes = 5_000_000,
} = {}) {
  if (!url) throw new TypeError("A viewport loader needs an API URL.");
  if (typeof fetchImpl !== "function") throw new TypeError("A viewport loader needs fetch().");
  if (!Number.isInteger(maxResponseBytes) || maxResponseBytes < 1) {
    throw new TypeError("maxResponseBytes must be a positive integer.");
  }
  return async ({ bbox, zoom, signal }) => {
    const target = new URL(url, baseUrl);
    target.search = viewportQuery({ bbox, zoom, layers, extra }).toString();
    const response = await fetchImpl(target, {
      signal,
      headers: { Accept: "application/geo+json, application/json" },
    });
    if (!response.ok) {
      throw new MapDataError(`Map API returned HTTP ${response.status}.`, {
        code: "map_api_error",
      });
    }
    const contentLength = Number(response.headers?.get?.("content-length"));
    if (Number.isFinite(contentLength) && contentLength > maxResponseBytes) {
      throw new MapDataError(
        `Map API response exceeds the browser limit of ${maxResponseBytes} bytes.`,
        { code: "map_payload_limit_exceeded" },
      );
    }
    const payload = await readBoundedJson(response, maxResponseBytes);
    const selected = select(payload);
    if (!selected) throw new MapDataError("Map API response did not contain the requested layer.");
    return validateFeatureCollection(selected, { maxFeatures, maxCoordinates });
  };
}

async function readBoundedJson(response, maxResponseBytes) {
  if (typeof response.text !== "function") return response.json();
  const body = await response.text();
  const bytes = new TextEncoder().encode(body).byteLength;
  if (bytes > maxResponseBytes) {
    throw new MapDataError(
      `Map API response exceeds the browser limit of ${maxResponseBytes} bytes.`,
      { code: "map_payload_limit_exceeded" },
    );
  }
  try {
    return JSON.parse(body);
  } catch (cause) {
    throw new MapDataError("Map API returned invalid JSON.", { code: "map_api_error", cause });
  }
}
