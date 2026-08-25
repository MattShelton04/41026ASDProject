import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { displayName, formatBytes, formatDate, formatNumber, humanise, researchAreaLabel } from "../core/formats.js?v=17";
import { isPsiJob } from "../core/forms.js?v=18";
import { routeQuery } from "../core/router.js";
import { filterToolbar } from "../components/forms.js?v=17";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js?v=17";
import { emptyState, errorState, renderLoading } from "../components/states.js";
import { cell, makeTable, primaryCell } from "../components/tables.js";

function operationStep(number, title, description) {
  const item = el("div", "operation-step");
  append(item, el("span", "operation-number", number), el("div"));
  append(item.lastElementChild, el("strong", "", title), el("p", "", description));
  return item;
}

export function jobLifecycleMessage(status) {
  if (status === "active") return "";
  if (status === "draft") return "This data update is still a draft. Set its lifecycle status to Active before starting it.";
  if (status === "disabled") return "This data update is disabled. Its saved history remains available, but it cannot start until its lifecycle status is Active.";
  if (status === "retired") return "This data update is retired and retained for history. Create or reactivate an appropriate definition before starting new work.";
  return `This data update cannot start while its lifecycle status is ${humanise(status || "unknown")}.`;
}

export function createEntityRoutes({ view, request, openEntityDialog, openPlanDialog, confirmAction, mutate, rerender }) {
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
      append(view, pageHeading("Property data", isSource ? "Data sources" : "Data updates", isSource ? "Manage the publishers, licences and schedules behind property data." : "Start repeatable data imports and preview what each update will do.", [button(`Create ${isSource ? "source" : "update"}`, "button primary", () => openEntityDialog(isSource ? "source" : "job"))]));
      append(view, filterToolbar({ search: filters.q, status: filters.status, statuses: ["active", "draft", "disabled", "retired", "all"], placeholder: isSource ? "Source or publisher" : "Update or dataset", onApply: (values) => { location.hash = `#${kind}${queryString(values)}`; } }));
      if (!items.length) {
        append(view, emptyState(`No ${isSource ? "sources" : "data updates"} found`, filters.q || filters.status ? "Try clearing the current filters." : `Create the first ${isSource ? "source record" : "data update"}.`));
        return;
      }
      const columns = isSource
        ? [{ label: "Source" }, { label: "Publisher" }, { label: "Adapter" }, { label: "Cadence" }, { label: "Status" }, { label: "Actions" }]
        : [{ label: "Update" }, { label: "Dataset / area" }, { label: "Method" }, { label: "Capacity alarm" }, { label: "Status" }, { label: "Actions" }];
      const table = makeTable(columns, items, (item) => {
        const row = el("tr");
        const actions = el("div", "button-row");
        if (!isSource) {
          const runNow = button("Start update", "button primary small", () => openPlanDialog(item, null, { intent: "run" }));
          const backfill = button("Load earlier data", "button secondary small", () => openPlanDialog(item, null, { intent: "backfill" }));
          runNow.disabled = item.status !== "active";
          backfill.disabled = item.status !== "active";
          append(actions, runNow, backfill, link("View history", `#runs${queryString({ job: item.id })}`, "button secondary small"));
        }
        append(actions, link("View", `#${kind}/${item.id}`, "button secondary small"), button("Edit", "button secondary small", () => openEntityDialog(isSource ? "source" : "job", item)), button("Delete", "button small danger", async () => {
          const confirmed = await confirmAction({
            title: `Delete ${item.name}?`,
            description: "Only unused draft/test definitions can be deleted. Existing provenance remains protected.",
            label: "Delete definition",
            progressLabel: "Deleting…",
            onConfirm: () => mutate(`${kind}/${item.id}`, { method: "DELETE", body: item.version === undefined ? undefined : { version: item.version }, success: `${humanise(isSource ? "source" : "job")} deleted` }),
          });
          if (!confirmed) return;
          await rerender();
        }));
        for (const control of actions.querySelectorAll("button, a")) control.setAttribute("aria-label", `${control.textContent.trim()} ${item.name}`);
        if (isSource) append(row, cell(primaryCell(displayName(item.name), item.id)), cell(item.publisher), cell(displayName(item.adapter_key), "mono"), cell(humanise(item.cadence)), cell(badge(item.status)), cell(actions, "actions-cell"));
        else append(row, cell(primaryCell(displayName(item.name), displayName(item.profile_key))), cell(primaryCell(displayName(item.dataset_id || item.target?.contract), researchAreaLabel(item.target_feature || item.target?.feature))), cell(humanise(item.refresh_strategy)), cell(`${formatNumber(item.max_rows ?? item.limits?.max_rows)}-row alarm`, "numeric"), cell(badge(item.status)), cell(actions, "actions-cell"));
        return row;
      }, isSource ? "Registered data sources" : "Saved data updates");
      append(view, panel(`${items.length} ${isSource ? "sources" : "data updates"}`, "Showing up to 100 results", table));
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  async function renderEntityDetail(kind, id) {
    const singular = kind === "sources" ? "source" : "job";
    renderLoading(view, `Loading ${singular}`);
    try {
      const result = await request(`${kind}/${encodeURIComponent(id)}`);
      const item = entity(result.body, singular);
      let capabilities = null;
      let capabilitiesError = null;
      if (kind === "jobs") {
        try { capabilities = (await request(`jobs/${encodeURIComponent(id)}/capabilities`)).body; } catch (error) { capabilitiesError = error; }
      }
      view.replaceChildren();
      const actions = [button("Edit", "button secondary", () => openEntityDialog(singular, item))];
      if (kind === "jobs") {
        const runNow = button("Start update", "button primary", () => openPlanDialog(item, capabilities, { intent: "run" }));
        const backfill = button("Load earlier data", "button secondary", () => openPlanDialog(item, capabilities, { intent: "backfill" }));
        runNow.disabled = item.status !== "active";
        backfill.disabled = item.status !== "active";
        actions.unshift(runNow, backfill, link("Update history", `#runs${queryString({ job: item.id })}`, "button secondary"));
      }
      append(view, pageHeading(kind === "sources" ? "Data source" : "Data update", displayName(item.name || singular), `${kind === "sources" ? item.publisher || "Attributed source" : displayName(item.dataset_id || item.target?.contract || "Data update")} · Version ${item.version ?? "—"}`, actions));
      if (kind === "jobs" && jobLifecycleMessage(item.status)) append(view, el("div", "notice warning", jobLifecycleMessage(item.status)));
      if (capabilitiesError) append(view, el("div", "notice warning", `Available processing options could not be checked. Saved settings and update history remain available.${capabilitiesError.requestId ? ` Request ID ${capabilitiesError.requestId}.` : ""}`));
      const left = el("div");
      const entries = kind === "sources" ? [
        ["Status", badge(item.status)], ["Publisher", item.publisher], ["Update cadence", item.cadence], ["Connector", displayName(item.adapter_key)], ["Licence", item.licence_id], ["Redistribution", item.redistribution_policy], ["Attribution URL", item.source_url], ["Updated", formatDate(item.updated_at)],
      ] : [
        ["Status", badge(item.status)], ["Dataset", displayName(item.dataset_id || item.target?.contract)], ["Research area", researchAreaLabel(item.target_feature || item.target?.feature)], ["Update profile", displayName(item.profile_key)], ["Refresh strategy", humanise(item.refresh_strategy)], ["Default mode", humanise(item.default_run_mode)], ["Data-check policy", item.quality_policy_key || item.quality_policy], ["Updated", formatDate(item.updated_at)],
      ];
      append(left, detailList(entries), technicalDetails(item));
      const right = el("div", "stack");
      if (kind === "sources") {
        append(right, panel("Download protection", "Only approved source locations can be requested", el("div", "notice", "The attribution URL describes the publisher. Downloads still use the approved host and path configured for this source adapter.")));
      } else {
        const limits = el("div", "metric-strip");
        for (const [label, value] of [["Row alarm", formatNumber(item.max_rows ?? item.limits?.max_rows)], ["Byte alarm", formatBytes(item.max_bytes ?? item.limits?.max_bytes)], ["Object alarm", formatNumber(item.max_objects ?? item.limits?.max_objects)], ["Time alarm", `${formatNumber(item.timeout_seconds ?? item.limits?.deadline_seconds)}s`]]) {
          const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(limits, metric);
        }
        append(right, panel("Capacity safeguards", "The update fails atomically instead of returning partial data when a registered alarm is crossed", limits));
        const workflow = el("div", "operation-guide");
        append(workflow,
          operationStep("1", "Choose scope", isPsiJob(item) ? "Run complete history plus current weekly updates, or select explicit annual/weekly partitions." : "Review the registered job scope."),
          operationStep("2", "Preview update", "Check the source, work and limits before starting."),
          operationStep("3", "Review the result", "Follow progress, then retry a failed update if needed."),
        );
        append(right, panel("How this update works", "Preview, process and review", workflow));
        if (capabilities) append(right, panel("Available processing options", "Resolved adapter and dataset behaviour", technicalDetails(capabilities, "Inspect technical contract")));
      }
      const layout = el("div", "detail-layout");
      append(layout, panel(kind === "sources" ? "Source details" : "Update settings", "Saved settings used for this data update", left), right);
      append(view, layout);
    } catch (error) { view.replaceChildren(errorState(error, rerender)); }
  }

  return { renderEntityList, renderEntityDetail };
}
