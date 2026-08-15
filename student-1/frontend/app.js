import { API_BASE, collection, entity, newRequestId, queryString, requestJson } from "./core/api.js";
import { append, button, el, link } from "./core/dom.js";
import { coverageRows, formatBytes, formatDate, formatNumber, humanise, releaseComparison, reportReleaseRows, stateLabel, statusTone } from "./core/formats.js";
import { parseJsonField } from "./core/forms.js";
import { ACTIVE_RUN_STATES, createGenerationGuard } from "./core/polling.js";
import { parseRoute } from "./core/router.js";
import { waitForDialog } from "./components/dialogs.js";
import { filterToolbar, formField } from "./components/forms.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "./components/layout.js";
import { emptyState, errorState, renderLoading } from "./components/states.js";
import { cell, makeTable, primaryCell } from "./components/tables.js";
import { createEntityRoutes } from "./routes/entities.js";
import { renderOverview } from "./routes/overview.js";
import { createRunPlanner } from "./routes/run-plan.js";
import { createRunRoutes } from "./routes/runs.js";

const view = document.querySelector("#view");
const liveRegion = document.querySelector("#live-region");
const serviceState = document.querySelector("#service-state");
const sidebar = document.querySelector("#primary-nav");
const navToggle = document.querySelector("#nav-toggle");
const entityDialog = document.querySelector("#entity-dialog");
const entityForm = document.querySelector("#entity-form");
const actionDialog = document.querySelector("#action-dialog");
const actionForm = document.querySelector("#action-form");
const toast = document.querySelector("#toast");

const state = {
  pollTimer: null,
  lastRunStatus: "",
  selectedProperty: null,
  propertyResults: [],
  requests: new Map(),
};
const generationGuard = createGenerationGuard();

const RUN_FILTERS = ["", "requested", "queued", "running", "succeeded", "failed", "cancelled", "interrupted"];

function announce(message) {
  liveRegion.textContent = "";
  requestAnimationFrame(() => { liveRegion.textContent = message; });
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 4500);
  announce(message);
}

function setActiveNavigation(route) {
  for (const item of document.querySelectorAll("[data-route]")) {
    if (item.dataset.route === route) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  sidebar.classList.remove("open");
  navToggle.setAttribute("aria-expanded", "false");
}

function clearView() {
  view.replaceChildren();
}

function loading(title = "Loading evidence") {
  renderLoading(view, title);
}

function request(path, options = {}) {
  return requestJson(fetch, path.startsWith("/") ? path : `${API_BASE}/${path}`, options);
}

const SOURCE_FIELDS = [
  { name: "name", label: "Source name", required: true },
  { name: "publisher", label: "Publisher", required: true },
  { name: "source_url", label: "Attribution URL", type: "url", required: true, wide: true, help: "Metadata only; acquisition remains allowlisted" },
  { name: "adapter_key", label: "Registered adapter", required: true },
  { name: "cadence", label: "Update cadence", required: true },
  { name: "licence_id", label: "Licence", required: true },
  { name: "licence_url", label: "Licence URL", type: "url", required: true },
  { name: "redistribution_policy", label: "Redistribution policy", required: true, wide: true },
  { name: "target_features", label: "Target features", type: "json_array", wide: true, required: true, help: "JSON list of feature keys" },
  { name: "status", label: "Lifecycle status", options: ["draft", "active", "disabled", "retired"], required: true },
  { name: "notes", label: "Operator notes", type: "textarea", wide: true },
];

const JOB_FIELDS = [
  { name: "source_definition_id", label: "Source ID", required: true, wide: true },
  { name: "name", label: "Job name", required: true },
  { name: "profile_key", label: "Registered profile", required: true },
  { name: "profile_version", label: "Profile version", required: true },
  { name: "adapter_key", label: "Registered adapter", required: true },
  { name: "release_builder_key", label: "Release builder", required: true },
  { name: "import_profile_key", label: "Import profile", required: true },
  { name: "import_profile_version", label: "Import profile version", required: true },
  { name: "target_feature", label: "Target feature", required: true },
  { name: "dataset_id", label: "Dataset ID", required: true },
  { name: "refresh_strategy", label: "Refresh strategy", options: ["full_snapshot", "append_only_partitioned", "partitioned_snapshot", "manual_versioned_import"], required: true },
  { name: "default_run_mode", label: "Default run mode", options: ["full_refresh", "reprocess_cached"], required: true },
  { name: "scope_json", label: "Bounded default scope", type: "json", wide: true },
  { name: "quality_policy_key", label: "Quality policy", required: true },
  { name: "quality_policy_version", label: "Quality policy version", required: true },
  { name: "max_parallelism", label: "Maximum parallel tasks", type: "number", min: 1, required: true },
  { name: "timeout_seconds", label: "Time limit (seconds)", type: "number", min: 1, required: true },
  { name: "max_objects", label: "Object limit", type: "number", min: 1, required: true },
  { name: "max_bytes", label: "Byte limit", type: "number", min: 1, required: true },
  { name: "max_rows", label: "Row limit", type: "number", min: 1, required: true },
  { name: "status", label: "Lifecycle status", options: ["draft", "active", "disabled", "retired"], required: true },
  { name: "schedule_text", label: "Schedule note", wide: true, help: "Descriptive only in Release 0" },
];

const RELEASE_FIELDS = [
  { name: "dataset_id", label: "Dataset ID", required: true, createOnly: true },
  { name: "source_definition_id", label: "Source definition ID", required: true, createOnly: true },
  { name: "ingestion_run_id", label: "Ingestion run ID", required: true, createOnly: true },
  { name: "target_feature", label: "Target feature", required: true, createOnly: true },
  { name: "release_version", label: "Release version", required: true },
  { name: "schema_version", label: "Schema version", required: true },
  { name: "coverage", label: "Coverage evidence", type: "json", wide: true },
  { name: "record_count", label: "Record count", type: "number", min: 0, required: true },
  { name: "content_sha256", label: "Content SHA-256", required: true, wide: true, pattern: "[0-9a-f]{64}" },
  { name: "artifact_record_id", label: "Artifact record ID", required: true, createOnly: true },
  { name: "manifest", label: "Bounded manifest", type: "json", wide: true },
  { name: "review_comment", label: "Review note", type: "textarea", wide: true },
];

async function openEntityDialog(kind, item = null) {
  const isSource = kind === "source";
  const fields = isSource ? SOURCE_FIELDS : JOB_FIELDS;
  document.querySelector("#entity-kicker").textContent = isSource ? "Source definition" : "Job definition";
  document.querySelector("#entity-title").textContent = `${item ? "Edit" : "Create"} ${kind}`;
  const fieldHost = document.querySelector("#entity-fields");
  const fieldValue = (name) => {
    const aliases = {
      adapter_key: item?.adapter?.key,
      import_profile_key: item?.import_profile?.key,
      import_profile_version: item?.import_profile?.version,
      target_feature: item?.target?.feature,
      target_features: item?.target_features_json,
      quality_policy_key: item?.quality_policy,
      max_parallelism: item?.limits?.max_parallelism,
      timeout_seconds: item?.limits?.deadline_seconds,
      max_objects: item?.limits?.max_objects,
      max_bytes: item?.limits?.max_bytes,
      max_rows: item?.limits?.max_rows,
    };
    return item?.[name] ?? aliases[name];
  };
  fieldHost.replaceChildren(...fields.map((definition) => formField(definition, fieldValue(definition.name))));
  document.querySelector("#entity-error").textContent = "";
  entityDialog.returnValue = "";
  entityDialog.showModal();
  entityDialog.querySelector("input, select, textarea")?.focus();

  if (!await waitForDialog(entityDialog, "save")) return;
  const data = Object.fromEntries(new FormData(entityForm));
  try {
    for (const definition of fields.filter((field) => field.type === "json")) data[definition.name] = parseJsonField(data[definition.name], definition.label);
    for (const definition of fields.filter((field) => field.type === "json_array")) {
      try {
        const parsed = JSON.parse(data[definition.name] || "[]");
        if (!Array.isArray(parsed) || (definition.required && parsed.length === 0) || parsed.some((value) => typeof value !== "string")) throw new Error();
        data[definition.name] = parsed;
      } catch { throw new Error(`${definition.label} must be a JSON list of text values.`); }
    }
    for (const definition of fields.filter((field) => field.type === "number")) data[definition.name] = Number(data[definition.name]);
    if (item?.version !== undefined) data.version = item.version;
    const path = isSource ? "sources" : "jobs";
    const method = item ? "PUT" : "POST";
    const result = await request(`${path}${item ? `/${encodeURIComponent(item.id)}` : ""}`, { method, body: data });
    showToast(`${humanise(kind)} ${item ? "updated" : "created"}. Request ID ${result.requestId}`);
    await renderRoute();
  } catch (error) {
    showToast(`${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`);
  }
}

async function openReleaseDialog(item = null) {
  document.querySelector("#entity-kicker").textContent = "Dataset release";
  document.querySelector("#entity-title").textContent = `${item ? "Edit" : "Create"} draft release`;
  const fieldHost = document.querySelector("#entity-fields");
  const valueFor = (name) => {
    if (name === "coverage") return item?.coverage_json;
    if (name === "manifest") return item?.manifest_json;
    return item?.[name];
  };
  fieldHost.replaceChildren(...RELEASE_FIELDS.map((definition) => formField(
    { ...definition, disabled: Boolean(item && definition.createOnly) },
    valueFor(definition.name),
  )));
  document.querySelector("#entity-error").textContent = "";
  entityDialog.returnValue = "";
  entityDialog.showModal();
  entityDialog.querySelector("input:not(:disabled), select:not(:disabled), textarea:not(:disabled)")?.focus();
  if (!await waitForDialog(entityDialog, "save")) return;
  const data = Object.fromEntries(new FormData(entityForm));
  try {
    data.coverage = parseJsonField(data.coverage, "Coverage evidence");
    data.manifest = parseJsonField(data.manifest, "Manifest");
    data.record_count = Number(data.record_count);
    data.review_comment = data.review_comment?.trim() || null;
    if (item) data.version = item.version;
    else data.status = "draft";
    const result = await request(`dataset-releases${item ? `/${encodeURIComponent(item.id)}` : ""}`, {
      method: item ? "PUT" : "POST",
      body: data,
    });
    showToast(`Draft release ${item ? "updated" : "created"}. Request ID ${result.requestId}`);
    const saved = entity(result.body, "release");
    if (!item && saved?.id) location.hash = `#releases/${saved.id}`;
    else await renderRoute();
  } catch (error) {
    showToast(`${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`);
  }
}

function confirmAction({ title, description, label = "Confirm", tone = "danger", extra = null }) {
  document.querySelector("#action-title").textContent = title;
  document.querySelector("#action-description").textContent = description;
  document.querySelector("#action-error").textContent = "";
  const host = document.querySelector("#action-extra");
  host.replaceChildren();
  if (extra) append(host, extra);
  const confirm = document.querySelector("#action-confirm");
  confirm.textContent = label;
  confirm.className = `button ${tone}`;
  actionDialog.returnValue = "";
  actionDialog.showModal();
  return waitForDialog(actionDialog, "confirm");
}

async function mutate(path, { method = "POST", body = {}, success = "Action completed" } = {}) {
  const idempotencyKey = body?.idempotency_key || newRequestId();
  const result = await request(path, {
    method,
    headers: { "Idempotency-Key": idempotencyKey },
    body,
  });
  showToast(`${success}. Request ID ${result.requestId}`);
  return result.body;
}

const openPlanDialog = createRunPlanner({ request, mutate, confirmAction, showToast });
const { renderEntityList, renderEntityDetail } = createEntityRoutes({
  view,
  request,
  openEntityDialog,
  openPlanDialog,
  confirmAction,
  mutate,
  showToast,
  rerender: renderRoute,
});

const { renderRuns, renderRunDetail } = createRunRoutes({
  view, request, mutate, confirmAction, showToast, announce, state, generationGuard, rerender: renderRoute,
});
async function renderReleases(id = "") {
  loading("Loading release evidence");
  try {
    if (id) return await renderReleaseDetail(id);
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    const filters = { q: params.get("q") || "", status: params.get("status") || "" };
    const { body } = await request(`dataset-releases${queryString({ status: filters.status, limit: 100 })}`);
    const releases = collection(body);
    const visibleReleases = filters.q ? releases.filter((release) => [release.dataset_id, release.release_version, release.target_feature].some((value) => String(value || "").toLowerCase().includes(filters.q.toLowerCase()))) : releases;
    clearView();
    append(view, pageHeading("Publication control", "Dataset releases", "Create and maintain draft metadata, compare candidates with accepted evidence, then publish only after quality and human review.", [button("Create draft release", "button primary", () => openReleaseDialog())]));
    append(view, filterToolbar({ ...filters, statuses: ["", "draft", "candidate", "awaiting_review", "accepted", "rejected", "superseded"], placeholder: "Dataset, version or target", onApply: (values) => { location.hash = `#releases${queryString(values)}`; renderRoute(); } }));
    if (!visibleReleases.length) { append(view, emptyState("No dataset releases", filters.q || filters.status ? "Try clearing the current filters." : "Completed ingestion runs can create isolated candidate releases.")); return; }
    const table = makeTable([{ label: "Dataset / release" }, { label: "Target" }, { label: "Records" }, { label: "Status" }, { label: "Accepted" }, { label: "Checksum" }], visibleReleases, (release) => {
      const row = el("tr");
      append(row, cell(link(release.dataset_id || "Dataset", `#releases/${release.id}`), "primary-cell"), cell(release.target_feature), cell(formatNumber(release.record_count), "numeric"), cell(badge(release.status)), cell(formatDate(release.accepted_at)), cell(String(release.content_sha256 || "—").slice(0, 12), "mono"));
      return row;
    });
    append(view, panel(`${visibleReleases.length} releases`, "Candidates are isolated from accepted generations", table));
  } catch (error) { if (!id) { clearView(); append(view, errorState(error, renderRoute)); } else throw error; }
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
    || acceptedReleases.find((candidate) => candidate.id !== release.id && candidate.dataset_id === release.dataset_id && candidate.target_feature === release.target_feature)
    || null;
  clearView();
  const actions = [];
  if (["draft", "candidate"].includes(release.status)) actions.push(button("Edit metadata", "button secondary", () => openReleaseDialog(release)));
  if (["draft", "rejected"].includes(release.status)) actions.push(button("Delete", "button danger", async () => {
    const ok = await confirmAction({ title: `Delete ${release.release_version}?`, description: "Only unreferenced draft or rejected local releases can be deleted. Retained quality, receipt and registry evidence remains protected.", label: "Delete release" });
    if (!ok) return;
    try { await mutate(`dataset-releases/${id}`, { method: "DELETE", body: undefined, success: "Release deleted" }); location.hash = "#releases"; } catch (error) { showToast(`${error.message} Request ID ${error.requestId}`); }
  }));
  if (["validated", "candidate"].includes(release.status)) actions.push(button("Submit for review", "button secondary", async () => {
    const comment = el("textarea"); comment.placeholder = "Reviewer context (required)";
    const ok = await confirmAction({ title: "Submit candidate for review?", description: "Blocking failures cannot be bypassed. The candidate remains isolated until publication succeeds.", label: "Submit review", tone: "primary", extra: comment });
    if (ok && comment.value.trim()) { await mutate(`dataset-releases/${id}/submit-review`, { body: { version: release.version, comment: comment.value.trim() }, success: "Candidate submitted" }); renderRoute(); }
    else if (ok) showToast("A review comment is required.");
  }));
  if (["review", "review_required", "awaiting_review"].includes(release.status)) actions.push(button("Publish", "button primary", async () => {
    const comment = el("textarea"); comment.placeholder = "Approval evidence (required)";
    const ok = await confirmAction({ title: "Publish this release?", description: "This protected action starts the idempotent consumer import handshake. The prior accepted release stays live unless the consumer accepts this release.", label: "Publish release", tone: "primary", extra: comment });
    if (ok && comment.value.trim()) { await mutate(`dataset-releases/${id}/publish`, { body: { approved: true, version: release.version, comment: comment.value.trim() }, success: "Publication requested" }); renderRoute(); }
    else if (ok) showToast("Approval evidence is required.");
  }));
  if (["candidate", "review", "review_required", "awaiting_review"].includes(release.status)) actions.push(button("Reject", "button danger", async () => { const reason = el("textarea"); reason.placeholder = "Reason for rejection (required)"; const ok = await confirmAction({ title: "Reject this candidate?", description: "The decision and reason become durable evidence. Accepted data is unchanged.", label: "Reject candidate", extra: reason }); if (ok && reason.value.trim()) { await mutate(`dataset-releases/${id}/reject`, { body: { reason: reason.value.trim(), version: release.version }, success: "Candidate rejected" }); renderRoute(); } }));
  actions.push(button("Diagnose with AI", "button secondary", () => { location.hash = `#ai/release:${id}`; }));
  append(view, pageHeading("Dataset release", `${release.dataset_id} ${release.release_version}`, `${release.target_feature} · ${formatNumber(release.record_count)} records`, actions));
  if (!["accepted", "superseded"].includes(release.status)) append(view, el("div", "notice warning", "This is candidate evidence. The previously accepted release remains live until the publication handshake succeeds."));
  const layout = el("div", "detail-layout");
  const releaseBody = el("div");
  append(releaseBody, detailList([["Status", badge(release.status)], ["Schema", release.schema_version], ["Content hash", el("code", "mono", release.content_sha256)], ["Review note", release.review_comment || "No review note recorded"], ["Created", formatDate(release.created_at)], ["Accepted", formatDate(release.accepted_at)], ["Supersedes", release.supersedes_release_id ? link(release.supersedes_release_id, `#releases/${release.supersedes_release_id}`) : "None"]]), technicalDetails(release));
  const side = el("div", "stack");
  append(side, panel("Manifest", "Bounded reproducibility evidence", manifest ? technicalDetails(manifest, "Inspect manifest") : el("p", "", "Manifest unavailable.")));
  const receiptBody = el("div");
  if (!receipts.length) append(receiptBody, el("p", "", "No consumer publication receipts recorded."));
  for (const receipt of receipts) append(receiptBody, detailList([["Target", receipt.target_feature], ["Status", badge(receipt.status)], ["Rows accepted", formatNumber(receipt.rows_accepted)], ["Request ID", el("code", "mono", receipt.request_id || requestId)]]));
  append(side, panel("Publication receipts", "Consumer-owned import outcomes", receiptBody));
  append(layout, panel("Release evidence", "Candidate and accepted state remain distinct", releaseBody), side);
  append(view, layout);
  if (previewResult.status === "fulfilled") append(view, releasePreviewPanel(id, previewResult.value.body));
  else append(view, panel("Dataset preview", "Bounded release-scoped records", el("div", "notice warning", "Preview is unavailable for this release profile. Release evidence and quality controls remain available.")));
  append(view, renderReleaseReviewEvidence(release, predecessor, qualityResults, {
    qualityUnavailable: qualityResult.status === "rejected",
    predecessorUnavailable: acceptedResult.status === "rejected",
  }));
}

function previewValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    const encoded = JSON.stringify(value);
    return encoded.length > 80 ? technicalDetails(value, "Inspect value") : el("code", "mono", encoded);
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function releasePreviewPanel(releaseId, initialPage) {
  const host = el("section", "panel");
  const heading = el("div", "panel-heading");
  const headingCopy = el("div");
  append(headingCopy, el("h2", "", "Dataset preview"), el("p", "", "Bounded rows from this exact candidate or accepted generation"));
  append(heading, headingCopy);
  const body = el("div", "panel-body");
  append(host, heading, body);

  const renderPage = (page) => {
    body.replaceChildren();
    const release = page.release || {};
    append(body, el("div", "notice", `${humanise(release.status)} generation · ${formatNumber(page.total)} previewable ${humanise(page.profile)} records. No other release is mixed into this view.`));
    if (!page.items?.length) {
      append(body, emptyState("No preview rows", "This release has no rows in its registered warehouse projection."));
      return;
    }
    const columns = page.columns || Object.keys(page.items[0]);
    append(body, makeTable(columns.map((column) => ({ label: humanise(column) })), page.items, (item) => {
      const row = el("tr");
      columns.forEach((column, index) => {
        const value = previewValue(item[column]);
        append(row, cell(index === 0 && !(value instanceof Node) ? primaryCell(value) : value, index === 0 ? "primary-cell" : ""));
      });
      return row;
    }));
    const controls = el("div", "dialog-actions");
    const previous = button("Previous page", "button secondary");
    const next = button("Next page", "button secondary");
    previous.disabled = page.offset <= 0;
    next.disabled = page.next_offset === null || page.next_offset === undefined;
    const load = async (offset, control) => {
      control.disabled = true;
      try {
        const result = await request(`dataset-releases/${releaseId}/records${queryString({ limit: page.limit || 25, offset })}`);
        renderPage(result.body);
      } catch (error) {
        body.prepend(el("div", "notice warning", `${error.message} Request ID ${error.requestId}`));
        control.disabled = false;
      }
    };
    previous.addEventListener("click", () => load(Math.max(0, page.offset - page.limit), previous));
    next.addEventListener("click", () => load(page.next_offset, next));
    append(controls, el("span", "field-help", `Showing ${formatNumber(page.offset + 1)}–${formatNumber(page.offset + page.count)} of ${formatNumber(page.total)}`), previous, next);
    append(body, controls);
  };
  renderPage(initialPage);
  return host;
}

function renderReleaseReviewEvidence(release, predecessor, qualityResults, availability) {
  const section = el("section", "dashboard-grid");
  const comparisonBody = el("div");
  if (availability.predecessorUnavailable) append(comparisonBody, el("div", "notice warning", "Accepted predecessor evidence is temporarily unavailable. Publication controls remain governed by the backend."));
  else if (!predecessor) append(comparisonBody, el("p", "", "No accepted predecessor exists for this dataset and target."));
  else {
    append(comparisonBody, el("div", "notice", `Comparing candidate ${release.release_version} with accepted predecessor ${predecessor.release_version}.`));
    append(comparisonBody, makeTable(
      [{ label: "Evidence" }, { label: "Candidate" }, { label: "Accepted predecessor" }, { label: "Change" }],
      releaseComparison(release, predecessor),
      (item) => {
        const row = el("tr");
        const renderValue = (value) => typeof value === "object" ? JSON.stringify(value) : String(value ?? "—");
        append(row, cell(item.field, "primary-cell"), cell(renderValue(item.candidate)), cell(renderValue(item.predecessor)), cell(badge(item.changed ? "warning" : "complete")));
        return row;
      },
    ));
  }

  const qualityBody = el("div");
  if (availability.qualityUnavailable) append(qualityBody, el("div", "notice warning", "Quality evidence is temporarily unavailable. No failure is inferred from this dependency state."));
  else if (!qualityResults.length) append(qualityBody, el("p", "", "No quality results are linked to this release run."));
  else append(qualityBody, makeTable(
    [{ label: "Rule" }, { label: "Severity" }, { label: "Outcome" }, { label: "Message" }, { label: "Sample" }],
    qualityResults,
    (item) => {
      const row = el("tr");
      append(row, cell(primaryCell(item.rule_key, item.dimension)), cell(badge(item.severity)), cell(badge(item.status)), cell(item.message), cell(item.sample_json ? technicalDetails(item.sample_json, "Bounded sample") : "—"));
      return row;
    },
  ));
  append(section, panel("Candidate comparison", "Accepted and candidate versions shown together", comparisonBody), panel("Quality review", `${qualityResults.length} linked deterministic checks`, qualityBody));
  return section;
}

async function resolveRunScopedEvidence(kind, id) {
  let runId = id;
  if (!runId) {
    const result = await request("ingestion-runs?limit=1");
    runId = collection(result.body)[0]?.id;
  }
  if (!runId) return { runId: "", items: [] };
  const suffix = kind === "quality" ? "quality-results" : "artifacts";
  const result = await request(`ingestion-runs/${runId}/${suffix}?limit=100`);
  return { runId, items: collection(result.body), requestId: result.requestId };
}

async function renderEvidenceExplorer(kind, id) {
  loading(`Loading ${kind} evidence`);
  try {
    const { runId, items } = await resolveRunScopedEvidence(kind, id);
    clearView();
    append(view, pageHeading("Evidence explorer", kind === "quality" ? "Quality results" : "Artifacts", kind === "quality" ? "Filter rule outcomes without exposing unbounded source records." : "Inspect hashes, sizes, retention and lineage without exposing storage paths or restricted data."));
    if (runId) append(view, el("div", "notice", `Showing bounded evidence for run ${runId}. Select another run from the Runs screen to inspect its evidence.`));
    if (!items.length) { append(view, emptyState(`No ${kind} evidence`, runId ? "This run has not recorded evidence of this type." : "No ingestion runs are available yet.")); return; }
    const table = kind === "quality" ? makeTable(
      [{ label: "Rule" }, { label: "Dimension" }, { label: "Severity" }, { label: "Outcome" }, { label: "Message" }, { label: "Evidence" }], items,
      (item) => { const row = el("tr"); append(row, cell(primaryCell(item.rule_key, item.rule_version)), cell(humanise(item.dimension)), cell(badge(item.severity)), cell(badge(item.status)), cell(item.message), cell(technicalDetails({ observed: item.observed_value_json, expected: item.expected_value_json, sample: item.sample_json }, "Inspect"))); return row; },
    ) : makeTable(
      [{ label: "Artifact" }, { label: "Type" }, { label: "Size" }, { label: "SHA-256" }, { label: "Retention" }, { label: "Created" }], items,
      (item) => { const row = el("tr"); append(row, cell(primaryCell(item.logical_key, item.id)), cell(`${item.artifact_kind} · ${item.media_type}`), cell(formatBytes(item.bytes), "numeric"), cell(String(item.content_sha256).slice(0, 16), "mono"), cell(humanise(item.retention_class)), cell(formatDate(item.created_at))); return row; },
    );
    append(view, panel(`${items.length} ${kind === "quality" ? "checks" : "artifact records"}`, "Safe, bounded metadata", table));
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

async function renderCoverage() {
  loading("Loading coverage matrix");
  try {
    const result = await request("dataset-releases?limit=100");
    const rows = [];
    for (const release of collection(result.body).filter((item) => ["accepted", "superseded"].includes(item.status))) {
      const coverage = release.coverage_json || {};
      rows.push({ dataset_id: release.dataset_id, locality: coverage.locality || coverage.area || coverage.state || "NSW", coverage_status: coverage.status || (coverage.complete === false ? "partial" : "supported"), target_feature: release.target_feature, release_version: release.release_version, accepted_at: release.accepted_at, description: coverage.profile });
    }
    clearView();
    append(view, pageHeading("Availability evidence", "Coverage matrix", "Accepted, partial, stale and unavailable are explicit data states—not inferred from a running service."));
    if (!rows.length) { append(view, emptyState("No coverage evidence", "Coverage is published only after a release has been accepted.")); return; }
    const table = makeTable([{ label: "Dataset" }, { label: "Locality / area" }, { label: "Consumer feature" }, { label: "Coverage" }, { label: "Accepted release" }, { label: "As at" }], rows, (item) => {
      const row = el("tr");
      append(row, cell(primaryCell(item.dataset || item.dataset_id, item.description)), cell(item.locality || item.area || item.geography || "NSW"), cell(item.feature || item.target_feature || "Property discovery"), cell(badge(item.status || item.coverage_status)), cell(item.release_version || item.dataset_release_id || "—", "mono"), cell(formatDate(item.as_at || item.accepted_at)));
      return row;
    });
    append(view, panel(`${rows.length} coverage entries`, "Colour is always paired with status text", table));
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

async function renderProperties() {
  clearView();
  const hero = el("section", "discovery-hero");
  append(hero, el("p", "eyebrow", "Property discovery"), el("h1", "", "Trace an NSW address to the evidence behind it"), el("p", "", "Search the accepted property registry, inspect match provenance and see which buyer features have usable data."));
  const form = el("form", "search-box");
  const input = el("input"); input.type = "search"; input.name = "q"; input.placeholder = "Try 11 Example Street, Sydney NSW 2000"; input.autocomplete = "street-address"; input.maxLength = 250; input.required = true;
  const search = button("Search", "button primary"); search.type = "submit";
  append(form, input, search);
  append(hero, form);
  append(hero, el("p", "search-help", "NSW only · Maximum 25 matches · Search works without AI"));
  append(view, hero);
  const resultHost = el("div");
  append(resultHost, emptyState("Start with a street address", "Results include an accessible list and table-based coordinate context. No map interaction is required."));
  append(view, resultHost);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    resultHost.replaceChildren(el("section", "loading-state", "Searching the accepted property registry…"));
    try {
      const result = await request(`properties/search${queryString({ q: input.value.trim(), state: "NSW", limit: 25 })}`);
      const items = collection(result.body);
      state.propertyResults = items;
      if (result.body.supported === false) resultHost.replaceChildren(el("div", "notice warning", "This query is outside the supported NSW coverage. Try an NSW street address."));
      else if (!items.length) resultHost.replaceChildren(emptyState("No canonical property found", "Try including a street number, suburb and four-digit postcode. The platform will not invent or silently broaden a match."));
      else { renderPropertyResults(resultHost, items); announce(`${items.length} property matches found.`); }
    } catch (error) { resultHost.replaceChildren(errorState(error, () => form.requestSubmit())); }
  });
}

function renderPropertyResults(host, items) {
  const layout = el("div", "property-results");
  const listBody = el("div", "result-list");
  listBody.setAttribute("aria-label", "Property matches");
  const detailHost = el("div");
  items.forEach((item, index) => {
    const result = el("button", "result-card"); result.type = "button";
    append(result, el("strong", "", item.address_display), el("span", "", `${item.locality || ""} ${item.state || "NSW"} ${item.postcode || ""} · ${humanise(item.resolution_status || item.match?.status)}`));
    result.addEventListener("click", () => selectProperty(item, detailHost, result, listBody));
    append(listBody, result);
    if (index === 0) queueMicrotask(() => result.click());
  });
  append(layout, panel(`${items.length} matches`, "Select a result to inspect evidence", listBody), detailHost);
  append(host, layout);
}

async function selectProperty(summary, host, selectedButton, list) {
  for (const item of list.querySelectorAll(".result-card")) item.removeAttribute("aria-current");
  selectedButton.setAttribute("aria-current", "true");
  host.replaceChildren(panel("Property evidence", "Loading accepted snapshot…", el("div", "loading-state", "Loading…")));
  try {
    const [detailResult, mapResult, coverageResult, reportResult] = await Promise.all([
      request(`properties/${encodeURIComponent(summary.property_ref)}`),
      request(`properties/${encodeURIComponent(summary.property_ref)}/map-context`),
      request(`properties/${encodeURIComponent(summary.property_ref)}/coverage`),
      request(`properties/${encodeURIComponent(summary.property_ref)}/report-section`).catch((error) => ({ error })),
    ]);
    const property = entity(detailResult.body, "property");
    const map = entity(mapResult.body);
    const coverage = coverageRows(coverageResult.body).length ? coverageRows(coverageResult.body) : (detailResult.body.coverage || []);
    const body = el("div", "stack");
    append(body, el("div", "notice", `Canonical property reference: ${property.property_ref}. Match evidence is shown explicitly; aliases are not silently merged.`));
    const mapPanel = el("div", "map-context");
    const latitude = map.latitude ?? map.coordinates?.latitude ?? property.latitude ?? property.coordinates?.latitude;
    const longitude = map.longitude ?? map.coordinates?.longitude ?? property.longitude ?? property.coordinates?.longitude;
    append(mapPanel, el("span", "map-pin", "⌖"), el("div", "map-caption", `${latitude ?? "Unknown latitude"}, ${longitude ?? "unknown longitude"} · Map-style context with accessible evidence below`));
    append(body, mapPanel, detailList([["Canonical address", property.address_display || property.display_address], ["Locality", property.locality], ["Postcode", property.postcode], ["Resolution", badge(property.resolution_status || summary.resolution_status || property.match?.tier)], ["Match source", summary.match?.source || property.match?.source], ["Match score", summary.match?.score ?? summary.match?.confidence ?? property.match?.score ?? property.match?.confidence ?? "Not supplied"]]));
    const cards = el("div", "coverage-grid");
    for (const item of coverage) { const card = el("div", `coverage-card ${statusTone(item.status || item.coverage_status || item.state)}`); append(card, el("strong", "", item.dataset || item.dataset_id || item.feature || item.target_feature || "Dataset"), el("span", "", `${humanise(item.status || item.coverage_status || item.state)}${item.release_version ? ` · ${item.release_version}` : ""}${item.limitation ? ` · ${item.limitation}` : ""}`)); append(cards, card); }
    if (coverage.length) append(body, el("h3", "", "Feature coverage"), cards);
    append(body, renderPropertyReportSection(reportResult));
    append(body, technicalDetails({ identifiers: detailResult.body.identifiers || [], aliases: detailResult.body.aliases || [], map }, "Identifiers, aliases and coordinate evidence"));
    host.replaceChildren(panel("Property evidence", "Accepted snapshot and provenance", body));
  } catch (error) { host.replaceChildren(errorState(error, () => selectProperty(summary, host, selectedButton, list))); }
}

function renderPropertyReportSection(result) {
  const section = el("section", "panel report-section");
  const heading = el("div", "panel-heading");
  const copy = el("div");
  append(copy, el("h3", "", "Dossier report evidence"), el("p", "", "Bounded identity and accepted-release facts for Feature 5"));
  append(heading, copy);
  append(section, heading);
  const body = el("div", "panel-body");
  if (result?.error) {
    append(body, el("div", "notice warning", `Report-section evidence is temporarily unavailable. Property discovery remains usable.${result.error.requestId ? ` Request ID ${result.error.requestId}` : ""}`));
    append(section, body);
    return section;
  }
  const report = result?.body || {};
  const identity = report.identity || {};
  append(body, detailList([
    ["Property reference", el("code", "mono", report.property_ref || "Not supplied")],
    ["Address", report.address_display || "Not supplied"],
    ["G-NAF PID", identity.gnaf_pid || "Not supplied"],
    ["Resolution", humanise(identity.resolution_status)],
    ["Locality", identity.locality || "Not supplied"],
    ["Evidence entries", formatNumber(report.evidence_count)],
  ]));
  const releases = reportReleaseRows(report);
  if (!releases.length) append(body, el("p", "", "No accepted release evidence is available for this report section."));
  else append(body, makeTable(
    [{ label: "Dataset" }, { label: "Target feature" }, { label: "Release" }, { label: "Status" }, { label: "Accepted" }, { label: "Coverage" }],
    releases,
    (item) => {
      const row = el("tr");
      append(row, cell(item.dataset_id || "—", "primary-cell"), cell(item.target_feature || "—"), cell(item.release_version || item.dataset_release_id || "—"), cell(badge(item.coverage_status)), cell(formatDate(item.accepted_at || item.checked_at)), cell(item.coverage_scope ? technicalDetails(item.coverage_scope, "Inspect") : "—"));
      return row;
    },
  ));
  if (identity.geometry) append(body, technicalDetails(identity.geometry, "Report coordinate evidence"));
  append(section, body);
  return section;
}

async function renderAi(context = "") {
  loading("Loading diagnosis workspace");
  try {
    const [releasesResult, historyResult] = await Promise.all([
      request("dataset-releases?limit=100"),
      request("agent-runs?limit=50").catch((error) => ({ error, body: { items: [] } })),
    ]);
    const releases = collection(releasesResult.body);
    const history = collection(historyResult.body);
    const selectedAgentRun = context && !context.startsWith("release:") ? context : "";
    clearView();
    append(view, pageHeading("Assisted investigation", "AI diagnosis", "The model inspects bounded stored evidence and pauses before protected retry or publish actions.", selectedAgentRun ? [link("New diagnosis", "#ai", "button primary")] : []));
    append(view, el("div", "notice", "Direct operations and property discovery do not depend on Ollama. If the model is unavailable, all stored evidence remains accessible."));
    if (historyResult.error) append(view, el("div", "notice warning", `Diagnosis history is temporarily unavailable.${historyResult.error.requestId ? ` Request ID ${historyResult.error.requestId}` : ""}`));
    else if (!history.length) append(view, emptyState("No diagnosis history", "Start the first bounded diagnosis below. The run will remain available after navigation or reload."));
    else {
      const historyTable = makeTable(
        [{ label: "Diagnosis" }, { label: "Status" }, { label: "Latest phase" }, { label: "Tool calls" }, { label: "Started" }, { label: "Open" }],
        history,
        (run) => {
          const row = el("tr");
          append(row,
            cell(primaryCell(run.objective_preview || "Bounded diagnosis", run.id)),
            cell(badge(run.status)),
            cell(humanise(run.latest_phase)),
            cell(formatNumber(run.tool_call_count), "numeric"),
            cell(formatDate(run.created_at)),
            cell(link(run.id === selectedAgentRun ? "Viewing" : "View trace", `#ai/${run.id}`, "button secondary small"), "actions-cell"),
          );
          return row;
        },
      );
      append(view, panel("Diagnosis history", `${history.length} durable AI-mode runs · newest first`, historyTable));
    }
    const traceHost = el("div");
    if (selectedAgentRun) {
      append(view, traceHost);
      await pollAgent(selectedAgentRun, traceHost);
    }
    const formBody = el("div");
    const form = el("form", "form-grid");
    const releaseLabel = el("label", "wide"); append(releaseLabel, el("span", "", "Candidate release"));
    const releaseSelect = el("select"); releaseSelect.required = true;
    for (const release of releases) { const option = el("option", "", `${release.dataset_id} ${release.release_version} · ${humanise(release.status)}`); option.value = release.id; option.selected = context === `release:${release.id}`; append(releaseSelect, option); }
    append(releaseLabel, releaseSelect);
    append(form, releaseLabel);
    const objectiveLabel = el("label", "wide"); append(objectiveLabel, el("span", "", "Diagnosis objective"));
    const objective = el("textarea"); objective.value = "Diagnose why this candidate is not publishable, determine whether existing buyer analytics remain usable, and prepare the safest recovery action."; objective.maxLength = 2000; objective.required = true; append(objectiveLabel, objective); append(form, objectiveLabel);
    const submit = button("Start bounded diagnosis", "button primary"); submit.type = "submit"; append(form, submit); append(formBody, form);
    append(view, panel("Start diagnosis", "Plan → Act → Observe → Adapt with human review", formBody));
    if (!releases.length) { form.replaceChildren(el("p", "", "No release candidates are available to diagnose.")); return; }
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); submit.disabled = true;
      formBody.prepend(el("div", "notice", "Creating a durable AI-mode run…"));
      try {
        const result = await mutate(`dataset-releases/${releaseSelect.value}/agent-runs`, { body: { objective: objective.value.trim() }, success: "Diagnosis started" });
        const run = entity(result, "agent_run");
        location.hash = `#ai/${run.id || result.id}`;
      } catch (error) {
        const message = error.status === 503 ? "Ollama is unavailable. Direct evidence and recovery controls remain usable; retry diagnosis when the model service is ready." : error.message;
        formBody.prepend(el("div", "notice warning", `${message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`));
        submit.disabled = false;
      }
    });
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

async function pollAgent(id, host, cursor = 0, failures = 0) {
  const generation = generationGuard.current();
  try {
    const [detailResult, eventsResult] = await Promise.all([request(`agent-runs/${id}`), request(`agent-runs/${id}/events${queryString({ after: cursor, limit: 100 })}`)]);
    if (!generationGuard.isCurrent(generation)) return;
    const run = entity(detailResult.body, "agent_run");
    const events = collection(eventsResult.body);
    const body = el("div");
    const steps = run.steps || detailResult.body.steps || events;
    append(body, detailList([["Status", badge(run.status)], ["Agent run", el("code", "mono", run.id || id)], ["Request ID", el("code", "mono", run.request_id || detailResult.requestId)]]));
    const timeline = el("ol", "timeline");
    for (const step of steps) {
      const item = el("li"); const tone = statusTone(step.status); const detail = el("div");
      append(detail, el("h3", "", humanise(step.phase || step.event_type || "Agent event")), el("p", "", step.summary || step.message || humanise(step.status)));
      if (step.tool_key || step.tool_name) append(detail, el("code", "mono", step.tool_key || step.tool_name));
      append(item, el("span", `timeline-marker ${tone}`, stateLabel(step.status).symbol), detail);
      append(timeline, item);
    }
    append(body, timeline);
    if (run.status === "review_required") append(body, el("div", "notice warning", "A protected retry or publication is paused for human review. Review it in the durable AI-mode approval interface; no write has occurred."));
    if (run.final_result) append(body, technicalDetails(run.final_result, "Terminal result and cited evidence"));
    host.replaceChildren(panel("Agent trace", "Live durable phases and bounded tool calls", body));
    if (["succeeded", "failed", "cancelled", "review_required"].includes(run.status)) return;
    const nextCursor = eventsResult.body.next_cursor || events.at(-1)?.id || cursor;
    setTimeout(() => { if (generationGuard.isCurrent(generation)) pollAgent(id, host, nextCursor); }, document.hidden ? 8000 : 1500);
  } catch (error) {
    if (!generationGuard.isCurrent(generation)) return;
    host.replaceChildren(el("div", "notice warning", `Diagnosis polling paused: ${error.message} Request ID ${error.requestId}. The run is durable and can be reloaded.`));
    if (failures < 4) setTimeout(() => pollAgent(id, host, cursor, failures + 1), Math.min(15000, 2000 * (2 ** failures)));
  }
}

async function checkHealth() {
  try {
    await request("/health/ready", { timeoutMs: 4000 });
    serviceState.className = "service-state online";
    serviceState.lastElementChild.textContent = "Data service available";
  } catch {
    serviceState.className = "service-state offline";
    serviceState.lastElementChild.textContent = "Data service unavailable";
  }
}

async function renderRoute() {
  generationGuard.next();
  clearTimeout(state.pollTimer);
  state.lastRunStatus = "";
  const { route, id } = parseRoute(location.hash);
  setActiveNavigation(route);
  view.setAttribute("aria-busy", "true");
  try {
    if (route === "overview") await renderOverview({ view, request });
    else if (route === "sources" || route === "jobs") id ? await renderEntityDetail(route, id) : await renderEntityList(route);
    else if (route === "runs") id ? await renderRunDetail(id) : await renderRuns();
    else if (route === "releases") await renderReleases(id);
    else if (route === "quality" || route === "artifacts") await renderEvidenceExplorer(route, id);
    else if (route === "coverage") await renderCoverage();
    else if (route === "properties") await renderProperties();
    else if (route === "ai") await renderAi(id);
  } catch (error) {
    clearView();
    append(view, errorState(error, renderRoute));
  } finally {
    view.setAttribute("aria-busy", "false");
  }
}

entityForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.submitter?.value === "cancel") entityDialog.close("cancel");
  else if (entityForm.reportValidity()) entityDialog.close("save");
});
actionForm.addEventListener("submit", (event) => { event.preventDefault(); actionDialog.close(event.submitter?.value || "cancel"); });
navToggle.addEventListener("click", () => { const open = sidebar.classList.toggle("open"); navToggle.setAttribute("aria-expanded", String(open)); });
window.addEventListener("hashchange", renderRoute);
document.addEventListener("visibilitychange", () => { const current = parseRoute(location.hash); if (!document.hidden && current.route === "runs" && current.id && ACTIVE_RUN_STATES.has(state.lastRunStatus)) renderRunDetail(current.id, { polling: true }); });

checkHealth();
renderRoute();
setInterval(checkHealth, 30000);
