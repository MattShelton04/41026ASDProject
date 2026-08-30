/** Bounded ingress from the Shared shell to Feature 1's public adapter. */

const DEFAULT_TIMEOUT_MS = 350;
const REQUIRED_COPY = Object.freeze([
  "headerDescription", "releasePanelDescription", "agentPanelDescription",
  "releaseEmpty", "releaseError", "agentEmpty", "agentError", "transitionLabel",
]);

export class Feature1BridgeContractError extends TypeError {}

function requireFunction(value, path) {
  if (typeof value !== "function") throw new Feature1BridgeContractError(`Feature 1 adapter is missing ${path}().`);
}

function requireString(value, path) {
  if (typeof value !== "string" || !value) throw new Feature1BridgeContractError(`Feature 1 adapter is missing ${path}.`);
}

export function validateFeature1Adapter(adapter) {
  if (!adapter || typeof adapter !== "object") throw new Feature1BridgeContractError("Feature 1 adapter must be an object.");
  for (const name of ["propertyDiscovery", "dataOperations", "agentRuns"]) requireString(adapter.links?.[name], `links.${name}`);
  requireFunction(adapter.primarySearchHref, "primarySearchHref");
  requireFunction(adapter.statusDependencies, "statusDependencies");
  requireString(adapter.evidence?.action?.label, "evidence.action.label");
  requireString(adapter.evidence?.action?.href, "evidence.action.href");
  for (const name of REQUIRED_COPY) requireString(adapter.evidence?.copy?.[name], `evidence.copy.${name}`);
  for (const section of ["published", "agentRuns"]) {
    requireString(adapter.evidence?.[section]?.path, `evidence.${section}.path`);
    requireFunction(adapter.evidence?.[section]?.project, `evidence.${section}.project`);
    requireFunction(adapter.evidence?.[section]?.href, `evidence.${section}.href`);
  }
  return adapter;
}

export async function loadFeature1Bridge({
  importer,
  overrides = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
  onLateAdapter,
  onError,
} = {}) {
  const load = importer || (() => import("/features/data-platform/integration/shell.js"));
  const reportError = typeof onError === "function"
    ? onError
    : (error) => console.error("Feature 1 shell adapter could not be loaded.", error);
  const createAdapter = (module) => {
    if (typeof module?.createFeature1ShellAdapter !== "function") {
      throw new Feature1BridgeContractError("Feature 1 module must export createFeature1ShellAdapter().");
    }
    return validateFeature1Adapter(module.createFeature1ShellAdapter(overrides));
  };
  let timer;
  try {
    const timedOut = Symbol("feature-1-timeout");
    const modulePromise = Promise.resolve().then(load);
    const module = await Promise.race([
      modulePromise,
      new Promise((resolve) => { timer = setTimeout(() => resolve(timedOut), timeoutMs); }),
    ]);
    if (module === timedOut) {
      const lateAdapter = modulePromise.then(createAdapter);
      if (typeof onLateAdapter === "function") {
        lateAdapter.then(onLateAdapter).catch(reportError);
      } else lateAdapter.catch(reportError);
      return null;
    }
    return createAdapter(module);
  } catch (error) {
    if (error instanceof Feature1BridgeContractError) throw error;
    reportError(error);
    return null;
  } finally {
    clearTimeout(timer);
  }
}
