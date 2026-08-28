import { entity } from "../core/api.js";
import { append, button, el } from "../core/dom.js";
import { humanise } from "../core/formats.js?v=18";
import { createSubmissionGuard, isPsiJob } from "../core/forms.js?v=18";
import { technicalDetails } from "../components/layout.js?v=17";

export function createRunPlanner({ request, mutate, confirmAction }) {
  return async function openPlanDialog(job, capabilities = null, { intent = "run" } = {}) {
    const wrapper = el("div", "stack");
    const isBackfill = intent === "backfill";
    const psi = isPsiJob(job);
    const importProfile = job.import_profile_key || job.import_profile;
    append(wrapper, el("div", `notice ${isBackfill ? "warning" : ""}`, isBackfill
      ? "Loading earlier data starts a separate update. Published data changes only after the new version passes review."
      : "This update imports every record available from the registered source. Published data changes only after review."));

    const modeLabel = el("label", "field");
    append(modeLabel, el("span", "", "Update method (required)"));
    const mode = el("select"); mode.name = "run_mode"; mode.id = "run-mode"; mode.required = true;
    for (const value of capabilities?.supported_modes || capabilities?.run_modes || ["full_refresh", "reprocess_cached"]) {
      const option = el("option", "", humanise(value));
      option.value = value;
      option.selected = isBackfill ? value === "full_refresh" : value === job.default_run_mode;
      append(mode, option);
    }
    if (isBackfill) mode.disabled = true;
    append(modeLabel, mode);
    append(wrapper, modeLabel);

    const requestedScope = () => {
      const value = { ...(job.scope_json || {}), profile: "full-data", all_records: true };
      delete value.maximum_records;
      delete value.localities;
      delete value.years;
      delete value.weeks;
      if (importProfile === "bocsar-sparse") {
        delete value.geography_kind;
        delete value.geography_values;
        delete value.start_month;
        delete value.end_month;
        value.geography_kinds = ["postcode", "suburb"];
      }
      if (psi) {
        value.all_history = true;
        value.include_current_weekly = true;
        value.partition_type = "annual_and_weekly";
      }
      return value;
    };

    const preview = button("Preview update", "button secondary");
    const evidence = el("div");
    append(wrapper, preview, evidence);
    const previewGuard = createSubmissionGuard(async () => {
      evidence.replaceChildren(el("p", "", "Checking the source and proposed work…"));
      try {
        const payload = { run_mode: mode.value, scope: requestedScope() };
        const result = await request(`jobs/${job.id}/plans`, { method: "POST", body: payload });
        const scopeSummary = psi && payload.scope.all_history ? "Complete sales history: annual archives from 1990 plus current weekly updates" : "Complete dataset: all available source records";
        evidence.replaceChildren(el("div", "notice", `Update checked · ${scopeSummary}. Review the work before starting.`), technicalDetails(result.body, "Technical plan details"));
      } catch (error) {
        evidence.replaceChildren(el("div", "notice negative", `${error.message}${error.requestId ? ` Request ID ${error.requestId}.` : ""} Your update settings are unchanged.`));
      }
    }, (pending) => {
      preview.disabled = pending;
      preview.textContent = pending ? "Checking update…" : "Preview update";
      preview.setAttribute("aria-busy", String(pending));
    });
    preview.addEventListener("click", () => previewGuard.submit());
    let startedRun = null;
    const confirmed = await confirmAction({
      title: `${isBackfill ? "Load earlier data for" : "Start"} ${job.name}?`,
      description: "This creates a separate update that you can follow in Update history.",
      label: isBackfill ? "Load earlier data" : "Start update",
      tone: "primary",
      extra: wrapper,
      progressLabel: isBackfill ? "Starting earlier-data update…" : "Starting update…",
      discardMessage: "Discard your changed update scope?",
      onConfirm: async () => {
        const body = await mutate(`jobs/${job.id}/runs`, { body: { run_mode: mode.value, scope: requestedScope() }, success: isBackfill ? "Earlier-data update started" : "Data update started" });
        startedRun = entity(body, "run");
      },
    });
    if (!confirmed) return;
    location.hash = `#runs/${startedRun.id}`;
  };
}
