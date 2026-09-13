/** Feature-owned review intent and projection of durable runs into Shared chat. */
import { createAssistantClient, normalizeTurnDetail } from "../ai-chat/index.js";
import { FEATURE_ASSISTANT_CONTEXTS } from "./assistant.js";

export const REVIEW_OBJECTIVES = Object.freeze({
  compare: "Compare this dataset with the current published version. Check schema, record count, coverage, quality and publishing differences. Make clear when information is missing. Recommend one next step for human review. Do not publish or change data.",
  quality: "Review this dataset and its exact data update. Explain each required or failed data check and its impact. Make clear when information is missing. Recommend one retry option for human review. Do not execute it.",
  consumer: "Review this dataset, its publishing records and the current published version. Explain each failed or retryable delivery. Make clear when a receipt is missing. Recommend one next step for human review. Do not publish or change data.",
});

export const REVIEW_SUGGESTIONS = Object.freeze([
  "Compare this dataset with the current published version.",
  "Explain this dataset’s failed data checks and the next step.",
  "Explain this dataset’s publishing and delivery failures.",
]);

export function releaseReviewContext(release) {
  return {
    route: "releases/detail", release_id: release.id,
    display_label: `${release.dataset_id} · ${release.release_version} · ${release.status}`.slice(0, 200),
  };
}

export function reviewContextOptions(releases = []) {
  return [
    ...releases.filter((release) => !["accepted", "superseded", "draft"].includes(release.status)).map((release) => {
      const context = releaseReviewContext(release);
      return { id: release.id, label: context.display_label, context };
    }),
    { ...FEATURE_ASSISTANT_CONTEXTS.find((item) => item.id === "release"), label: "Find another dataset release" },
  ];
}

export function recordedReviewTurn(payload) {
  const run = normalizeTurnDetail(payload);
  const objective = String(run.objective || run.objective_preview || "Review this dataset.");
  const question = objective.match(/^Current user question: (.+)$/m);
  let message = objective.replace(/^release_id: [^.]+\. predecessor_release_id: [^.]+\. Use only these exact identifiers; never send placeholders to tools\.\s*/, "");
  if (question) {
    try { const parsed = JSON.parse(question[1]); if (typeof parsed === "string") message = parsed; } catch { /* Retain the recorded objective when the old envelope differs. */ }
  }
  const contexts = { release_id: ["releases/detail", "release_id"], run_id: ["runs/detail", "ingestion_run_id"], property_ref: ["properties/detail", "property_ref"] };
  const identifier = run.trusted_identifiers?.find((item) => Object.hasOwn(contexts, item.kind));
  const [route, parameter] = identifier ? contexts[identifier.kind] : [];
  const context = identifier ? { route, [parameter]: identifier.value } : {};
  // Legacy diagnosis runs have no assistant allowlist and cannot use its cancel endpoint.
  return { run, message: message.slice(0, 2000), context, canCancel: Array.isArray(run.tool_allowlist) };
}

export function createReviewClient({ request, recordedTurn = null, onCreated = () => {}, client = createAssistantClient({ apiRoot: "/api/data-platform/v1/assistant" }) }) {
  const recordedId = recordedTurn?.run.id;
  return {
    ...client,
    async createTurn(turn) {
      const result = await client.createTurn(turn);
      onCreated(normalizeTurnDetail(result.body));
      return result;
    },
    getTurn: (id) => id === recordedId ? request(`agent-runs/${encodeURIComponent(id)}`) : client.getTurn(id),
    getEvents: (id, after = 0) => id === recordedId
      ? request(`agent-runs/${encodeURIComponent(id)}/events?after=${after}&limit=100`) : client.getEvents(id, after),
  };
}
