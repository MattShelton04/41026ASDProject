const ACTIVE_ACTIVATION_STATES = Object.freeze(["queued", "claimed", "running", "interrupted"]);

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
  if (release.status === "accepted" || activations.some((item) => item.status === "succeeded")) {
    return "completed";
  }
  if (activations.some((item) => ACTIVE_ACTIVATION_STATES.includes(item.status))) return "pending";
  if (activations.some((item) => item.status === "failed")) return "failed";
  return "unknown";
}
