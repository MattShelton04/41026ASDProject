/** Whether this deployment enables the release page's review actions, read once per page load. */
// The backend reports them as `review_actions` beside its acquisition runtime capabilities.
export const REVIEW_CAPABILITIES_PATH = "runtime-capabilities";
export const REVIEW_DISABLED_DETAILS = Object.freeze({
  readiness_review: "Multi-agent review is not enabled in this deployment.",
  ai_review: "AI review is not enabled in this deployment.",
});

/**
 * One action's availability. Only an explicit `enabled: false` from the backend disables it:
 * an unreadable or missing answer keeps the action available, and its own route then reports
 * any failure as before.
 */
export function reviewCapability(capabilities, key) {
  const entry = capabilities?.[key];
  if (entry?.enabled !== false) return Object.freeze({ enabled: true, detail: "" });
  const detail = typeof entry.detail === "string" && entry.detail.trim()
    ? entry.detail.trim().slice(0, 200)
    : REVIEW_DISABLED_DETAILS[key] || "This review is not enabled in this deployment.";
  return Object.freeze({ enabled: false, detail });
}

export const REVIEW_UNAVAILABLE_IDS = Object.freeze({
  readiness_review: "readiness-review-unavailable",
  ai_review: "ai-review-unavailable",
});

/** The visible explanations for the review actions a page shows but cannot offer, in page order. */
export function unavailableReviewExplanations(capabilities, shown = ["readiness_review", "ai_review"]) {
  return shown.flatMap((key) => {
    const capability = reviewCapability(capabilities, key);
    return capability.enabled ? [] : [Object.freeze({ key, id: REVIEW_UNAVAILABLE_IDS[key], detail: capability.detail })];
  });
}

/** The answer is configuration, so it is asked once and kept; a failed read is asked again. */
export function createReviewCapabilities(request) {
  let answer = null;
  return Object.freeze({
    load() {
      if (!answer) {
        const pending = request(REVIEW_CAPABILITIES_PATH, { timeoutMs: 4000 }).then(
          ({ body }) => (body?.review_actions && typeof body.review_actions === "object" ? body.review_actions : null),
          () => {
            if (answer === pending) answer = null;
            return null;
          },
        );
        answer = pending;
      }
      return answer;
    },
  });
}

/**
 * Keep a disabled review action focusable and say why: `aria-disabled` (not `disabled`) so
 * keyboard and screen-reader users still reach it, described by the visible explanation.
 */
export function markReviewActionUnavailable(button, explanationId) {
  button.setAttribute("aria-disabled", "true");
  button.setAttribute("aria-describedby", explanationId);
  button.classList.add("is-unavailable");
  button.removeAttribute("aria-controls");
  button.removeAttribute("aria-expanded");
  return button;
}

export function reviewActionAvailable(button) {
  return button?.getAttribute("aria-disabled") !== "true";
}
