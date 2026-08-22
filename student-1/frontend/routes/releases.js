import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatDate, formatNumber, humanise, isInternalAssessmentFixture, releaseComparison, researchAreaLabel } from "../core/formats.js?v=6";
import { parseJsonField } from "../core/forms.js";
import { formField, filterToolbar } from "../components/forms.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

const RELEASE_FIELDS = [
  { name: "dataset_id", label: "Dataset ID", required: true, createOnly: true },
  { name: "source_definition_id", label: "Source definition ID", required: true, createOnly: true },
  { name: "ingestion_run_id", label: "Ingestion run ID", required: true, createOnly: true },
  { name: "target_feature", label: "Research area key", required: true, createOnly: true },
  { name: "release_version", label: "Release version", required: true },
  { name: "schema_version", label: "Schema version", required: true },
  { name: "coverage", label: "Coverage evidence", type: "json", wide: true },
  { name: "record_count", label: "Record count", type: "number", min: 0, required: true },
  { name: "content_sha256", label: "Content SHA-256", required: true, wide: true, pattern: "[0-9a-f]{64}" },
  { name: "artifact_record_id", label: "Artifact record ID", required: true, createOnly: true },
  { name: "manifest", label: "Bounded manifest", type: "json", wide: true },
  { name: "review_comment", label: "Review note", type: "textarea", wide: true },
];

function hasBlockingFailures(results) {
  return results.some((item) => item.severity === "blocking" && ["fail", "failed", "error"].includes(item.status));
}

export function createReleaseRoutes({
  view, request, loading, entityDialog, entityForm, confirmAction, mutate, showToast, rerender,
}) {
  async function openReleaseDialog(item = null) {
    document.querySelector("#entity-kicker").textContent = "Dataset release";
    document.querySelector("#entity-title").textContent = `${item ? "Edit" : "Create"} draft release`;
    const fieldHost = document.querySelector("#entity-fields");
    const valueFor = (name) => name === "coverage" ? item?.coverage_json : name === "manifest" ? item?.manifest_json : item?.[name];
    fieldHost.replaceChildren(...RELEASE_FIELDS.map((definition) => formField(
      { ...definition, disabled: Boolean(item && definition.createOnly) }, valueFor(definition.name),
    )));
    document.querySelector("#entity-error").textContent = "";
    entityDialog.returnValue = "";
    entityDialog.showModal();
    entityDialog.querySelector("input:not(:disabled), select:not(:disabled), textarea:not(:disabled)")?.focus();
    const closed = new Promise((resolve) => entityDialog.addEventListener("close", () => resolve(entityDialog.returnValue), { once: true }));
    if (await closed !== "save") return;
    const data = Object.fromEntries(new FormData(entityForm));
    try {
      data.coverage = parseJsonField(data.coverage, "Coverage evidence");
      data.manifest = parseJsonField(data.manifest, "Manifest");
      data.record_count = Number(data.record_count);
      data.review_comment = data.review_comment?.trim() || null;
      if (item) data.version = item.version;
      else data.status = "draft";
      const result = await request(`dataset-releases${item ? `/${encodeURIComponent(item.id)}` : ""}`, {
        method: item ? "PUT" : "POST", body: data,
      });
      showToast(`Draft release ${item ? "updated" : "created"}. Request ID ${result.requestId}`);
      const saved = entity(result.body, "release");
      if (!item && saved?.id) location.hash = `#releases/${saved.id}`;
      else await rerender();
    } catch (error) {
      showToast(`${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`);
    }
  }

  async function renderReleases(id = "") {
    loading("Loading release evidence");
    try {
      if (id) return await renderReleaseDetail(id);
      const params = new URLSearchParams(location.hash.split("?")[1] || "");
      const filters = { q: params.get("q") || "", status: params.get("status") || "" };
      const { body } = await request(`dataset-releases${queryString({ status: filters.status, limit: 100 })}`);
      const releases = collection(body).filter((release) => !isInternalAssessmentFixture(release));
      const visible = filters.q ? releases.filter((release) => [release.dataset_id, release.release_version, release.target_feature]
        .some((value) => String(value || "").toLowerCase().includes(filters.q.toLowerCase()))) : releases;
      view.replaceChildren();
      append(view, pageHeading("Property records", "Published datasets", "Review each new dataset against the version already in use. Publication and rejection always require a recorded human decision.", [button("Create draft dataset", "button primary", () => openReleaseDialog())]));
      append(view, filterToolbar({ ...filters, statuses: ["", "draft", "candidate", "awaiting_review", "accepted", "rejected", "superseded"], placeholder: "Dataset, version or research area", onApply: (values) => { location.hash = `#releases${queryString(values)}`; rerender(); } }));
      if (!visible.length) { append(view, emptyState("No datasets found", filters.q || filters.status ? "Try clearing the current filters." : "A completed processing run can create a dataset for review.")); return; }
      append(view, panel(`${visible.length} dataset versions`, "Unpublished candidates remain separate from the version currently in use", makeTable(
        [{ label: "Dataset / version" }, { label: "Research area" }, { label: "Records" }, { label: "State" }, { label: "Published" }, { label: "Checksum" }], visible,
        (release) => { const row = el("tr"); append(row, cell(link(release.dataset_id || "Dataset", `#releases/${release.id}`), "primary-cell"), cell(researchAreaLabel(release.target_feature)), cell(formatNumber(release.record_count), "numeric"), cell(badge(release.status)), cell(formatDate(release.accepted_at)), cell(String(release.content_sha256 || "—").slice(0, 12), "mono")); return row; },
      )));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  async function renderReleaseDetail(id) {
    const { body, requestId } = await request(`dataset-releases/${id}`);
    const release = entity(body, "release");
    const receipts = body.receipts || [];
    let manifest = release.manifest_json || body.manifest;
    if (!manifest) { try { manifest = (await request(`dataset-releases/${id}/manifest`)).body; } catch { manifest = null; } }
    const [qualityResult, acceptedResult, previewResult] = await Promise.allSettled([
      request(`ingestion-runs/${release.ingestion_run_id}/quality-results?limit=100`),
      request("dataset-releases?status=accepted&limit=100"),
      request(`dataset-releases/${id}/records?limit=25&offset=0`),
    ]);
    const qualityResults = qualityResult.status === "fulfilled" ? collection(qualityResult.value.body) : [];
    const acceptedReleases = acceptedResult.status === "fulfilled" ? collection(acceptedResult.value.body) : [];
    const predecessor = acceptedReleases.find((candidate) => candidate.id === release.supersedes_release_id)
      || acceptedReleases.find((candidate) => candidate.id !== release.id && candidate.dataset_id === release.dataset_id && candidate.target_feature === release.target_feature) || null;
    const blocking = hasBlockingFailures(qualityResults);
    const actions = [];
    if (["draft", "candidate"].includes(release.status)) actions.push(button("Edit metadata", "button secondary", () => openReleaseDialog(release)));
    if (["draft", "rejected"].includes(release.status)) actions.push(button("Delete", "button danger", async () => {
      const ok = await confirmAction({ title: `Delete ${release.release_version}?`, description: "Only unreferenced draft or rejected releases can be deleted. Retained quality and receipt evidence remains protected.", label: "Delete release" });
      if (!ok) return;
      try { await mutate(`dataset-releases/${id}`, { method: "DELETE", body: undefined, success: "Release deleted" }); location.hash = "#releases"; } catch (error) { showToast(`${error.message} Request ID ${error.requestId}`); }
    }));
    if (["validated", "candidate"].includes(release.status)) actions.push(button("Submit for review", "button secondary", async () => {
      const comment = requiredReviewText("Reviewer context");
      const ok = await confirmAction({ title: "Submit candidate for review?", description: "Blocking failures cannot be bypassed. The candidate remains isolated until publication succeeds.", label: "Submit review", tone: "primary", extra: comment });
      if (ok && comment.value.trim()) { await mutate(`dataset-releases/${id}/submit-review`, { body: { version: release.version, comment: comment.value.trim() }, success: "Candidate submitted" }); rerender(); }
      else if (ok) showToast("A review comment is required.");
    }));
    if (["review", "review_required", "awaiting_review"].includes(release.status) && !blocking) actions.push(button("Publish", "button primary", async () => {
      const comment = requiredReviewText("Human approval evidence");
      const ok = await confirmAction({ title: "Publish this release?", description: "This protected action starts the idempotent consumer import handshake. The accepted predecessor stays live unless the consumer accepts this candidate.", label: "Publish release", tone: "primary", extra: comment });
      if (ok && comment.value.trim()) { await mutate(`dataset-releases/${id}/publish`, { body: { approved: true, version: release.version, comment: comment.value.trim() }, success: "Publication requested" }); rerender(); }
      else if (ok) showToast("Human approval evidence is required.");
    }));
    if (["candidate", "review", "review_required", "awaiting_review"].includes(release.status)) actions.push(button("Reject", "button danger", async () => {
      const reason = requiredReviewText("Reason for rejection");
      const ok = await confirmAction({ title: "Reject this candidate?", description: "The human decision and reason become durable evidence. Accepted data is unchanged.", label: "Reject candidate", extra: reason });
      if (ok && reason.value.trim()) { await mutate(`dataset-releases/${id}/reject`, { body: { reason: reason.value.trim(), version: release.version }, success: "Candidate rejected" }); rerender(); }
      else if (ok) showToast("A rejection reason is required.");
    }));
    actions.push(button("Diagnose evidence", "button secondary", () => { location.hash = `#ai/release:${id}`; }));

    view.replaceChildren();
    append(view, pageHeading("Dataset review", `${release.dataset_id} ${release.release_version}`, `${researchAreaLabel(release.target_feature)} · ${formatNumber(release.record_count)} records`, actions));
    if (!["accepted", "superseded"].includes(release.status)) append(view, el("div", "notice warning", "Candidate evidence is isolated. The accepted predecessor remains available until a reviewed publication handshake succeeds."));
    if (blocking) append(view, el("div", "notice negative", "Publication is blocked by deterministic quality failures. Inspect the failed checks, diagnose if useful, then reject or recover the candidate; accepted data is unaffected."));
    const layout = el("div", "detail-layout");
    const releaseBody = el("div");
    append(releaseBody, detailList([["State", badge(release.status)], ["Schema", release.schema_version], ["Records", formatNumber(release.record_count)], ["Content hash", el("code", "mono", release.content_sha256)], ["Coverage", release.coverage_json ? technicalDetails(release.coverage_json, "Inspect coverage") : "Unknown"], ["Review note", release.review_comment || "No review note recorded"], ["Created", formatDate(release.created_at)], ["Accepted", formatDate(release.accepted_at)], ["Request ID", el("code", "mono", requestId)]]), technicalDetails(release, "Inspect bounded release metadata"));
    const side = el("div", "stack");
    append(side, panel("Dataset manifest", "Files and settings needed to reproduce this version", manifest ? technicalDetails(manifest, "Inspect manifest") : el("p", "", "Manifest unavailable.")));
    const receiptBody = el("div");
    if (!receipts.length) append(receiptBody, el("p", "", "No consumer publication receipts recorded."));
    for (const receipt of receipts) append(receiptBody, detailList([["Research area", researchAreaLabel(receipt.target_feature)], ["Status", badge(receipt.status)], ["Rows accepted", formatNumber(receipt.rows_accepted)], ["Request ID", el("code", "mono", receipt.request_id || requestId)], ["Failure evidence", receipt.error_json ? technicalDetails(receipt.error_json, "Inspect failure") : "None recorded"]]));
    append(side, panel("Publication receipts", "Recorded outcomes from each destination", receiptBody));
    append(layout, panel(["accepted", "superseded"].includes(release.status) ? "Published dataset" : "Candidate dataset", "The exact version selected for review", releaseBody), side);
    append(view, layout);
    if (previewResult.status === "fulfilled") append(view, releasePreviewPanel(id, previewResult.value.body));
    else append(view, panel("Dataset preview", "Bounded release-scoped records", el("div", "notice warning", "Preview is unavailable for this release profile. Release and quality evidence remain available.")));
    append(view, renderReleaseReviewEvidence(release, predecessor, qualityResults, { qualityUnavailable: qualityResult.status === "rejected", predecessorUnavailable: acceptedResult.status === "rejected" }));
  }

  function requiredReviewText(label) {
    const field = el("label", "dialog-review-field");
    append(field, el("span", "", `${label} (required)`));
    const input = el("textarea"); input.required = true; input.maxLength = 2000; append(field, input);
    Object.defineProperty(field, "value", { get: () => input.value });
    return field;
  }

  function releasePreviewPanel(releaseId, initialPage) {
    const host = el("section", "panel"); const heading = el("div", "panel-heading"); const copy = el("div");
    append(copy, el("h2", "", "Dataset preview"), el("p", "", "Bounded rows from this exact candidate or accepted generation")); append(heading, copy);
    const body = el("div", "panel-body"); append(host, heading, body);
    const renderPage = (page) => {
      body.replaceChildren(); const release = page.release || {};
      append(body, el("div", "notice", `${humanise(release.status)} generation · ${formatNumber(page.total)} previewable ${humanise(page.profile)} records. No other release is mixed into this view.`));
      if (!page.items?.length) { append(body, emptyState("No preview rows", "This release has no rows in its registered warehouse projection.")); return; }
      const columns = page.columns || Object.keys(page.items[0]);
      append(body, makeTable(columns.map((column) => ({ label: humanise(column) })), page.items, (item) => { const row = el("tr"); columns.forEach((column, index) => { const value = previewValue(item[column]); append(row, cell(index === 0 && !(value instanceof Node) ? primaryCell(value) : value, index === 0 ? "primary-cell" : "")); }); return row; }));
      const controls = el("div", "dialog-actions"); const previous = button("Previous page", "button secondary"); const next = button("Next page", "button secondary");
      previous.disabled = page.offset <= 0; next.disabled = page.next_offset === null || page.next_offset === undefined;
      const load = async (offset, control) => { control.disabled = true; try { renderPage((await request(`dataset-releases/${releaseId}/records${queryString({ limit: page.limit || 25, offset })}`)).body); } catch (error) { body.prepend(el("div", "notice warning", `${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`)); control.disabled = false; } };
      previous.addEventListener("click", () => load(Math.max(0, page.offset - page.limit), previous)); next.addEventListener("click", () => load(page.next_offset, next));
      append(controls, el("span", "field-help", `Showing ${formatNumber(page.offset + 1)}–${formatNumber(page.offset + page.count)} of ${formatNumber(page.total)}`), previous, next); append(body, controls);
    };
    renderPage(initialPage); return host;
  }

  return { renderReleases };
}

function previewValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") { const encoded = JSON.stringify(value); return encoded.length > 80 ? technicalDetails(value, "Inspect value") : el("code", "mono", encoded); }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function renderReleaseReviewEvidence(release, predecessor, qualityResults, availability) {
  const section = el("section", "dashboard-grid"); const comparisonBody = el("div");
  if (availability.predecessorUnavailable) append(comparisonBody, el("div", "notice warning", "Accepted predecessor evidence is temporarily unavailable. No negative conclusion is inferred."));
  else if (!predecessor) append(comparisonBody, el("p", "", "No accepted predecessor exists for this dataset and research area."));
  else {
    append(comparisonBody, el("div", "notice", `Candidate ${release.release_version} is shown beside accepted predecessor ${predecessor.release_version}. The accepted generation remains available.`));
    append(comparisonBody, makeTable([{ label: "Evidence" }, { label: "Candidate" }, { label: "Accepted predecessor" }, { label: "Difference" }], releaseComparison(release, predecessor), (item) => { const row = el("tr"); const renderValue = (value) => typeof value === "object" ? JSON.stringify(value) : String(value ?? "—"); append(row, cell(item.field, "primary-cell"), cell(renderValue(item.candidate)), cell(renderValue(item.predecessor)), cell(badge(item.changed ? "changed" : "unchanged"))); return row; }));
  }
  const qualityBody = el("div");
  if (availability.qualityUnavailable) append(qualityBody, el("div", "notice warning", "Quality evidence is temporarily unavailable. No failure is inferred from this dependency state."));
  else if (!qualityResults.length) append(qualityBody, el("p", "", "No quality results are linked to this release run."));
  else append(qualityBody, makeTable([{ label: "Rule" }, { label: "Severity" }, { label: "Outcome" }, { label: "Observed / expected" }, { label: "Message" }, { label: "Sample" }], qualityResults, (item) => { const row = el("tr"); append(row, cell(primaryCell(item.rule_key, item.dimension)), cell(badge(item.severity)), cell(badge(item.status)), cell(technicalDetails({ observed: item.observed_value_json, expected: item.expected_value_json }, "Compare")), cell(item.message), cell(item.sample_json ? technicalDetails(item.sample_json, "Bounded sample") : "—")); return row; }));
  append(section, panel("Candidate and accepted predecessor", "Schema, count, checksum and coverage", comparisonBody), panel("Deterministic quality review", `${qualityResults.length} linked checks`, qualityBody));
  return section;
}
