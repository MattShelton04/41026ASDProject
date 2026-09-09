const NOTIFY_STATES = new Set(["succeeded", "failed", "interrupted", "cancelled", "published", "delivered", "rejected"]);

export function reconcileNotifications(previous, runs, now = Date.now()) {
  const state = previous || { seen: {}, items: [], checkedAt: null };
  const seen = { ...state.seen };
  const items = [...(state.items || [])];
  const added = [];
  for (const run of runs) {
    const key = `${run.id}:${run.status}:${run.finished_at || ""}`;
    const prior = seen[run.id];
    const newlyRequested = new Date(run.activity_at || run.requested_at).valueOf() >= Number(state.checkedAt);
    if (state.checkedAt !== null && NOTIFY_STATES.has(run.status) && prior !== key && (prior || newlyRequested)) {
      if (!items.some((item) => item.key === key)) {
        const item = { key, runId: run.target_id || run.id, kind: run.kind || "run", status: run.status, name: run.source_name || run.job_name || "Data update", at: now, read: false };
        items.unshift(item); added.push(item);
      }
    }
    delete seen[run.id];
    seen[run.id] = key;
  }
  return { state: { seen: Object.fromEntries(Object.entries(seen).slice(-200)), items: items.slice(0, 50), checkedAt: now }, added };
}

export function notificationTitle(item) {
  const outcome = { succeeded: "candidate ready", failed: "failed", interrupted: "needs recovery", cancelled: "cancelled", published: "published", delivered: "downstream import accepted", rejected: "rejected" }[item.status] || item.status;
  return `${item.name}: ${item.kind === "delivery" && item.status !== "delivered" ? "downstream delivery " : ""}${outcome}`;
}

export function notificationLink(item) {
  return `#${["publication", "delivery"].includes(item.kind) ? "releases" : "runs"}/${encodeURIComponent(item.runId)}`;
}
