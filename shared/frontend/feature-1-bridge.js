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
  for (const name of REQUIRED_COPY) requireString(adapter.evidence?.copy?.[name], `evidence.copy.${name}`);
  for (const section of ["published", "agentRuns"]) {
    requireString(adapter.evidence?.[section]?.path, `evidence.${section}.path`);
    requireFunction(adapter.evidence?.[section]?.project, `evidence.${section}.project`);
    requireFunction(adapter.evidence?.[section]?.href, `evidence.${section}.href`);
  }
  return adapter;
}

export async function loadFeature1Bridge({ importer, overrides = {}, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const load = importer || (() => import("/features/data-platform/integration/shell.js?v=2"));
  let timer;
  try {
    const timedOut = Symbol("feature-1-timeout");
    const module = await Promise.race([
      Promise.resolve().then(load),
      new Promise((resolve) => { timer = setTimeout(() => resolve(timedOut), timeoutMs); }),
    ]);
    if (module === timedOut) return null;
    if (typeof module?.createFeature1ShellAdapter !== "function") {
      throw new Feature1BridgeContractError("Feature 1 module must export createFeature1ShellAdapter().");
    }
    return validateFeature1Adapter(module.createFeature1ShellAdapter(overrides));
  } catch (error) {
    if (error instanceof Feature1BridgeContractError) throw error;
    return null;
  } finally {
    clearTimeout(timer);
  }
}
