import { collection, entity, newRequestId, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { displayName, formatDate, formatNumber, humanise, releaseComparison, researchAreaLabel } from "../core/formats.js?v=49";
import { FieldValidationError, parseIntegerField, parseJsonField } from "../core/forms.js";
import {
  activePublicationOperation,
  createPublicationAttemptKeys,
  nextPublicationPollDelay,
  PUBLICATION_POLL_LIMIT,
  publicationDisplayState,
  reconcilePublication,
} from "../core/publication.js?v=48";
import {
  consumerImportStatusPath,
  publicationSuccessMessage,
  reconcilePublicationTimeout,
} from "./release-publication.js?v=48";
import { runDialogForm } from "../components/dialogs.js";
import { formField, filterToolbar } from "../components/forms.js";
import { badge, detailList, disclosurePanel, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState } from "../components/states.js";
import { cell, makeTable, primaryCell, technicalReference } from "../components/tables.js";
import { disposeTableRegions } from "../browser/index.js";
import { createLatestRequestGuard } from "../core/polling.js";
import { releasePreviewPanel } from "./release-preview.js?v=46";
import { collectionPagination, pageOffset } from "../components/pagination.js";

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

export function releaseLifecycleContext(status) {
  if (["accepted", "published"].includes(status)) return { tone: "positive", message: "This is the published version currently available from the data platform." };
  if (status === "publishing") return { tone: "info", message: "Approval recorded. Publication is running in the background. The previous published version stays in use until this version is ready." };
  if (status === "publication_failed") return { tone: "negative", message: "Approval was recorded, but publication failed. The previous published version remains in use. Inspect the failure below, then retry publication." };
  if (status === "superseded") return { tone: "warning", message: "This published version has been replaced by a newer accepted version and remains available as history." };
  if (status === "rejected") return { tone: "negative", message: "This version was rejected and is not published. The current published version remains in use." };
  if (["review", "review_required", "awaiting_review"].includes(status)) return { tone: "warning", message: "This version is awaiting human review and is not yet published. The current published version remains in use." };
  if (["validated", "candidate"].includes(status)) return { tone: "warning", message: "This version is ready for review but is not published. The current published version remains in use." };
  return { tone: "", message: "This draft version is not published. The current published version remains in use while it is prepared." };
}

function hasBlockingFailures(results) {
  return results.some((item) => item.severity === "blocking" && ["fail", "failed", "error"].includes(item.status));
}

const RELEASE_STATES = Object.freeze([
  { key: "all", label: "All" },
  { key: "review", label: "Needs review" },
  { key: "published", label: "Published" },
  { key: "rejected", label: "Rejected" },
]);

function releaseStateTabs(selected, filters) {
  const navigation = el("nav", "state-tabs");
  navigation.setAttribute("aria-label", "Published data lifecycle");
  for (const state of RELEASE_STATES) {
    const tab = link("", `#releases${queryString({ q: filters.q, status: filters.status, state: state.key === "all" ? "" : state.key })}`, "state-tab");
    append(tab, el("span", "", state.label));
    if (selected === state.key) tab.setAttribute("aria-current", "page");
    append(navigation, tab);
  }
  return navigation;
}

export function createReleaseRoutes({
  view, request, loading, entityDialog, entityForm, confirmAction, confirmDiscard, mutate, showToast, generationGuard, rerender,
}) {
  const publicationKeys = createPublicationAttemptKeys(newRequestId);
  const detailRequests = createLatestRequestGuard();
  const publicationStatusPaths = new Map();
  let evidenceCache = null;
  let refreshReleaseList = null;
  let releaseListTimer = null;
  const publicationPolling = {
    timer: null, attempts: 0, releaseId: "", statusPath: "", routeEpoch: null, outcome: "unknown",
  };

  function stopPublicationPolling({ reset = false } = {}) {
    clearTimeout(publicationPolling.timer);
    publicationPolling.timer = null;
    if (reset) {
      publicationPolling.attempts = 0;
      publicationPolling.releaseId = "";
      publicationPolling.statusPath = "";
      publicationPolling.routeEpoch = null;
      publicationPolling.outcome = "unknown";
    }
  }

  async function refreshPublicationStatus() {
    const { releaseId, statusPath, routeEpoch } = publicationPolling;
    if (!releaseId || !routeEpoch?.isCurrent() || document.hidden) return;
    publicationPolling.timer = null;
    try {
      if (statusPath) {
        const { body } = await request(statusPath);
        if (!routeEpoch.isCurrent()) return;
        publicationPolling.outcome = reconcilePublication(body);
      }
      publicationPolling.attempts += 1;
      if (!routeEpoch.isCurrent()) return;
      await renderReleaseDetail(releaseId, routeEpoch, { polling: true });
    } catch (error) {
      if (error?.name === "AbortError" || !routeEpoch.isCurrent()) return;
      publicationPolling.attempts += 1;
      schedulePublicationPoll(releaseId, statusPath, routeEpoch, "pending");
    }
  }

  function schedulePublicationPoll(releaseId, statusPath, routeEpoch, outcome) {
    stopPublicationPolling();
    publicationPolling.releaseId = releaseId;
    publicationPolling.statusPath = statusPath;
    publicationPolling.routeEpoch = routeEpoch;
    publicationPolling.outcome = outcome;
    const delay = nextPublicationPollDelay(
      publicationPolling.attempts,
      outcome,
      { visible: !document.hidden },
    );
    if (delay === null) return;
    publicationPolling.timer = setTimeout(refreshPublicationStatus, delay);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    if (refreshReleaseList) { refreshReleaseList(); return; }
    if (!publicationPolling.routeEpoch?.isCurrent()) return;
    stopPublicationPolling();
    refreshPublicationStatus();
  });

  async function publishReviewedRelease(release, comment) {
    const key = publicationKeys.acquire(release);
    try {
      const { body, requestId } = await request(`dataset-releases/${release.id}/publish`, {
        method: "POST",
        body: { approved: true, version: release.version, comment },
        headers: { "Idempotency-Key": key.value },
      });
      showToast(`${publicationSuccessMessage(body)}. Request ID ${requestId}`);
      const operation = body?.consumer_import;
      if (operation?.id && reconcilePublication(body) === "pending") {
        publicationStatusPaths.set(
          release.id,
          consumerImportStatusPath(release.id, operation.id, body.status_path),
        );
      }
      publicationKeys.clear(key.identity);
      return body;
    } catch (error) {
      if (error?.status !== 0 || !String(error?.message || "").includes("timed out")) {
        publicationKeys.clear(key.identity);
        throw error;
      }
      return reconcilePublicationTimeout({
        release, request, publicationKeys, key, showToast, timeoutError: error,
      });
    }
  }

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
    clearTimeout(releaseListTimer);
    refreshReleaseList = null;
    stopPublicationPolling({ reset: true });
    const routeEpoch = generationGuard.capture();
    loading("Loading release evidence");
    try {
      if (id) return await renderReleaseDetail(id, routeEpoch);
      const params = new URLSearchParams(location.hash.split("?")[1] || "");
      const requestedState = params.get("state") || "all";
      const selectedState = RELEASE_STATES.some((state) => state.key === requestedState) ? requestedState : "all";
      const filters = { q: params.get("q") || "", status: params.get("status") || "" };
      const offset = pageOffset(params);
      const listPath = `dataset-releases${queryString({ ...filters, lifecycle: selectedState, view: "summary", limit: 100, offset })}`;
      const { body } = await request(listPath);
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren();
      append(view, pageHeading("Property data", "Published data", "Review new data before it replaces the version currently used in property research.", [button("Create draft version", "button primary", () => openReleaseDialog())]));
      append(view, releaseStateTabs(selectedState, filters));
      append(view, filterToolbar({ search: filters.q, status: filters.status, statuses: ["", "draft", "candidate", "awaiting_review", "accepted", "rejected", "superseded"], placeholder: "Dataset, version or research area", onApply: (values) => { location.hash = `#releases${queryString({ ...values, state: selectedState === "all" ? "" : selectedState })}`; } }));
      const resultsHost = el("div", "stack");
      append(view, resultsHost);
      function renderResults(payload) {
        const visible = collection(payload);
        const activeLink = resultsHost.contains(document.activeElement) ? document.activeElement.getAttribute("href") : null;
        const scrollY = window.scrollY;
        disposeTableRegions(resultsHost);
        resultsHost.replaceChildren();
        append(resultsHost, collectionPagination("releases", { ...filters, state: selectedState }, payload, offset));
        if (!visible.length) { append(resultsHost, emptyState("No datasets found", filters.q || filters.status ? "Try clearing the current filters." : "A completed processing run can create a dataset for review.")); return; }
        append(resultsHost, panel(`${visible.length} ${visible.length === 1 ? "data version" : "data versions"}`, "New versions stay separate until they are reviewed and published", makeTable(
          [{ label: "Dataset / version" }, { label: "Research area" }, { label: "Records" }, { label: "State" }, { label: "Published" }, { label: "Checksum" }], visible,
          (release) => { const row = el("tr"); const releaseLink = link(displayName(release.dataset_id || "Dataset"), `#releases/${release.id}`); append(row, cell(primaryCell(releaseLink, release.release_version || "Version not recorded"), "primary-cell"), cell(researchAreaLabel(release.target_feature)), cell(formatNumber(release.record_count), "numeric"), cell(badge(publicationDisplayState(release, release.publication_status))), cell(formatDate(release.accepted_at)), cell(technicalReference(release.content_sha256, 12))); return row; },
          "Published data versions", { responsive: true },
        )));
        if (activeLink) [...resultsHost.querySelectorAll("a[href]")].find((item) => item.getAttribute("href") === activeLink)?.focus({ preventScroll: true });
        window.scrollTo({ top: scrollY, behavior: "instant" });
      }
      renderResults(body);
      let refreshing = false;
      const refresh = async () => {
        clearTimeout(releaseListTimer);
        if (refreshing || document.hidden || !routeEpoch.isCurrent()) return;
        refreshing = true;
        try {
          const result = await request(listPath);
          if (routeEpoch.isCurrent()) renderResults(result.body);
        } catch {
          if (routeEpoch.isCurrent() && !resultsHost.querySelector(".refresh-warning")) append(resultsHost, el("p", "notice warning refresh-warning", "Publication states could not be refreshed. Retrying shortly."));
        } finally {
          refreshing = false;
          if (routeEpoch.isCurrent()) releaseListTimer = setTimeout(refresh, 30000);
        }
      };
      refreshReleaseList = refresh;
      releaseListTimer = setTimeout(refresh, 30000);
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren(errorState(error, rerender));
    }
  }

  async function renderReleaseDetail(id, routeEpoch, { polling = false } = {}) {
    const refresh = detailRequests.begin();
    const detailRequest = (path) => request(path, { signal: refresh.signal });
    const isCurrent = () => routeEpoch.isCurrent() && refresh.isCurrent();
    if (!polling) publicationPolling.attempts = 0;
    stopPublicationPolling();
    const { body, requestId } = await detailRequest(`dataset-releases/${id}`);
    if (!isCurrent()) return;
    const release = entity(body, "release");
    const receipts = body.receipts || [];
    const activations = body.activations || [];
    const consumerImports = body.consumer_imports || [];
    const activeConsumerImport = activePublicationOperation({ consumer_imports: consumerImports });
    const activeActivation = [...activations].reverse().find((item) => ["queued", "claimed", "running", "interrupted"].includes(item.status)) || null;
    const publicationOutcome = reconcilePublication({
      release, activations, consumer_imports: consumerImports,
      publication_policy: body.publication_policy,
    });
    const publicationInProgress = publicationOutcome === "pending";
    let manifest = release.manifest_json || body.manifest;
    let manifestError = null;
    if (!manifest) {
      try {
        manifest = (await detailRequest(`dataset-releases/${id}/manifest`)).body;
      } catch (error) {
        if (error.name === "AbortError") throw error;
        manifestError = error;
      }
    }
    if (evidenceCache?.identity !== id || (!polling && evidenceCache?.result?.status === "rejected")) {
      const cache = { identity: id, result: null, promise: null };
      cache.promise = request(`dataset-releases/${id}/records?limit=25&offset=0`)
        .then((value) => ({ status: "fulfilled", value }), (reason) => ({ status: "rejected", reason }))
        .then((result) => { cache.result = result; return result; });
      evidenceCache = cache;
    }
    const previewPromise = evidenceCache.promise;
    const [qualityResult, acceptedResult] = await Promise.allSettled([
        Array.isArray(body.quality_results)
          ? Promise.resolve({ body: { items: body.quality_results } })
          : detailRequest(`ingestion-runs/${release.ingestion_run_id}/quality-results?limit=100`),
        Object.hasOwn(body, "accepted_predecessor")
          ? Promise.resolve({ body: { items: body.accepted_predecessor ? [body.accepted_predecessor] : [] } })
          : detailRequest("dataset-releases?status=accepted&limit=100"),
      ]);
    if (!isCurrent()) return;
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
      const latest = entity((await request(`dataset-releases/${id}`)).body, "release");
      if (latest.status !== release.status || latest.version !== release.version) {
        showToast("This version changed. The latest review actions are now shown.");
        await rerender();
        return;
      }
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
    if (["review", "review_required", "awaiting_review"].includes(release.status) && !blocking && !publicationInProgress) actions.push(button(publicationOutcome === "failed" ? "Retry publication" : "Publish", "button primary", async () => {
      const comment = requiredReviewText("Approval note");
      const ok = await confirmAction({
        title: "Publish this version?",
        description: "Publishing makes this verified version current in the data platform. Downstream imports run separately.",
        label: "Publish version",
        tone: "primary",
        extra: comment,
        progressLabel: "Publishing…",
        discardMessage: "Discard your approval note?",
        onConfirm: () => publishReviewedRelease(release, requiredReviewValue(comment, "Approval note")),
      });
      if (ok) await renderReleaseDetail(id, routeEpoch, { polling: true });
    }));
    if (["candidate", "review", "review_required", "awaiting_review"].includes(release.status) && !publicationInProgress) actions.push(button("Reject", "button danger", async () => {
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
    if (release.status === "accepted" && ["failed", "rejected"].includes(consumerImports.at(-1)?.status)) {
      actions.push(button("Retry downstream import", "button secondary", async () => {
        await mutate(`dataset-releases/${id}/retry-delivery`, {
          idempotencyKey: `delivery-${id}-${newRequestId()}`,
          body: { version: release.version }, success: "Downstream import queued",
        });
        await rerender();
      }));
    }
    actions.push(button("Review with AI", "button secondary", () => { location.hash = `#ai/release:${id}`; }));

    disposeTableRegions(view);
    view.replaceChildren();
    const sourceRecordCount = release.coverage_json?.source_record_count;
    append(view, pageHeading("Dataset review", `${displayName(release.dataset_id)} ${release.release_version}`, `${researchAreaLabel(release.target_feature)} · ${formatNumber(sourceRecordCount ?? release.record_count)} source records`, actions));
    const displayState = publicationDisplayState(release, publicationOutcome);
    const lifecycle = releaseLifecycleContext(displayState);
    const lifecycleNotice = el("div", `notice ${lifecycle.tone}`.trim());
    append(lifecycleNotice, badge(displayState), document.createTextNode(` ${lifecycle.message}`));
    append(view, lifecycleNotice);
    if (publicationOutcome === "failed") {
      const failure = activations.at(-1)?.error_json;
      if (failure?.message) append(view, el("div", "notice negative", failure.message));
    }
    if (activeActivation) append(view, el("div", "notice info", `Publication continues (${activeActivation.progress_phase || displayName(activeActivation.status)}). The current version remains live until the final switch succeeds.`));
    if (activeConsumerImport) append(view, el("div", "notice info", `Downstream import continues (${displayName(activeConsumerImport.phase_key || activeConsumerImport.status)}). It does not block data platform publication.`));
    const downstreamFailure = consumerImports.at(-1)?.error_json;
    if (release.status === "accepted" && downstreamFailure?.message) append(view, el("div", "notice warning", `Published in the data platform. Downstream import needs attention: ${downstreamFailure.message}`));
    if (publicationInProgress && publicationPolling.attempts >= PUBLICATION_POLL_LIMIT) append(view, el("div", "notice info", "Publication is still running. Progress updates continue every 30 seconds."));
    if (blocking) append(view, el("div", "notice negative", "Required data checks failed, so this version cannot be published. Review the failures, then retry or reject it."));
    const layout = el("div", "detail-layout");
    const releaseBody = el("div");
    append(releaseBody, detailList([["State", badge(displayState)], ["Schema", release.schema_version], ["Source generation records", formatNumber(sourceRecordCount ?? release.record_count)], ["Portable product records", formatNumber(release.record_count)], ["Content hash", el("code", "mono", release.content_sha256)], ["Coverage", release.coverage_json ? technicalDetails(release.coverage_json, "Inspect coverage") : "Unknown"], ["Review note", release.review_comment || "No review note recorded"], ["Created", formatDate(release.created_at)], ["Published", formatDate(release.accepted_at)], ["Request ID", el("code", "mono", requestId)]]), technicalDetails(release, "Inspect version metadata"));
    const side = el("div", "stack");
    append(side, panel(
      "Dataset manifest",
      "Files and settings needed to reproduce this version",
      manifest
        ? technicalDetails(manifest, "Inspect manifest")
        : el(
          "div",
          "notice warning",
          `Manifest unavailable.${manifestError?.requestId ? ` Request ID: ${manifestError.requestId}.` : ""}`,
        ),
    ));
    const receiptBody = el("div");
    if (!receipts.length) append(receiptBody, el("p", "", "No consumer publication receipts recorded."));
    for (const receipt of [...receipts].reverse()) append(receiptBody, detailList([["Research area", receipt.consumer_operation_id?.startsWith("feature-1-local:") ? "Data platform verification" : researchAreaLabel(receipt.target_feature || release.target_feature)], ["Status", badge(receipt.status === "accepted" ? (receipt.consumer_operation_id?.startsWith("feature-1-local:") ? "verified" : "imported") : receipt.status)], ["Rows received", formatNumber(receipt.rows_received)], ["Rows accepted", formatNumber(receipt.rows_accepted)], ["Failure details", receipt.error ? technicalDetails(receipt.error, "Inspect failure") : "None recorded"]]));
    append(side, panel("Publication receipts", "Producer verification and downstream import outcomes", receiptBody));
    const consumerImportBody = el("div");
    const previousImports = el("div", "stack");
    if (!consumerImports.length) append(consumerImportBody, el("p", "", "No consumer import operations recorded."));
    for (const [index, operation] of [...consumerImports].reverse().entries()) append(index === 0 ? consumerImportBody : previousImports, detailList([
      ["Status", badge(operation.status)],
      ["Phase", displayName(operation.phase_key || "Not recorded")],
      ["Consumer status", displayName(operation.remote_status || "Not reported")],
      ["Attempt", formatNumber(operation.attempt_number)],
      ["Last worker heartbeat", formatDate(operation.heartbeat_at)],
      ["Next check or retry", ["interrupted", "polling", "queued"].includes(operation.status) ? formatDate(operation.next_attempt_at) : "Not scheduled"],
      ["Requested", formatDate(operation.requested_at)],
      ["Started", formatDate(operation.started_at)],
      ["Finished", formatDate(operation.finished_at)],
      ["Budgets", operation.budgets ? technicalDetails(operation.budgets, "Inspect limits") : "Not recorded"],
      ["Failure details", operation.error_json ? technicalDetails(operation.error_json, "Inspect failure") : "None recorded"],
    ]));
    if (consumerImports.length > 1) append(consumerImportBody, disclosurePanel("Previous delivery attempts", `${consumerImports.length - 1} historical operations; latest outcome shown above`, previousImports));
    append(side, panel("Consumer import operations", "Independent downstream delivery and import outcomes", consumerImportBody));
    const activationBody = el("div");
    if (!activations.length) append(activationBody, el("p", "", "No background publication operations recorded."));
    for (const activation of [...activations].reverse()) append(activationBody, detailList([["Status", badge(activation.status)], ["Current step", activation.progress_phase || (["failed", "succeeded"].includes(activation.status) ? displayName(activation.status) : "Waiting for a publication worker")], ["Started", formatDate(activation.started_at)], ["Last progress update", formatDate(activation.progress_updated_at)], ["Attempt", formatNumber(activation.attempt_number)], ["Requested", formatDate(activation.requested_at)], ["Materialised", formatDate(activation.materialized_at)], ["Finished", formatDate(activation.finished_at)], ["Failure details", activation.error_json ? technicalDetails(activation.error_json, "Inspect failure") : "None recorded"]]));
    append(side, panel("Background publication", "Registry preparation completes before a short accepted-version switch", activationBody));
    append(layout, panel(publicationInProgress ? "Publishing version" : ["accepted", "superseded"].includes(release.status) ? "Published dataset" : publicationOutcome === "failed" ? "Publication needs attention" : "Version under review", "The exact version selected for publication", releaseBody), side);
    append(view, layout);
    const previewHost = panel("Dataset preview", "Records in this version", el("p", "", "Loading record preview…"));
    append(view, previewHost);
    previewPromise.then((previewResult) => {
      if (!isCurrent() || !previewHost.isConnected) return;
      previewHost.replaceWith(previewResult.status === "fulfilled"
        ? releasePreviewPanel(id, previewResult.value.body, { request: detailRequest, isCurrent, displayState })
        : panel("Dataset preview", "Records in this version", el("div", "notice warning", "A record preview is unavailable for this dataset. Version details and data checks remain available.")));
    });
    append(view, renderReleaseReviewEvidence(release, predecessor, qualityResults, { qualityUnavailable: qualityResult.status === "rejected", predecessorUnavailable: acceptedResult.status === "rejected" }));
    const newestConsumerImport = [...consumerImports].reverse()[0] || null;
    const statusPath = newestConsumerImport?.id
      ? consumerImportStatusPath(
        id,
        newestConsumerImport.id,
        publicationStatusPaths.get(id) || "",
      )
      : "";
    schedulePublicationPoll(id, statusPath, routeEpoch, activeConsumerImport ? "pending" : publicationOutcome);
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

  return { renderReleases };
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
