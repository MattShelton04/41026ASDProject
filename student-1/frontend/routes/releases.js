import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { displayName, formatDate, formatNumber, humanise, releaseComparison, researchAreaLabel } from "../core/formats.js?v=17";
import { FieldValidationError, parseIntegerField, parseJsonField } from "../core/forms.js";
import { runDialogForm } from "../components/dialogs.js";
import { formField, filterToolbar } from "../components/forms.js?v=17";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js?v=17";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

const RELEASE_FIELDS = [
  { name: "dataset_id", label: "Dataset ID", required: true, createOnly: true },
  { name: "source_definition_id", label: "Source definition ID", required: true, createOnly: true },
  { name: "ingestion_run_id", label: "Ingestion run ID", required: true, createOnly: true },
  { name: "target_feature", label: "Research area key", required: true, createOnly: true },
  { name: "release_version", label: "Release version", required: true, maxLength: 100 },
  { name: "schema_version", label: "Schema version", required: true },
  { name: "coverage", label: "Coverage evidence", type: "json", wide: true },
  { name: "record_count", label: "Record count", type: "number", min: 0, required: true },
  { name: "content_sha256", label: "Content SHA-256", required: true, wide: true, pattern: "[0-9a-f]{64}", help: "Exactly 64 lowercase hexadecimal characters." },
  { name: "artifact_record_id", label: "Artifact record ID", required: true, createOnly: true },
  { name: "manifest", label: "Dataset manifest", type: "json", wide: true },
  { name: "review_comment", label: "Review note", type: "textarea", wide: true, maxLength: 2000, help: "Up to 2,000 characters; optional until this version is submitted for review." },
];

function hasBlockingFailures(results) {
  return results.some((item) => item.severity === "blocking" && ["fail", "failed", "error"].includes(item.status));
}

export function createReleaseRoutes({
  view, request, loading, entityDialog, entityForm, confirmAction, confirmDiscard, mutate, showToast, rerender,
}) {
  async function openReleaseDialog(item = null) {
    document.querySelector("#entity-kicker").textContent = "Dataset release";
    document.querySelector("#entity-title").textContent = `${item ? "Edit" : "Create"} draft release`;
    const fieldHost = document.querySelector("#entity-fields");
    const valueFor = (name) => name === "coverage" ? item?.coverage_json : name === "manifest" ? item?.manifest_json : item?.[name];
    fieldHost.replaceChildren(...RELEASE_FIELDS.map((definition) => formField(
      { ...definition, disabled: Boolean(item && definition.createOnly) }, valueFor(definition.name),
    )));
    let savedRelease = null;
    const saved = await runDialogForm({
      dialog: entityDialog,
      form: entityForm,
      submitButton: document.querySelector("#entity-save"),
      errorHost: document.querySelector("#entity-error"),
      acceptedValue: "save",
      progressLabel: item ? "Saving metadata…" : "Creating draft…",
      discardMessage: "Discard your unsaved draft release changes?",
      confirmDiscard,
      onSubmit: async () => {
        const data = Object.fromEntries(new FormData(entityForm));
        data.coverage = parseJsonField(data.coverage, "Coverage evidence", "coverage");
        data.manifest = parseJsonField(data.manifest, "Dataset manifest", "manifest");
        data.record_count = parseIntegerField(data.record_count, "Record count", { fieldName: "record_count", minimum: 0 });
        data.review_comment = data.review_comment?.trim() || null;
        if (item) data.version = item.version;
        else data.status = "draft";
        const result = await request(`dataset-releases${item ? `/${encodeURIComponent(item.id)}` : ""}`, {
          method: item ? "PUT" : "POST", body: data,
        });
        savedRelease = entity(result.body, "release");
        showToast(`Draft release ${item ? "updated" : "created"}. Request ID ${result.requestId}`);
      },
    });
    if (!saved) return;
    if (!item && savedRelease?.id) location.hash = `#releases/${savedRelease.id}`;
    else await rerender();
  }

  async function renderReleases(id = "") {
    loading("Loading release evidence");
    try {
      if (id) return await renderReleaseDetail(id);
      const params = new URLSearchParams(location.hash.split("?")[1] || "");
      const filters = { q: params.get("q") || "", status: params.get("status") || "" };
      const { body } = await request(`dataset-releases${queryString({ status: filters.status, limit: 100 })}`);
      const releases = collection(body);
      const visible = filters.q ? releases.filter((release) => [release.dataset_id, release.release_version, release.target_feature]
        .some((value) => String(value || "").toLowerCase().includes(filters.q.toLowerCase()))) : releases;
      view.replaceChildren();
      append(view, pageHeading("Property data", "Published data", "Review new data before it replaces the version currently used in property research.", [button("Create draft version", "button primary", () => openReleaseDialog())]));
      append(view, filterToolbar({ search: filters.q, status: filters.status, statuses: ["", "draft", "candidate", "awaiting_review", "accepted", "rejected", "superseded"], placeholder: "Dataset, version or research area", onApply: (values) => { location.hash = `#releases${queryString(values)}`; } }));
      if (!visible.length) { append(view, emptyState("No datasets found", filters.q || filters.status ? "Try clearing the current filters." : "A completed processing run can create a dataset for review.")); return; }
      append(view, panel(`${visible.length} data versions`, "New versions stay separate until they are reviewed and published", makeTable(
        [{ label: "Dataset / version" }, { label: "Research area" }, { label: "Records" }, { label: "State" }, { label: "Published" }, { label: "Checksum" }], visible,
        (release) => { const row = el("tr"); append(row, cell(link(displayName(release.dataset_id || "Dataset"), `#releases/${release.id}`), "primary-cell"), cell(researchAreaLabel(release.target_feature)), cell(formatNumber(release.record_count), "numeric"), cell(badge(release.status)), cell(formatDate(release.accepted_at)), cell(String(release.content_sha256 || "—").slice(0, 12), "mono")); return row; },
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
      const ok = await confirmAction({
        title: `Delete ${release.release_version}?`,
        description: "Only unused draft or rejected versions can be deleted. Existing checks and publishing records are kept.",
        label: "Delete version",
        progressLabel: "Deleting…",
        onConfirm: () => mutate(`dataset-releases/${id}`, { method: "DELETE", body: undefined, success: "Release deleted" }),
      });
      if (!ok) return;
      location.hash = "#releases";
    }));
    if (["validated", "candidate"].includes(release.status)) actions.push(button("Submit for review", "button secondary", async () => {
      const comment = requiredReviewText("Reviewer context");
      const ok = await confirmAction({
        title: "Submit this version for review?",
        description: "Failed required checks cannot be bypassed. This version stays separate until it is published.",
        label: "Submit for review",
        tone: "primary",
        extra: comment,
        progressLabel: "Submitting…",
        discardMessage: "Discard your reviewer context?",
        onConfirm: () => mutate(`dataset-releases/${id}/submit-review`, { body: { version: release.version, comment: requiredReviewValue(comment, "Reviewer context") }, success: "Candidate submitted" }),
      });
      if (ok) rerender();
    }));
    if (["review", "review_required", "awaiting_review"].includes(release.status) && !blocking) actions.push(button("Publish", "button primary", async () => {
      const comment = requiredReviewText("Approval note");
      const ok = await confirmAction({
        title: "Publish this version?",
        description: "Publishing sends this version to its destination. The current version stays in use unless the new version is published successfully.",
        label: "Publish version",
        tone: "primary",
        extra: comment,
        progressLabel: "Publishing…",
        discardMessage: "Discard your approval note?",
        onConfirm: () => mutate(`dataset-releases/${id}/publish`, { body: { approved: true, version: release.version, comment: requiredReviewValue(comment, "Approval note") }, success: "Publication requested" }),
      });
      if (ok) rerender();
    }));
    if (["candidate", "review", "review_required", "awaiting_review"].includes(release.status)) actions.push(button("Reject", "button danger", async () => {
      const reason = requiredReviewText("Reason for rejection");
      const ok = await confirmAction({
        title: "Reject this version?",
        description: "The reason is recorded with the review. The current published data does not change.",
        label: "Reject version",
        extra: reason,
        progressLabel: "Rejecting…",
        discardMessage: "Discard your rejection reason?",
        onConfirm: () => mutate(`dataset-releases/${id}/reject`, { body: { reason: requiredReviewValue(reason, "Reason for rejection"), version: release.version }, success: "Candidate rejected" }),
      });
      if (ok) rerender();
    }));
    actions.push(button("Review with AI", "button secondary", () => { location.hash = `#ai/release:${id}`; }));

    view.replaceChildren();
    append(view, pageHeading("Dataset review", `${displayName(release.dataset_id)} ${release.release_version}`, `${researchAreaLabel(release.target_feature)} · ${formatNumber(release.record_count)} records`, actions));
    if (!["accepted", "superseded"].includes(release.status)) append(view, el("div", "notice warning", "This version is not published. The current published version remains in use while you review it."));
    if (blocking) append(view, el("div", "notice negative", "Required data checks failed, so this version cannot be published. Review the failures, then retry or reject it."));
    const layout = el("div", "detail-layout");
    const releaseBody = el("div");
    append(releaseBody, detailList([["State", badge(release.status)], ["Schema", release.schema_version], ["Records", formatNumber(release.record_count)], ["Content hash", el("code", "mono", release.content_sha256)], ["Coverage", release.coverage_json ? technicalDetails(release.coverage_json, "Inspect coverage") : "Unknown"], ["Review note", release.review_comment || "No review note recorded"], ["Created", formatDate(release.created_at)], ["Published", formatDate(release.accepted_at)], ["Request ID", el("code", "mono", requestId)]]), technicalDetails(release, "Inspect version metadata"));
    const side = el("div", "stack");
    append(side, panel("Dataset manifest", "Files and settings needed to reproduce this version", manifest ? technicalDetails(manifest, "Inspect manifest") : el("p", "", "Manifest unavailable.")));
    const receiptBody = el("div");
    if (!receipts.length) append(receiptBody, el("p", "", "No consumer publication receipts recorded."));
    for (const receipt of receipts) append(receiptBody, detailList([["Research area", researchAreaLabel(receipt.target_feature)], ["Status", badge(receipt.status)], ["Rows received", formatNumber(receipt.rows_accepted)], ["Request ID", el("code", "mono", receipt.request_id || requestId)], ["Failure details", receipt.error_json ? technicalDetails(receipt.error_json, "Inspect failure") : "None recorded"]]));
    append(side, panel("Publication receipts", "Recorded outcomes from each destination", receiptBody));
    append(layout, panel(["accepted", "superseded"].includes(release.status) ? "Published dataset" : "Version under review", "The exact version selected for review", releaseBody), side);
    append(view, layout);
    if (previewResult.status === "fulfilled") append(view, releasePreviewPanel(id, previewResult.value.body));
    else append(view, panel("Dataset preview", "Records in this version", el("div", "notice warning", "A record preview is unavailable for this dataset. Version details and data checks remain available.")));
    append(view, renderReleaseReviewEvidence(release, predecessor, qualityResults, { qualityUnavailable: qualityResult.status === "rejected", predecessorUnavailable: acceptedResult.status === "rejected" }));
  }

  function requiredReviewText(label) {
    const field = el("label", "dialog-review-field");
    append(field, el("span", "", `${label} (required)`));
    const input = el("textarea"); input.id = "review-comment"; input.name = "review_comment"; input.required = true; input.maxLength = 2000; input.placeholder = "Record the evidence and next step for this decision"; append(field, input, el("small", "field-help", "Required · up to 2,000 characters. This note is recorded with the review decision."));
    Object.defineProperty(field, "value", { get: () => input.value });
    return field;
  }

  function requiredReviewValue(field, label) {
    const value = field.value.trim();
    if (!value) throw new FieldValidationError("review_comment", `${label} must include text, not only spaces.`, (candidate) => Boolean(String(candidate || "").trim()));
    return value;
  }

  function releasePreviewPanel(releaseId, initialPage) {
    const host = el("section", "panel"); const heading = el("div", "panel-heading"); const copy = el("div");
    append(copy, el("h2", "", "Dataset preview"), el("p", "", "Rows from this version only")); append(heading, copy);
    const body = el("div", "panel-body"); append(host, heading, body);
    const renderPage = (page) => {
      body.replaceChildren(); const release = page.release || {};
      append(body, el("div", "notice", `${humanise(release.status)} version · ${formatNumber(page.total)} previewable ${humanise(page.profile)} records. No other version is included.`));
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
  if (availability.predecessorUnavailable) append(comparisonBody, el("div", "notice warning", "The current published version is temporarily unavailable for comparison."));
  else if (!predecessor) append(comparisonBody, el("p", "", "There is no previously published version for this dataset and research area."));
  else {
    append(comparisonBody, el("div", "notice", `New version ${release.release_version} is shown beside published version ${predecessor.release_version}.`));
    append(comparisonBody, makeTable([{ label: "Check" }, { label: "New version" }, { label: "Published version" }, { label: "Difference" }], releaseComparison(release, predecessor), (item) => { const row = el("tr"); const renderValue = (value) => typeof value === "object" ? JSON.stringify(value) : String(value ?? "—"); append(row, cell(item.field, "primary-cell"), cell(renderValue(item.candidate)), cell(renderValue(item.predecessor)), cell(badge(item.changed ? "changed" : "unchanged"))); return row; }));
  }
  const qualityBody = el("div");
  if (availability.qualityUnavailable) append(qualityBody, el("div", "notice warning", "Data checks are temporarily unavailable."));
  else if (!qualityResults.length) append(qualityBody, el("p", "", "No quality results are linked to this release run."));
  else append(qualityBody, makeTable([{ label: "Rule" }, { label: "Severity" }, { label: "Outcome" }, { label: "Observed / expected" }, { label: "Message" }, { label: "Sample" }], qualityResults, (item) => { const row = el("tr"); append(row, cell(primaryCell(item.rule_key, item.dimension)), cell(badge(item.severity)), cell(badge(item.status)), cell(technicalDetails({ observed: item.observed_value_json, expected: item.expected_value_json }, "Compare")), cell(item.message), cell(item.sample_json ? technicalDetails(item.sample_json, "View sample") : "—")); return row; }));
  append(section, panel("New and published versions", "Schema, count, checksum and coverage", comparisonBody), panel("Data checks", `${qualityResults.length} linked checks`, qualityBody));
  return section;
}
