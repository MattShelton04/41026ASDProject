import { HttpProblem, requestJsonResponse } from "./browser/index.js";

export const API_BASE = "/api/buyer-workspaces/v1";
export const MAX_PREFERENCE_ITEMS = 20;
export const MAX_PREFERENCE_TEXT_LENGTH = 100;
export const JOURNEY_STAGES = ["Shortlisted", "Inspecting", "Reviewing", "Offer Considered", "Closed"];
export const PROPERTY_PRIORITIES = ["low", "medium", "high"];

export class ApiProblem extends Error {
  constructor(status, code, detail) {
    super(detail || `Request failed with status ${status}.`);
    this.name = "ApiProblem";
    this.status = status;
    this.code = code || "request_failed";
  }
}

export function createBuyerCaseApi(fetchImpl = globalThis.fetch) {
  async function request(method, path, body, extraHeaders = {}, options = {}) {
    try {
      return (await requestJsonResponse(fetchImpl, `${API_BASE}${path}`, {
        ...options, method, headers: extraHeaders, body,
        unavailableMessage: "Buyer cases are temporarily unavailable.",
      })).body;
    } catch (error) {
      if (!(error instanceof HttpProblem)) throw error;
      const problem = new ApiProblem(error.status, error.code, error.message);
      problem.requestId = error.requestId;
      problem.cause = error;
      throw problem;
    }
  }

  function childApi(resource) {
    return {
      list: (caseId, options = {}) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}?page=1&page_size=100`, undefined, {}, options),
      create: (caseId, values) => request("POST", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}`, values),
      read: (caseId, childId) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}/${encodeURIComponent(childId)}`),
      update: (caseId, childId, values) => request("PUT", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}/${encodeURIComponent(childId)}`, values),
      delete: (caseId, childId) => request("DELETE", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}/${encodeURIComponent(childId)}`),
    };
  }

  return {
    list: (page = 1, pageSize = 100, options = {}) => request("GET", `/buyer-cases?page=${page}&page_size=${pageSize}`, undefined, {}, options),
    create: (values) => request("POST", "/buyer-cases", values),
    read: (caseId, options = {}) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}`, undefined, {}, options),
    update: (caseId, values) => request("PUT", `/buyer-cases/${encodeURIComponent(caseId)}`, values),
    delete: (caseId) => request("DELETE", `/buyer-cases/${encodeURIComponent(caseId)}`),
    properties: childApi("properties"),
    notes: childApi("notes"),
    tasks: childApi("tasks"),
    evidence: (caseId, options = {}) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}/evidence`, undefined, {}, options),
    summaries: {
      create: (caseId, idempotencyKey) => request(
        "POST",
        `/buyer-cases/${encodeURIComponent(caseId)}/case-summary-runs`,
        {},
        { "Idempotency-Key": idempotencyKey },
      ),
      read: (caseId, runId, options = {}) => request(
        "GET",
        `/buyer-cases/${encodeURIComponent(caseId)}/case-summary-runs/${encodeURIComponent(runId)}`,
        undefined, {}, options,
      ),
    },
  };
}
