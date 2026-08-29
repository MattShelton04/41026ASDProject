import { createAssistantClient } from "./client.js?v=3";
import { createAiChat } from "./controller.js?v=3";

function required(value, name) {
  if (typeof value !== "string" || !value.trim()) {
    throw new TypeError(`createFeatureAssistant requires ${name}`);
  }
  return value.trim();
}

export function featureActivityHref({
  featureKey,
  featureLabel,
  returnTo,
  operationsPath = "/operations/ai-mode/",
} = {}) {
  const key = required(featureKey, "featureKey");
  const label = required(featureLabel, "featureLabel");
  const destination = required(returnTo, "returnTo");
  return (runId) => {
    const params = new URLSearchParams({
      feature_key: key,
      feature_label: label,
      return_to: destination,
      run: required(runId, "runId"),
    });
    return `${operationsPath}?${params}`;
  };
}

/**
 * Compose the public Shared controller for one independently owned feature adapter.
 * Feature vocabulary, context, API routes and tool policy remain backend-owned inputs.
 */
export function createFeatureAssistant({
  root,
  apiRoot,
  featureKey,
  featureLabel,
  returnTo,
  scopes,
  suggestions,
  context = {},
  contextOptions = [],
  initialScope = "feature",
  fetcher = globalThis.fetch?.bind(globalThis),
  announce = () => {},
  operationsPath = "/operations/ai-mode/",
  title = `Ask ${featureLabel || "PropertyScope"}`,
  description,
  assistantLabel = "PropertyScope assistant",
  welcomeTitle,
  welcomeMessage,
  composerLabel,
  placeholder,
} = {}) {
  if (!root) throw new TypeError("createFeatureAssistant requires root");
  const resolvedApiRoot = required(apiRoot, "apiRoot");
  if (typeof fetcher !== "function") throw new TypeError("createFeatureAssistant requires fetch");
  const client = createAssistantClient({ apiRoot: resolvedApiRoot, fetcher });
  const controller = createAiChat({
    root,
    client,
    initialScope,
    context,
    contextOptions,
    activityHref: featureActivityHref({
      featureKey,
      featureLabel,
      returnTo,
      operationsPath,
    }),
    announce,
    title,
    description,
    scopes,
    suggestions,
    assistantLabel,
    welcomeTitle,
    welcomeMessage,
    composerLabel,
    placeholder,
  });
  return Object.freeze({ client, controller });
}
