import { reconcilePublication } from "../core/publication.js";

export function publicationSuccessMessage(body) {
  const outcome = body?.publication_status || reconcilePublication(body);
  if (outcome === "completed") return "Publication completed";
  if (outcome === "pending") return "Publication requested";
  if (outcome === "failed") {
    throw new Error("Background publication failed before the live version changed. A fresh retry is safe.");
  }
  throw new Error("The service returned an unknown publication status.");
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
    const progress = outcome === "completed" ? "completed" : "continues in the database loader";
    showToast(`Publication ${progress}. Request ID ${requestId}`);
    return body;
  }
  if (outcome === "failed") {
    publicationKeys.clear(key.identity);
    timeoutError.message = `${timeoutError.message} Background publication failed before the live version changed. A fresh retry is safe.`;
    throw timeoutError;
  }
  timeoutError.message = `${timeoutError.message} Its outcome is not known yet; retrying will reuse the same publication key.`;
  throw timeoutError;
}
