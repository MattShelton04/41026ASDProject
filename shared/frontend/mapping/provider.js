export const NEUTRAL_STYLE = Object.freeze({
  version: 8,
  name: "PropertyScope neutral fallback",
  sources: {},
  layers: [
    {
      id: "propertyscope-background",
      type: "background",
      paint: { "background-color": "#e8f0ed" },
    },
  ],
});

export function createOpenFreeMapProvider({
  styleUrl = "https://tiles.openfreemap.org/styles/liberty",
  fallbackStyle = NEUTRAL_STYLE,
} = {}) {
  return Object.freeze({
    id: "openfreemap",
    label: "OpenFreeMap",
    style: styleUrl,
    fallbackStyle,
    attributionInStyle: true,
    attribution: [
      { label: "OpenFreeMap", url: "https://openfreemap.org/" },
      { label: "OpenStreetMap contributors", url: "https://www.openstreetmap.org/copyright" },
    ],
  });
}

export function validateProvider(provider) {
  if (!provider || typeof provider.id !== "string" || !provider.id.trim()) {
    throw new TypeError("A map provider needs a stable id.");
  }
  if (!(typeof provider.style === "string" || isStyleObject(provider.style))) {
    throw new TypeError("A map provider needs a MapLibre style URL or style object.");
  }
  if (!isStyleObject(provider.fallbackStyle)) {
    throw new TypeError("A map provider needs a local MapLibre fallback style.");
  }
  if (provider.attribution !== undefined && (
    !Array.isArray(provider.attribution)
    || provider.attribution.some((item) => !item || typeof item.label !== "string" || !item.label.trim()
      || (item.url !== undefined && !isHttpUrl(item.url)))
  )) {
    throw new TypeError("Map provider attribution must contain labels and optional HTTP(S) URLs.");
  }
  return provider;
}

function isStyleObject(value) {
  return Boolean(value && typeof value === "object" && value.version === 8 && Array.isArray(value.layers));
}

function isHttpUrl(value) {
  try {
    return ["http:", "https:"].includes(new URL(value).protocol);
  } catch {
    return false;
  }
}
