/**
 * Keep what a reader was doing when a page is rebuilt from fresh data: open disclosures, the
 * focused disclosure or the focused control inside a region that survives the rebuild (such as the
 * readiness review panel), and the scroll position.
 */

function disclosures(root, keep) {
  const counts = new Map();
  return [...root.querySelectorAll("details")]
    .filter((details) => !keep?.contains(details))
    .map((details) => {
      const label = details.querySelector("summary")?.textContent?.trim() || "";
      const count = counts.get(label) || 0;
      counts.set(label, count + 1);
      return [`${label}#${count}`, details];
    });
}

export function captureViewState(root, { keep = null, doc = globalThis.document, win = globalThis.window } = {}) {
  const active = doc?.activeElement || null;
  const entries = disclosures(root, keep);
  const focusedDisclosure = active && active.tagName === "SUMMARY"
    ? entries.find(([, details]) => details.contains(active))?.[0] || ""
    : "";
  return {
    scrollY: win?.scrollY ?? 0,
    // A surviving node keeps its identity, so it can simply be focused again after the move.
    focus: keep && active && keep.contains(active) ? active : null,
    focusedDisclosure,
    disclosures: new Map(entries.map(([key, details]) => [key, details.open])),
  };
}

export function restoreViewState(root, snapshot, { keep = null, win = globalThis.window } = {}) {
  if (!snapshot) return;
  for (const [key, details] of disclosures(root, keep)) {
    if (snapshot.disclosures.has(key)) details.open = snapshot.disclosures.get(key);
    if (key === snapshot.focusedDisclosure) details.querySelector("summary")?.focus?.({ preventScroll: true });
  }
  if (snapshot.focus?.isConnected) snapshot.focus.focus({ preventScroll: true });
  win?.scrollTo?.({ top: snapshot.scrollY, behavior: "instant" });
}
