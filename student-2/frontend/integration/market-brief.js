/** Feature-owned mount of the Shared multi-agent panel for one saved market case's brief. */
import { createMultiAgentClient, createMultiAgentPanel } from "../multi-agent/index.js";

export const MARKET_BRIEF_API_ROOT = "/api/market-intelligence/v1/market-briefs";
// Runs record which surface asked for them; each human decision records its own actor.
export const MARKET_BRIEF_REQUESTER = "market-intelligence-case-brief";
export const MARKET_BRIEF_CAPABILITIES_PATH = "/market-briefs/capabilities";

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The recorded run to reopen, from `#market-cases?brief={run_id}`; anything else is ignored. */
export function marketBriefRunId(hash = "") {
  const value = new URLSearchParams(String(hash).split("?")[1] || "").get("brief") || "";
  return RUN_ID.test(value) ? value.toLowerCase() : null;
}

/** Whether the address claims a brief at all, including one this page cannot use. */
export function addressClaimsMarketBrief(hash = "") {
  return new URLSearchParams(String(hash).split("?")[1] || "").has("brief");
}

/** The address for a brief, so a run stays linkable after a reload. */
export function marketBriefHash(runId = null) {
  return runId && RUN_ID.test(runId) ? `#market-cases?brief=${runId.toLowerCase()}` : "#market-cases";
}

// The latest brief started for each case, so leaving the page does not lose a running review.
// Browser storage is a per-viewer convenience only: the Multi-Agent Server stays the record.
export const MARKET_BRIEF_STORAGE_KEY = "propertyscope:market-briefs";
export const MARKET_BRIEF_MEMORY_LIMIT = 20;

function browserStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

function readMemory(storage) {
  try {
    const value = JSON.parse(storage?.getItem(MARKET_BRIEF_STORAGE_KEY) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}

function writeMemory(storage, memory) {
  try { storage?.setItem(MARKET_BRIEF_STORAGE_KEY, JSON.stringify(memory)); } catch { /* Storage is optional. */ }
}

export function rememberedMarketBrief(marketCaseId, storage = browserStorage()) {
  const value = readMemory(storage)[String(marketCaseId)];
  return typeof value === "string" && RUN_ID.test(value) ? value.toLowerCase() : null;
}

export function rememberMarketBrief(marketCaseId, runId, storage = browserStorage()) {
  if (!marketCaseId || !RUN_ID.test(String(runId || ""))) return;
  const memory = readMemory(storage);
  delete memory[marketCaseId];
  memory[marketCaseId] = String(runId).toLowerCase();
  // Insertion order is recency order; keep only the newest cases.
  writeMemory(storage, Object.fromEntries(Object.entries(memory).slice(-MARKET_BRIEF_MEMORY_LIMIT)));
}

export function forgetMarketBrief(marketCaseId, runId, storage = browserStorage()) {
  const memory = readMemory(storage);
  if (memory[marketCaseId] !== runId) return;
  delete memory[marketCaseId];
  writeMemory(storage, memory);
}

/**
 * The run to reopen for this case, checked through the feature proxy first: a run the server no
 * longer has, or one belonging to another case, is forgotten instead of opening as an error.
 * When the server cannot answer, nothing is reopened and the memory is kept for next time.
 *
 * `preferredRunId` is the one named in the address, which wins over the remembered one.
 */
export async function resumableMarketBrief(marketCaseId, { request, preferredRunId = null, storage = browserStorage() }) {
  const runId = preferredRunId || rememberedMarketBrief(marketCaseId, storage);
  if (!runId) return null;
  try {
    const body = await request(`/market-briefs/${encodeURIComponent(runId)}`);
    if (String(body?.input?.market_case_id || "").toLowerCase() === String(marketCaseId).toLowerCase()) return runId;
    forgetMarketBrief(marketCaseId, runId, storage);
    return null;
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    // The proxy answers 404 for a deleted run and for one that is not this feature's brief.
    if (error?.status === 404) forgetMarketBrief(marketCaseId, runId, storage);
    return null;
  }
}

/**
 * Whether this deployment enables market briefs, asked once before the panel is mounted.
 *
 * The Multi-Agent Server is a host process, so a Compose-only stack - CI's visual capture, and
 * the required cloud baseline with the AI tier off - has no server to reach. Mounting the panel
 * there made the page request a workflow template that could only answer 503. Asking first keeps
 * the page quiet and tells the reader why the card is empty.
 *
 * Anything other than a clear "enabled" is treated as disabled, including a deployment old
 * enough not to publish this route at all.
 */
export async function marketBriefEnabled({ request }) {
  try {
    const body = await request(`${MARKET_BRIEF_CAPABILITIES_PATH}`);
    return body?.market_brief?.enabled === true;
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return false;
  }
}

/** The case a recorded brief belongs to, so one link reopens both the case and its run. */
export async function marketBriefCaseId(runId, { request }) {
  if (!runId || !RUN_ID.test(runId)) return null;
  try {
    const body = await request(`/market-briefs/${encodeURIComponent(runId)}`);
    const caseId = String(body?.input?.market_case_id || "");
    return RUN_ID.test(caseId) ? caseId.toLowerCase() : null;
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return null;
  }
}

export const MARKET_BRIEF_LABELS = Object.freeze({
  start: "Brief this case",
  // Deciding records an answer to the agents. It never edits the case or its evidence.
  decisionSafety:
    "This records your decision. It never changes the saved case, its filters or its recorded sales.",
  outcomeSafety:
    "Recording a decision did not change the saved case. Editing the case stays a separate action on this page.",
});

/**
 * Mount the brief panel for one market case.
 *
 * A panel belongs to the case it was created for: the Release 1 case-scoping rule carries over,
 * so switching cases destroys this panel and mounts a new one rather than re-pointing it. The
 * caller owns teardown through the returned handle.
 */
export function mountMarketBrief({
  root,
  marketCaseId,
  caseName = "",
  actor = "",
  runId = null,
  announce,
  onRunChange = () => {},
  storage = browserStorage(),
} = {}) {
  if (!root) throw new TypeError("mountMarketBrief requires root");
  if (!marketCaseId) throw new TypeError("mountMarketBrief requires marketCaseId");

  const client = createMultiAgentClient({ apiRoot: MARKET_BRIEF_API_ROOT });
  const panel = createMultiAgentPanel({
    root,
    client,
    // The case is supplied by the page, so it is submitted and listed but never editable: a
    // brief must not be started for a case other than the one on screen.
    initialInput: { market_case_id: marketCaseId },
    hiddenInputs: ["market_case_id"],
    runId,
    actor,
    // Naming the case here stops the panel repeating the card's own heading, and says which
    // case the brief belongs to.
    title: caseName ? `Brief: ${caseName}` : "",
    requestedBy: MARKET_BRIEF_REQUESTER,
    labels: MARKET_BRIEF_LABELS,
    announce,
    onRunChange: (run) => {
      if (!run?.id) return;
      rememberMarketBrief(marketCaseId, run.id, storage);
      onRunChange(run);
    },
  });
  return panel;
}
