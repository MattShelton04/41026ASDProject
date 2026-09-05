const ACTIVE_ACTIVATION_STATES = Object.freeze(["queued", "claimed", "running", "interrupted"]);
const ACTIVE_CONSUMER_IMPORT_STATES = Object.freeze([
  "queued", "claimed", "polling", "receipt_pending", "activation_pending", "interrupted",
  "activation_queued",
]);
const FAILED_CONSUMER_IMPORT_STATES = Object.freeze(["failed", "rejected"]);

export const PUBLICATION_POLL_LIMIT = 60;

export function publicationDisplayState(release, outcome) {
  if (release.status === "accepted") return "published";
  if (outcome === "pending") return "publishing";
  if (outcome === "failed" && release.status === "awaiting_review") return "publication_failed";
  return release.status;
}

export function publicationIdentity(release) {
  return `${release.id}:v${release.version}`;
}

export function createPublicationAttemptKeys(generateKey) {
  const keys = new Map();
  return {
    acquire(release) {
      const identity = publicationIdentity(release);
      if (!keys.has(identity)) keys.set(identity, `publish-${identity}-${generateKey()}`);
      return { identity, value: keys.get(identity) };
    },
    clear(releaseOrIdentity) {
      const identity = typeof releaseOrIdentity === "string"
        ? releaseOrIdentity
        : publicationIdentity(releaseOrIdentity);
      keys.delete(identity);
    },
  };
}

export function reconcilePublication(body) {
  const release = body?.release || body?.item || {};
  const activations = Array.isArray(body?.activations)
    ? body.activations
    : (body?.activation ? [body.activation] : []);
  const consumerImports = Array.isArray(body?.consumer_imports)
    ? body.consumer_imports
    : (body?.consumer_import ? [body.consumer_import] : []);
  const activation = activations.at(-1) || null;
  const consumerImport = consumerImports.at(-1) || null;
  if (body?.publication_status === "completed"
    || release.status === "accepted"
    || activation?.status === "succeeded") {
    return "completed";
  }
  if (ACTIVE_ACTIVATION_STATES.includes(activation?.status)
    || ACTIVE_CONSUMER_IMPORT_STATES.includes(consumerImport?.status)) {
    return "pending";
  }
  if (body?.publication_status === "failed"
    || activation?.status === "failed"
    || FAILED_CONSUMER_IMPORT_STATES.includes(consumerImport?.status)) {
    return "failed";
  }
  if (body?.publication_status === "pending") return "pending";
  return "unknown";
}

export function activePublicationOperation(body) {
  const operations = Array.isArray(body?.consumer_imports)
    ? body.consumer_imports
    : (body?.consumer_import ? [body.consumer_import] : []);
  const latest = operations.at(-1) || null;
  return ACTIVE_CONSUMER_IMPORT_STATES.includes(latest?.status) ? latest : null;
}

export function nextPublicationPollDelay(attempt, outcome, { visible = true } = {}) {
  if (outcome !== "pending" || !visible) return null;
  if (attempt >= PUBLICATION_POLL_LIMIT) return 30000;
  return Math.min(1500 * (2 ** Math.floor(Math.max(0, attempt) / 6)), 10000);
}
