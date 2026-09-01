import { entity } from "../core/api.js";
import { append, button, el } from "../core/dom.js";
import { humanise } from "../core/formats.js";
import { createSubmissionGuard, isPsiJob, psiYearRange } from "../core/forms.js";
import { technicalDetails } from "../components/layout.js";

export function createRunPlanner({ request, mutate, confirmAction }) {
  return async function openPlanDialog(job, capabilities = null, { intent = "run", capabilitiesError = null } = {}) {
    const wrapper = el("div", "stack");
    const isBackfill = intent === "backfill";
    const psi = isPsiJob(job);
    append(wrapper, el("div", `notice ${isBackfill ? "warning" : ""}`, isBackfill
      ? "Loading earlier data starts a separate update. A selected-year PSI result is a non-publishable partial candidate; complete-source results still require review before publication."
      : "Complete source history is the default. PSI sales can instead load selected completed publisher archive years as a partial candidate."));
    if (capabilitiesError) {
      append(wrapper, el("div", "notice warning", `Update options could not be checked, so only the complete-source default is available.${capabilitiesError.requestId ? ` Request ID ${capabilitiesError.requestId}.` : ""}`));
    }

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

    let scopeProfile = null;
    let yearFields = null;
    let startYear = null;
    let endYear = null;
    const rangeCapabilities = capabilities?.scope_constraints?.["psi-year-range"];
    if (psi && capabilities?.supported_scope_profiles?.includes("psi-year-range") && rangeCapabilities) {
      const scopeLabel = el("label", "field");
      append(scopeLabel, el("span", "", "Sales history coverage (required)"));
      scopeProfile = el("select");
      scopeProfile.name = "scope_profile";
      scopeProfile.id = "scope-profile";
      for (const [value, label] of [
        ["full-data", "Complete history (default)"],
        ["psi-year-range", "Selected publisher archive years"],
      ]) {
        const option = el("option", "", label);
        option.value = value;
        append(scopeProfile, option);
      }
      append(scopeLabel, scopeProfile);
      yearFields = el("div", "field-grid");
      const latest = Number(rangeCapabilities.maximum_year);
      const earliest = Number(rangeCapabilities.minimum_year);
      startYear = el("input");
      startYear.type = "number";
      startYear.name = "start_year";
      startYear.id = "psi-start-year";
      startYear.min = String(earliest);
      startYear.max = String(latest);
      startYear.value = String(Math.max(earliest, latest - 4));
      endYear = el("input");
      endYear.type = "number";
      endYear.name = "end_year";
      endYear.id = "psi-end-year";
      endYear.min = String(earliest);
      endYear.max = String(latest);
      endYear.value = String(latest);
      const startLabel = el("label", "field");
      const endLabel = el("label", "field");
      append(startLabel, el("span", "", "First archive year"), startYear);
      append(endLabel, el("span", "", "Last archive year"), endYear);
      append(yearFields, startLabel, endLabel);
      yearFields.hidden = true;
      const rangeNotice = el("div", "notice warning", "Archive years select complete publisher ZIP partitions, not an exact contract-date range. The resulting candidate is labelled partial and cannot replace the accepted complete history.");
      rangeNotice.hidden = true;
      scopeProfile.addEventListener("change", () => {
        const scoped = scopeProfile.value === "psi-year-range";
        yearFields.hidden = !scoped;
        rangeNotice.hidden = !scoped;
        startYear.required = scoped;
        endYear.required = scoped;
      });
      append(wrapper, scopeLabel, yearFields, rangeNotice);
    }

    const requestedScope = () => {
      if (!scopeProfile || scopeProfile.value === "full-data") return { profile: "full-data", all_records: true };
      const minimum = Number(rangeCapabilities.minimum_year);
      const maximum = Number(rangeCapabilities.maximum_year);
      psiYearRange(startYear.value, endYear.value, { minimum, maximum });
      return { profile: "psi-year-range", start_year: Number(startYear.value), end_year: Number(endYear.value) };
    };

    const preview = button("Preview update", "button secondary");
    const evidence = el("div");
    append(wrapper, preview, evidence);
    const previewGuard = createSubmissionGuard(async () => {
      evidence.replaceChildren(el("p", "", "Checking the source and proposed work…"));
      try {
        const payload = { run_mode: mode.value, scope: requestedScope() };
        const result = await request(`jobs/${job.id}/plans`, { method: "POST", body: payload });
        const scopeSummary = result.body.scope?.profile === "psi-year-range"
          ? `Partial PSI candidate: publisher archive years ${result.body.scope.start_year}–${result.body.scope.end_year}; not publishable as the complete history`
          : psi && result.body.scope?.all_history
            ? "Complete sales history: annual archives from 1990 plus current weekly updates"
            : "Complete dataset: all available source records";
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
