import { collection, entity, queryString } from "../core/api.js";
import { append, button, el, link } from "../core/dom.js";
import { displayName, formatDate, humanise, researchAreaLabel } from "../core/formats.js";
import { isPsiJob } from "../core/forms.js";
import { routeQuery } from "../core/router.js";
import { filterToolbar } from "../components/forms.js";
import { badge, detailList, pageHeading, panel, technicalDetails } from "../components/layout.js";
import { emptyState, errorState, renderLoading } from "../components/states.js";
import { actionMenu, cell, makeTable, primaryCell } from "../components/tables.js";
import { collectionPagination, pageOffset } from "../components/pagination.js";

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

export function createEntityRoutes({ view, request, openEntityDialog, openPlanDialog, confirmAction, mutate, generationGuard, rerender }) {
  async function openPlannerFromList(item, intent) {
    let capabilities = null;
    let capabilitiesError = null;
    try {
      capabilities = (await request(`jobs/${encodeURIComponent(item.id)}/capabilities`)).body;
    } catch (error) {
      capabilitiesError = error;
    }
    return openPlanDialog(item, capabilities, { intent, capabilitiesError });
  }

  async function renderEntityList() {
    const routeEpoch = generationGuard.capture();
    const params = routeQuery(location.hash);
    const selectedStatus = params.has("status") ? params.get("status") || "all" : "active";
    const filters = { q: params.get("q") || "", status: selectedStatus };
    const offset = pageOffset(params);
    renderLoading(view, "Loading jobs");
    try {
      const { body } = await request(`jobs${queryString({ q: filters.q, status: filters.status === "all" ? "" : filters.status, limit: 100, offset })}`);
      if (!routeEpoch.isCurrent()) return;
      const items = collection(body);
      view.replaceChildren();
      append(
        view,
        pageHeading(
          "Property data",
          "Data updates",
          "Start repeatable data imports and preview what each update will do.",
          [button("Create update", "button primary", () => openEntityDialog("job"))],
        ),
      );
      append(
        view,
        filterToolbar({
          search: filters.q,
          status: filters.status,
          statuses: ["active", "draft", "disabled", "retired", "all"],
          placeholder: "Update or dataset",
          onApply: (values) => {
            location.hash = `#jobs${queryString(values)}`;
          },
        }),
      );
      append(view, collectionPagination("jobs", filters, body, offset));
      if (!items.length) {
        append(
          view,
          emptyState(
            "No data updates found",
            filters.q || filters.status ? "Try clearing the current filters." : "Create the first data update.",
          ),
        );
        return;
      }
      const columns = [
        { label: "Update" },
        { label: "Dataset / area" },
        { label: "Method" },
        { label: "Import scope" },
        { label: "Status" },
        { label: "Actions" },
      ];
      const table = makeTable(
        columns,
        items,
        (item) => {
          const row = el("tr");
          const actions = el("div", "row-actions");
          const viewDetails = link("View details", `#jobs/${item.id}`, "button secondary small");
          const edit = button("Edit", "button secondary small", () => openEntityDialog("job", item));
          const remove = button("Delete", "button small danger", async () => {
            const confirmed = await confirmAction({
              title: `Delete ${item.name}?`,
              description: "Only unused draft/test definitions can be deleted. Existing provenance remains protected.",
              label: "Delete definition",
              progressLabel: "Deleting…",
              onConfirm: () =>
                mutate(`jobs/${item.id}`, {
                  method: "DELETE",
                  body: item.version === undefined ? undefined : { version: item.version },
                  success: "Job deleted",
                }),
            });
            if (!confirmed) return;
            await rerender();
          });
          const runNow = button("Start update", "button primary small", () => openPlannerFromList(item, "run"));
          const backfill = button("Load earlier data", "button secondary small", () => openPlannerFromList(item, "backfill"));
          runNow.disabled = item.status !== "active";
          backfill.disabled = item.status !== "active";
          append(
            actions,
            viewDetails,
            runNow,
            actionMenu(`More actions for ${item.name}`, [
              link("View history", `#runs${queryString({ job: item.id })}`, "button secondary small"),
              backfill,
              edit,
              remove,
            ]),
          );
          for (const control of actions.querySelectorAll("button, a")) {
            if (!control.hasAttribute("aria-label")) control.setAttribute("aria-label", `${control.textContent.trim()} ${item.name}`);
          }
          append(
            row,
            cell(primaryCell(link(displayName(item.name), `#jobs/${item.id}`), displayName(item.profile_key))),
            cell(
              primaryCell(
                displayName(item.dataset_id || item.target?.contract),
                researchAreaLabel(item.target_feature || item.target?.feature),
              ),
            ),
            cell(humanise(item.refresh_strategy)),
            cell(isPsiJob(item) ? "Complete default · selected archive years optional" : "Complete source"),
            cell(badge(item.status)),
            cell(actions, "actions-cell"),
          );
          return row;
        },
        "Saved data updates",
        { responsive: true },
      );
      const resultLabel = items.length === 1 ? "data update" : "data updates";
      append(view, panel(`${items.length} ${resultLabel}`, "Showing up to 100 results", table));
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren(errorState(error, rerender));
    }
  }

  async function renderEntityDetail(id) {
    const routeEpoch = generationGuard.capture();
    renderLoading(view, "Loading job");
    try {
      const result = await request(`jobs/${encodeURIComponent(id)}`);
      const item = entity(result.body, "job");
      let capabilities = null;
      let capabilitiesError = null;
      try {
        capabilities = (await request(`jobs/${encodeURIComponent(id)}/capabilities`)).body;
      } catch (error) {
        capabilitiesError = error;
      }
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren();
      const runNow = button("Start update", "button primary", () => openPlanDialog(item, capabilities, { intent: "run", capabilitiesError }));
      const backfill = button("Load earlier data", "button secondary", () => openPlanDialog(item, capabilities, { intent: "backfill", capabilitiesError }));
      runNow.disabled = item.status !== "active";
      backfill.disabled = item.status !== "active";
      const actions = [
        runNow,
        backfill,
        link("Update history", `#runs${queryString({ job: item.id })}`, "button secondary"),
        button("Edit", "button secondary", () => openEntityDialog("job", item)),
      ];
      append(
        view,
        pageHeading(
          "Data update",
          displayName(item.name || "job"),
          `${displayName(item.dataset_id || item.target?.contract || "Data update")} · Version ${item.version ?? "—"}`,
          actions,
        ),
      );
      if (jobLifecycleMessage(item.status)) append(view, el("div", "notice warning", jobLifecycleMessage(item.status)));
      if (capabilitiesError) {
        append(
          view,
          el(
            "div",
            "notice warning",
            `Available processing options could not be checked. Saved settings and update history remain available.${capabilitiesError.requestId ? ` Request ID ${capabilitiesError.requestId}.` : ""}`,
          ),
        );
      }
      const left = el("div");
      append(
        left,
        detailList([
          ["Status", badge(item.status)],
          ["Dataset", displayName(item.dataset_id || item.target?.contract)],
          ["Research area", researchAreaLabel(item.target_feature || item.target?.feature)],
          ["Update profile", displayName(item.profile_key)],
          ["Refresh strategy", humanise(item.refresh_strategy)],
          ["Default mode", humanise(item.default_run_mode)],
          ["Data-check policy", item.quality_policy_key || item.quality_policy],
          ["Updated", formatDate(item.updated_at)],
        ]),
        technicalDetails(item),
      );
      const right = el("div", "stack");
      const workflow = el("div", "operation-guide");
      append(
        workflow,
        operationStep("1", "Choose update coverage", "Complete source data is the default. PSI also supports selected completed publisher archive years as a partial candidate."),
        operationStep("2", "Preview update", "Check the source and proposed work before starting."),
        operationStep("3", "Review the result", "Follow progress, then retry a failed update if needed."),
      );
      append(right, panel("How this update works", "Preview, process and review", workflow));
      if (capabilities) {
        append(
          right,
          panel(
            "Available processing options",
            "Resolved adapter and dataset behaviour",
            technicalDetails(capabilities, "Inspect technical contract"),
          ),
        );
      }
      const layout = el("div", "detail-layout");
      append(layout, panel("Update settings", "Saved settings used for this data update", left), right);
      append(view, layout);
    } catch (error) {
      if (!routeEpoch.isCurrent()) return;
      view.replaceChildren(errorState(error, rerender));
    }
  }

  return { renderEntityList, renderEntityDetail };
}
