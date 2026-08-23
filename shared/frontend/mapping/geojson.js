const GEOMETRY_TYPES = new Set([
  "Point",
  "MultiPoint",
  "LineString",
  "MultiLineString",
  "Polygon",
  "MultiPolygon",
]);

const LAYER_GEOMETRIES = Object.freeze({
  point: new Set(["Point", "MultiPoint"]),
  line: new Set(["LineString", "MultiLineString"]),
  polygon: new Set(["Polygon", "MultiPolygon"]),
});

export class MapDataError extends Error {
  constructor(message, { code = "invalid_map_data", cause } = {}) {
    super(message, { cause });
    this.name = "MapDataError";
    this.code = code;
  }
}

export function featureCollection(features = []) {
  if (!Array.isArray(features)) throw new MapDataError("GeoJSON features must be an array.");
  return { type: "FeatureCollection", features };
}

export function pointFeature(longitude, latitude, properties = {}, id = undefined) {
  const feature = {
    type: "Feature",
    geometry: { type: "Point", coordinates: [longitude, latitude] },
    properties: properties ?? {},
  };
  if (id !== undefined) feature.id = id;
  validateFeature(feature);
  return feature;
}

export function asFeatureCollection(value) {
  if (value?.type === "FeatureCollection") return value;
  if (value?.type === "Feature") return featureCollection([value]);
  if (GEOMETRY_TYPES.has(value?.type)) {
    return featureCollection([{ type: "Feature", geometry: value, properties: {} }]);
  }
  throw new MapDataError("Map data must be a GeoJSON FeatureCollection, Feature, or geometry.");
}

export function validateFeatureCollection(
  value,
  { maxFeatures = 10_000, maxCoordinates = 250_000, layerKind } = {},
) {
  const collection = asFeatureCollection(value);
  if (collection.features.length > maxFeatures) {
    throw new MapDataError(
      `Map layer contains ${collection.features.length} features; the browser limit is ${maxFeatures}.`,
      { code: "map_feature_limit_exceeded" },
    );
  }
  let coordinateCount = 0;
  for (const feature of collection.features) {
    coordinateCount += validateFeature(feature, {
      layerKind,
      maxCoordinates: maxCoordinates - coordinateCount,
    });
  }
  return collection;
}

export function validateFeature(feature, { layerKind, maxCoordinates = Infinity } = {}) {
  if (!feature || feature.type !== "Feature") {
    throw new MapDataError("Every map item must be a GeoJSON Feature.");
  }
  if (feature.properties !== null && !isPlainObject(feature.properties)) {
    throw new MapDataError("GeoJSON feature properties must be an object or null.");
  }
  const geometry = feature.geometry;
  if (!geometry || !GEOMETRY_TYPES.has(geometry.type)) {
    throw new MapDataError(
      "Supported geometries are Point, MultiPoint, LineString, MultiLineString, Polygon, and MultiPolygon.",
    );
  }
  if (layerKind && !LAYER_GEOMETRIES[layerKind]?.has(geometry.type)) {
    throw new MapDataError(
      `Geometry ${geometry.type} is not compatible with a ${layerKind} layer.`,
      { code: "map_geometry_mismatch" },
    );
  }
  validateGeometryShape(geometry);
  return scanPositions(geometry.coordinates, () => {}, { count: 0, maxCoordinates });
}

export function featureBounds(value) {
  const collection = asFeatureCollection(value);
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const feature of collection.features) {
    validateFeature(feature);
    scanPositions(feature.geometry.coordinates, ([longitude, latitude]) => {
      west = Math.min(west, longitude);
      south = Math.min(south, latitude);
      east = Math.max(east, longitude);
      north = Math.max(north, latitude);
    });
  }
  return Number.isFinite(west) ? [west, south, east, north] : null;
}

export function mergeBounds(bounds) {
  const valid = bounds.filter(Boolean);
  if (!valid.length) return null;
  return valid.reduce(
    (result, item) => [
      Math.min(result[0], item[0]),
      Math.min(result[1], item[1]),
      Math.max(result[2], item[2]),
      Math.max(result[3], item[3]),
    ],
    [...valid[0]],
  );
}

function validateGeometryShape(geometry) {
  const coordinates = geometry.coordinates;
  if (!Array.isArray(coordinates)) throw new MapDataError(`${geometry.type} coordinates must be an array.`);
  if (geometry.type === "Point") return validatePosition(coordinates);
  if (geometry.type === "MultiPoint") return validatePositionArray(coordinates, 0, "MultiPoint");
  if (geometry.type === "LineString") return validatePositionArray(coordinates, 2, "LineString");
  if (geometry.type === "MultiLineString") {
    for (const line of coordinates) validatePositionArray(line, 2, "MultiLineString member");
    return;
  }
  const polygons = geometry.type === "Polygon"
    ? [coordinates]
    : geometry.type === "MultiPolygon" ? coordinates : [];
  for (const polygon of polygons) {
    if (!Array.isArray(polygon) || !polygon.length) throw new MapDataError("A Polygon needs an exterior ring.");
    for (const ring of polygon) {
      if (!Array.isArray(ring) || ring.length < 4) {
        throw new MapDataError("A polygon ring needs at least four positions.");
      }
      const first = ring[0];
      const last = ring.at(-1);
      if (!Array.isArray(first) || !Array.isArray(last) || first[0] !== last[0] || first[1] !== last[1]) {
        throw new MapDataError("GeoJSON polygon rings must be closed.");
      }
    }
  }
}

function validatePositionArray(coordinates, minimum, label) {
  if (!Array.isArray(coordinates) || coordinates.length < minimum) {
    throw new MapDataError(`${label} needs at least ${minimum} positions.`);
  }
  for (const position of coordinates) {
    if (!Array.isArray(position) || typeof position[0] !== "number") {
      throw new MapDataError(`${label} coordinates must be positions.`);
    }
    validatePosition(position);
  }
}

function scanPositions(value, visit, state = { count: 0, maxCoordinates: Infinity }) {
  if (!Array.isArray(value)) throw new MapDataError("GeoJSON coordinates must be arrays.");
  if (typeof value[0] === "number") {
    validatePosition(value);
    state.count += 1;
    if (state.count > state.maxCoordinates) {
      throw new MapDataError(
        `Map layer exceeds the browser limit of ${state.maxCoordinates} coordinates.`,
        { code: "map_coordinate_limit_exceeded" },
      );
    }
    visit(value);
    return 1;
  }
  let count = 0;
  for (const child of value) count += scanPositions(child, visit, state);
  return count;
}

function validatePosition(position) {
  if (position.length < 2 || position.length > 3 || !position.every(Number.isFinite)) {
    throw new MapDataError("Each GeoJSON position needs finite longitude and latitude values.");
  }
  const [longitude, latitude] = position;
  if (longitude < -180 || longitude > 180 || latitude < -90 || latitude > 90) {
    throw new MapDataError("GeoJSON coordinates must use WGS84 longitude, latitude order.");
  }
}

function isPlainObject(value) {
  return Object.prototype.toString.call(value) === "[object Object]";
}
