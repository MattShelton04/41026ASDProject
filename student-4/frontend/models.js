export const LIST_INTRO =
  "Review available planning, environmental, strata and building evidence for a property, " +
  "and record a due-diligence disposition. Confirmed observations, non-intersections, partial " +
  "coverage and unavailable coverage are shown distinctly.";

const STATUS_LABELS = {
  draft: "Draft",
  in_review: "In review",
  completed: "Completed",
  archived: "Archived",
};

const DISPOSITION_LABELS = {
  undecided: "Undecided",
  proceed: "Proceed",
  hold: "Hold",
  do_not_proceed: "Do not proceed",
};

const EVIDENCE_STATE_LABELS = {
  confirmed: "Confirmed",
  non_intersection: "No intersection",
  partial_coverage: "Partial coverage",
  unavailable: "Unavailable",
};

// Map a review status to a shared evidence badge modifier (or "" for the neutral badge).
const STATUS_BADGE = {
  completed: "ps-badge--confirmed",
  in_review: "ps-badge--info",
  draft: "ps-badge--planned",
};

// Map an evidence state to a shared badge modifier (or "" for the neutral badge).
const EVIDENCE_STATE_BADGE = {
  confirmed: "ps-badge--confirmed",
  partial_coverage: "ps-badge--partial",
  non_intersection: "ps-badge--info",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || "Unknown";
}

export function dispositionLabel(disposition) {
  return DISPOSITION_LABELS[disposition] || "Unknown";
}

export function evidenceStateLabel(state) {
  return EVIDENCE_STATE_LABELS[state] || "Unknown";
}

export function statusBadgeClass(status) {
  return STATUS_BADGE[status] || "";
}

export function evidenceBadgeClass(state) {
  return EVIDENCE_STATE_BADGE[state] || "";
}

export function summariseReview(review) {
  return `${review.title} - ${review.address_display} (${statusLabel(review.status)})`;
}

// Turn a snake_case identifier (e.g. floor_space_ratio) into a readable label.
export function formatType(value) {
  if (!value) return "";
  const spaced = String(value).replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// Parse the location hash into a route: the list, or a review detail with its id.
export function parseRoute(hash) {
  const clean = String(hash || "").replace(/^#/, "");
  const match = clean.match(/^site-reviews\/(.+)$/);
  if (match) {
    try { return { name: "detail", id: decodeURIComponent(match[1]) }; }
    catch { return { name: "list" }; }
  }
  return { name: "list" };
}

const DEFAULT_CHECKLIST = [
  { item: "Confirm zoning permits the intended use", done: false },
  { item: "Check flood and bushfire exposure", done: false },
  { item: "Review strata and building orders", done: false },
];

// Build a create payload from raw form values, trimming text and defaulting safely.
export function buildReviewPayload(values) {
  return {
    property_ref: String(values.propertyRef || "").trim(),
    address_display: String(values.addressDisplay || "").trim(),
    title: String(values.title || "").trim(),
    status: values.status || "draft",
    disposition: values.disposition || "undecided",
    notes: String(values.notes || "").trim(),
    checklist: (Array.isArray(values.checklist) ? values.checklist : DEFAULT_CHECKLIST).map((item) => ({ ...item })),
  };
}

// Map a create/update Problem Details response to a friendly message.
export function problemMessage(problem, status) {
  const code = problem && problem.code;
  if (code === "unknown_property") return "That property is not verified in Feature 1.";
  if (code === "invalid_site_review") {
    return (problem && problem.detail) || "Please check the review details and try again.";
  }
  return `Could not save the review (status ${status}).`;
}

// Build an update payload for an existing review (property is not editable).
export function buildUpdatePayload(values) {
  return {
    title: String(values.title || "").trim(),
    status: values.status || "draft",
    disposition: values.disposition || "undecided",
    notes: String(values.notes || "").trim(),
  };
}

// Return a new checklist with one item's done-state changed (pure).
export function toggleChecklist(checklist, index, done) {
  const items = Array.isArray(checklist) ? checklist : [];
  return items.map((item, position) => (position === index ? { ...item, done } : item));
}

// Extract a clean question / verification-point list from an AI-mode final_result (pure).
// Prefers an explicit `questions` array; otherwise uses the default.v7 `findings` list
// (plus the recommended next step); otherwise pulls question-like lines from the text.
export function extractQuestions(finalResult) {
  if (!finalResult || typeof finalResult !== "object") return [];
  if (Array.isArray(finalResult.questions)) {
    const questions = finalResult.questions
      .map((q) => (typeof q === "string" ? q : q && q.question))
      .filter((q) => typeof q === "string" && q.trim())
      .map((q) => q.trim());
    if (questions.length) return questions;
  }
  if (Array.isArray(finalResult.findings)) {
    const points = finalResult.findings
      .filter((f) => typeof f === "string" && f.trim())
      .map((f) => f.trim());
    if (typeof finalResult.recommended_next_step === "string" && finalResult.recommended_next_step.trim()) {
      points.push(finalResult.recommended_next_step.trim());
    }
    if (points.length) return points;
  }
  const text = [finalResult.summary, finalResult.answer]
    .filter((value) => typeof value === "string")
    .join("\n");
  return text
    .split("\n")
    .map((line) => line.replace(/^\s*(?:\d+[.)]|[-*\u2022])\s*/, "").trim())
    .filter((line) => line.endsWith("?"));
}

// Build shared-map layer definitions from the backend /map payload (pure).
export function mapLayerDefinitions(mapData) {
  const layers = [];
  if (mapData && mapData.property) {
    layers.push({
      id: "property",
      label: "Property",
      kind: "point",
      data: mapData.property,
      popup: { title: "address", fields: [] },
    });
  }
  const hazards = Array.isArray(mapData && mapData.layers) ? mapData.layers : [];
  for (const layer of hazards) {
    layers.push({
      id: layer.id,
      label: layer.label,
      kind: "polygon",
      data: layer.data,
      popup: {
        title: "hazard",
        fields: [
          { label: "Evidence", property: "evidence_state" },
          { label: "Note", property: "summary" },
        ],
      },
    });
  }
  return layers;
}
