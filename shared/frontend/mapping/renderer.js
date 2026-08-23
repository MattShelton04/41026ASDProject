const VERSION = "5.24.0";
let rendererPromise;

/** Load the vendored renderer only when a feature actually creates a map. */
export function loadMapLibreRenderer({ documentRef = globalThis.document } = {}) {
  if (globalThis.maplibregl?.Map) return Promise.resolve(globalThis.maplibregl);
  if (!documentRef?.head) throw new TypeError("MapLibre needs a browser document.");
  if (rendererPromise) return rendererPromise;

  const stylesheetUrl = new URL(`./vendor/maplibre-gl.css?v=${VERSION}`, import.meta.url).href;
  const scriptUrl = new URL(`./vendor/maplibre-gl.js?v=${VERSION}`, import.meta.url).href;
  const stylesheetReady = ensureStylesheet(documentRef, stylesheetUrl);
  const scriptReady = new Promise((resolve, reject) => {
    const existing = documentRef.querySelector?.("script[data-propertyscope-maplibre]");
    const script = existing ?? documentRef.createElement("script");
    const loaded = () => {
      if (globalThis.maplibregl?.Map) resolve();
      else reject(new Error("The self-hosted MapLibre renderer did not initialise."));
    };
    const failed = () => reject(new Error("The self-hosted MapLibre renderer could not be loaded."));
    script.addEventListener("load", loaded, { once: true });
    script.addEventListener("error", failed, { once: true });
    if (!existing) {
      script.src = scriptUrl;
      script.dataset.propertyscopeMaplibre = VERSION;
      documentRef.head.append(script);
    }
  });
  rendererPromise = Promise.all([stylesheetReady, scriptReady]).then(() => globalThis.maplibregl).catch((error) => {
    rendererPromise = undefined;
    throw error;
  });
  return rendererPromise;
}

function ensureStylesheet(documentRef, href) {
  const existing = documentRef.querySelector?.("link[data-propertyscope-maplibre]");
  if (existing?.sheet) return Promise.resolve();
  const link = existing ?? documentRef.createElement("link");
  return new Promise((resolve, reject) => {
    link.addEventListener("load", resolve, { once: true });
    link.addEventListener("error", () => reject(new Error("The self-hosted MapLibre styles could not be loaded.")), {
      once: true,
    });
    if (!existing) {
      link.rel = "stylesheet";
      link.href = href;
      link.dataset.propertyscopeMaplibre = VERSION;
      documentRef.head.append(link);
    }
  });
}
