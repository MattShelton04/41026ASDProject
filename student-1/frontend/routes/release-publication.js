import { reconcilePublication } from "../core/publication.js";

export function publicationSuccessMessage(body) {
  const outcome = body?.publication_status || reconcilePublication(body);
  if (outcome === "completed") return "Publication completed";
  if (outcome === "pending") return "Publication queued";
  if (outcome === "failed") {
    throw new Error("Publication delivery or activation failed before the live version changed. A fresh retry is safe.");
  }
  throw new Error("The service returned an unknown publication status.");
}

export function consumerImportStatusPath(releaseId, operationId, suppliedPath = "") {
  if (!releaseId || !operationId) return "";
  const fixed = `/api/data-platform/v1/dataset-releases/${encodeURIComponent(releaseId)}`
    + `/consumer-imports/${encodeURIComponent(operationId)}`;
  return suppliedPath === fixed ? suppliedPath : fixed;
}

export async function reconcilePublicationTimeout({
  release, request, publicationKeys, key, showToast, timeoutError,
}) {
  let response;
  try {
    response = await request(`dataset-releases/${release.id}`);
  } catch (reconciliationError) {
    if (reconciliationError?.status !== 0) throw reconciliationError;
    timeoutError.message = `${timeoutError.message} Its outcome is not known yet; retrying will reuse the same publication key.`;
    throw timeoutError;
  }
  const { body, requestId } = response;
  const outcome = reconcilePublication(body);
  if (["completed", "pending"].includes(outcome)) {
    publicationKeys.clear(key.identity);
    const progress = outcome === "completed"
      ? "completed"
      : "continues through durable consumer delivery and accepted-version activation";
    showToast(`Publication ${progress}. Request ID ${requestId}`);
    return body;
  }
  if (outcome === "failed") {
    publicationKeys.clear(key.identity);
    timeoutError.message = `${timeoutError.message} Publication delivery or activation failed before the live version changed. A fresh retry is safe.`;
    throw timeoutError;
  }
  timeoutError.message = `${timeoutError.message} Its outcome is not known yet; retrying will reuse the same publication key.`;
  throw timeoutError;
}
