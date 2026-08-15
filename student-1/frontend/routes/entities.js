import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { formatBytes, formatDate, formatNumber, humanise, researchAreaLabel } from "../core/formats.js";
import { isPsiJob } from "../core/forms.js";
import { routeQuery } from "../core/router.js";
import { filterToolbar } from "../components/forms.js";
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
    const filters = { q: params.get("q") || "", status: params.get("status") || "" };
    renderLoading(view, `Loading ${kind}`);
    try {
      const { body } = await request(`${kind}${queryString({ ...filters, limit: 100 })}`);
      const items = collection(body);
      view.replaceChildren();
      append(view, pageHeading("Property data service · Data control", isSource ? "Source registry" : "Ingestion jobs", isSource ? "Manage attributed, allowlisted sources, licences and operating state." : "Configure bounded reusable ingestion and preview work before a durable run is created.", [button(`Create ${isSource ? "source" : "job"}`, "button primary", () => openEntityDialog(isSource ? "source" : "job"))]));
      append(view, filterToolbar({ ...filters, statuses: ["", "draft", "active", "disabled", "retired"], placeholder: isSource ? "Source or publisher" : "Job or dataset", onApply: (values) => { location.hash = `#${kind}${queryString(values)}`; rerender(); } }));
      if (!items.length) {
        append(view, emptyState(`No ${kind} found`, filters.q || filters.status ? "Try clearing the current filters." : `Create the first ${isSource ? "allowlisted source" : "bounded ingestion job"}.`));
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
      append(view, panel(`${items.length} ${kind}`, "Bounded to 100 results", table));
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
      append(view, pageHeading(kind === "sources" ? "Source definition" : "Job definition", item.name || humanise(singular), `${kind === "sources" ? item.publisher || "Attributed source" : item.dataset_id || item.target?.contract || "Bounded ingestion"} · Version ${item.version ?? "—"}`, actions));
      const left = el("div");
      const entries = kind === "sources" ? [
        ["Status", badge(item.status)], ["Publisher", item.publisher], ["Update cadence", item.cadence], ["Registered adapter", item.adapter_key], ["Licence", item.licence_id], ["Redistribution", item.redistribution_policy], ["Attribution URL", item.source_url], ["Updated", formatDate(item.updated_at)],
      ] : [
        ["Status", badge(item.status)], ["Dataset contract", item.dataset_id || item.target?.contract], ["Research area", researchAreaLabel(item.target_feature || item.target?.feature)], ["Profile", item.profile_key], ["Refresh strategy", humanise(item.refresh_strategy)], ["Default mode", humanise(item.default_run_mode)], ["Quality policy", item.quality_policy_key || item.quality_policy], ["Updated", formatDate(item.updated_at)],
      ];
      append(left, detailList(entries), technicalDetails(item));
      const right = el("div", "stack");
      if (kind === "sources") {
        append(right, panel("Safety boundary", "Source changes cannot create arbitrary requests", el("div", "notice", "The attribution URL is descriptive. Acquisition is constrained by the registered adapter’s host and path allowlist.")));
      } else {
        const limits = el("div", "metric-strip");
        for (const [label, value] of [["Rows", formatNumber(item.max_rows ?? item.limits?.max_rows)], ["Bytes", formatBytes(item.max_bytes ?? item.limits?.max_bytes)], ["Objects", formatNumber(item.max_objects ?? item.limits?.max_objects)], ["Time", `${formatNumber(item.timeout_seconds ?? item.limits?.deadline_seconds)}s`]]) {
          const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(limits, metric);
        }
        append(right, panel("Hard execution limits", "Validated before launch", limits));
        const workflow = el("div", "operation-guide");
        append(workflow,
          operationStep("1", "Choose scope", isPsiJob(item) ? "Select one source year or a bounded year range." : "Review the registered job scope."),
          operationStep("2", "Preview plan", "Validate tasks, network access and hard limits before creating a run."),
          operationStep("3", "Monitor and recover", "Follow durable tasks, then retry failed work or reprocess verified cache."),
        );
        append(right, panel("Operator workflow", "Run, backfill and recovery stay evidence-led", workflow));
        if (capabilities) append(right, panel("Registered capabilities", "Resolved adapter and builder behavior", technicalDetails(capabilities, "Inspect capability contract")));
      }
      const layout = el("div", "detail-layout");
      append(layout, panel(kind === "sources" ? "Source metadata" : "Resolved configuration", "Visible operator-safe fields", left), right);
      append(view, layout);
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  return { renderEntityList, renderEntityDetail };
}
