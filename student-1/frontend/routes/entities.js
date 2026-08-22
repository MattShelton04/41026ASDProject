import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatBytes, formatDate, formatNumber, humanise, researchAreaLabel } from "../core/formats.js";
import { isPsiJob } from "../core/forms.js";
import { routeQuery } from "../core/router.js";
import { filterToolbar } from "../components/forms.js?v=7";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState, renderLoading } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

function operationStep(number, title, description) {
  const item = el("div", "operation-step");
  append(item, el("span", "operation-number", number), el("div"));
  append(item.lastElementChild, el("strong", "", title), el("p", "", description));
  return item;
}

export function createEntityRoutes({ view, request, openEntityDialog, openPlanDialog, confirmAction, mutate, showToast, rerender }) {
  async function renderEntityList(kind) {
    const isSource = kind === "sources";
    const params = routeQuery(location.hash);
    const selectedStatus = params.has("status") ? params.get("status") || "all" : "active";
    const filters = { q: params.get("q") || "", status: selectedStatus };
    renderLoading(view, `Loading ${kind}`);
    try {
      const { body } = await request(`${kind}${queryString({ q: filters.q, status: filters.status === "all" ? "" : filters.status, limit: 100 })}`);
      const items = collection(body);
      view.replaceChildren();
      append(view, pageHeading("Property records", isSource ? "Source registry" : "Import jobs", isSource ? "Manage the publishers, licences and update schedules behind property data." : "Configure repeatable data updates and preview the work before starting a processing run.", [button(`Create ${isSource ? "source" : "job"}`, "button primary", () => openEntityDialog(isSource ? "source" : "job"))]));
      append(view, filterToolbar({ ...filters, statuses: ["active", "draft", "disabled", "retired", "all"], placeholder: isSource ? "Source or publisher" : "Job or dataset", onApply: (values) => { location.hash = `#${kind}${queryString(values)}`; rerender(); } }));
      if (!items.length) {
        append(view, emptyState(`No ${isSource ? "sources" : "import jobs"} found`, filters.q || filters.status ? "Try clearing the current filters." : `Create the first ${isSource ? "source record" : "import job"}.`));
        return;
      }
      const columns = isSource
        ? [{ label: "Source" }, { label: "Publisher" }, { label: "Adapter" }, { label: "Cadence" }, { label: "Status" }, { label: "Actions" }]
        : [{ label: "Job" }, { label: "Dataset / target" }, { label: "Strategy" }, { label: "Limits" }, { label: "Status" }, { label: "Actions" }];
      const table = makeTable(columns, items, (item) => {
        const row = el("tr");
        const actions = el("div", "button-row");
        if (!isSource) {
          const runNow = button("Run now", "button primary small", () => openPlanDialog(item, null, { intent: "run" }));
          const backfill = button("Backfill", "button secondary small", () => openPlanDialog(item, null, { intent: "backfill" }));
          runNow.disabled = item.status !== "active";
          backfill.disabled = item.status !== "active";
          append(actions, runNow, backfill, link("History", `#runs${queryString({ job: item.id })}`, "button secondary small"));
        }
        append(actions, link("View", `#${kind}/${item.id}`, "button secondary small"), button("Edit", "button secondary small", () => openEntityDialog(isSource ? "source" : "job", item)), button("Delete", "button small danger", async () => {
          const confirmed = await confirmAction({ title: `Delete ${item.name}?`, description: "Only unused draft/test definitions can be deleted. Existing provenance remains protected.", label: "Delete definition" });
          if (!confirmed) return;
          try {
            await mutate(`${kind}/${item.id}`, { method: "DELETE", body: item.version === undefined ? undefined : { version: item.version }, success: `${humanise(isSource ? "source" : "job")} deleted` });
            await rerender();
          } catch (error) { showToast(`${error.message} Request ID ${error.requestId}`); }
        }));
        if (isSource) append(row, cell(primaryCell(item.name, item.id)), cell(item.publisher), cell(item.adapter_key, "mono"), cell(item.cadence), cell(badge(item.status)), cell(actions, "actions-cell"));
        else append(row, cell(primaryCell(item.name, item.profile_key)), cell(primaryCell(item.dataset_id || item.target?.contract, researchAreaLabel(item.target_feature || item.target?.feature))), cell(humanise(item.refresh_strategy)), cell(`${formatNumber(item.max_rows ?? item.limits?.max_rows)} rows`, "numeric"), cell(badge(item.status)), cell(actions, "actions-cell"));
        return row;
      }, isSource ? "Registered data sources" : "Configured ingestion jobs");
      append(view, panel(`${items.length} ${isSource ? "sources" : "import jobs"}`, "Showing up to 100 results", table));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  async function renderEntityDetail(kind, id) {
    const singular = kind === "sources" ? "source" : "job";
    renderLoading(view, `Loading ${singular}`);
    try {
      const result = await request(`${kind}/${encodeURIComponent(id)}`);
      const item = entity(result.body, singular);
      let capabilities = null;
      if (kind === "jobs") {
        try { capabilities = (await request(`jobs/${encodeURIComponent(id)}/capabilities`)).body; } catch { /* optional evidence */ }
      }
      view.replaceChildren();
      const actions = [button("Edit", "button secondary", () => openEntityDialog(singular, item))];
      if (kind === "jobs") {
        const runNow = button("Run now", "button primary", () => openPlanDialog(item, capabilities, { intent: "run" }));
        const backfill = button("Backfill data", "button secondary", () => openPlanDialog(item, capabilities, { intent: "backfill" }));
        runNow.disabled = item.status !== "active";
        backfill.disabled = item.status !== "active";
        actions.unshift(runNow, backfill, link("Run history", `#runs${queryString({ job: item.id })}`, "button secondary"));
      }
      append(view, pageHeading(kind === "sources" ? "Registered source" : "Import job", item.name || humanise(singular), `${kind === "sources" ? item.publisher || "Attributed source" : item.dataset_id || item.target?.contract || "Data update"} · Version ${item.version ?? "—"}`, actions));
      const left = el("div");
      const entries = kind === "sources" ? [
        ["Status", badge(item.status)], ["Publisher", item.publisher], ["Update cadence", item.cadence], ["Registered adapter", item.adapter_key], ["Licence", item.licence_id], ["Redistribution", item.redistribution_policy], ["Attribution URL", item.source_url], ["Updated", formatDate(item.updated_at)],
      ] : [
        ["Status", badge(item.status)], ["Dataset contract", item.dataset_id || item.target?.contract], ["Research area", researchAreaLabel(item.target_feature || item.target?.feature)], ["Profile", item.profile_key], ["Refresh strategy", humanise(item.refresh_strategy)], ["Default mode", humanise(item.default_run_mode)], ["Quality policy", item.quality_policy_key || item.quality_policy], ["Updated", formatDate(item.updated_at)],
      ];
      append(left, detailList(entries), technicalDetails(item));
      const right = el("div", "stack");
      if (kind === "sources") {
        append(right, panel("Download protection", "Only approved source locations can be requested", el("div", "notice", "The attribution URL describes the publisher. Downloads still use the approved host and path configured for this source adapter.")));
      } else {
        const limits = el("div", "metric-strip");
        for (const [label, value] of [["Rows", formatNumber(item.max_rows ?? item.limits?.max_rows)], ["Bytes", formatBytes(item.max_bytes ?? item.limits?.max_bytes)], ["Objects", formatNumber(item.max_objects ?? item.limits?.max_objects)], ["Time", `${formatNumber(item.timeout_seconds ?? item.limits?.deadline_seconds)}s`]]) {
          const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(limits, metric);
        }
        append(right, panel("Failure safety ceilings", "Oversized or corrupt work aborts; successful data is never truncated", limits));
        const workflow = el("div", "operation-guide");
        append(workflow,
          operationStep("1", "Choose scope", isPsiJob(item) ? "Run complete history plus current weekly updates, or select explicit annual/weekly partitions." : "Review the registered job scope."),
          operationStep("2", "Preview plan", "Validate tasks, network access and hard limits before creating a run."),
          operationStep("3", "Monitor and recover", "Follow durable tasks, then retry failed work or reprocess verified cache."),
        );
        append(right, panel("How this job runs", "Preview, process and recover from the same recorded plan", workflow));
        if (capabilities) append(right, panel("Available processing options", "Resolved adapter and dataset behaviour", technicalDetails(capabilities, "Inspect technical contract")));
      }
      const layout = el("div", "detail-layout");
      append(layout, panel(kind === "sources" ? "Source details" : "Current configuration", "Saved values used by data operations", left), right);
      append(view, layout);
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  return { renderEntityList, renderEntityDetail };
}
