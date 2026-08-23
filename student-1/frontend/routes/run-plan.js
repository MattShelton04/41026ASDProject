import { entity } from "../core/api.js";
import { append, button, el } from "../core/dom.js";
import { humanise } from "../core/formats.js?v=17";
import { FieldValidationError, createSubmissionGuard, isPsiJob, liveProfileLabel, parseIntegerField, parseJsonField, psiYearRange } from "../core/forms.js";
import { presentFormError } from "../components/dialogs.js";
import { technicalDetails } from "../components/layout.js?v=17";

export function createRunPlanner({ request, mutate, confirmAction }) {
  return async function openPlanDialog(job, capabilities = null, { intent = "run" } = {}) {
    let runtime = { full_data_enabled: false, connected_live_profiles: [] };
    try { runtime = (await request("runtime-capabilities")).body; } catch { /* showcase controls remain available */ }
    const wrapper = el("div", "stack");
    const isBackfill = intent === "backfill";
    const psi = isPsiJob(job);
    const importProfile = job.import_profile_key || job.import_profile;
    const gnaf = importProfile === "gnaf-nsw";
    const liveAvailable = runtime.full_data_enabled && runtime.connected_live_profiles?.includes(importProfile);
    const cachedPsiYears = psi ? runtime.cached_source_years?.["psi-sales"] || [] : [];
    const currentYear = new Date().getFullYear();
    append(wrapper, el("div", `notice ${isBackfill ? "warning" : ""}`, isBackfill
      ? "Loading earlier data starts a separate update. Published data changes only after the new version passes review."
      : "Preview the source, work and limits before starting this data update."));

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

    const profileLabel = el("label", "field");
    append(profileLabel, el("span", "", "Data source (required)"));
    const scopeProfile = el("select"); scopeProfile.name = "scope_profile"; scopeProfile.id = "scope-profile"; scopeProfile.required = true;
    const showcaseOption = el("option", "", "Example data (recommended)"); showcaseOption.value = "showcase";
    const testOption = el("option", "", "Small test sample"); testOption.value = "test";
    append(scopeProfile, showcaseOption, testOption);
    if (runtime.implemented_live_profiles?.includes(importProfile)) {
      const liveLabel = liveProfileLabel(importProfile);
      const liveOption = el("option", "", liveAvailable ? liveLabel : `${liveLabel} (not available here)`);
      liveOption.value = "full-data";
      liveOption.disabled = !liveAvailable;
      append(scopeProfile, liveOption);
    }
    scopeProfile.value = ["test", "showcase", "full-data"].includes(job.scope_json?.profile)
      && [...scopeProfile.options].some((option) => option.value === job.scope_json.profile && !option.disabled)
      ? job.scope_json.profile : "showcase";
    append(profileLabel, scopeProfile, el("small", "field-help", liveAvailable
      ? "Official source data is available. The update stops if a source file fails validation."
      : "Official source imports are disabled in this workspace. Example data never substitutes for an official-source update."));
    append(wrapper, profileLabel);

    let firstYear = null;
    let lastYear = null;
    let maximumRecords = null;
    if (psi) {
      const scopeFields = el("div", "scope-fields");
      const startingYear = Number(job.scope_json?.source_year || job.scope_json?.years?.[0] || currentYear);
      const firstLabel = el("label", "field");
      append(firstLabel, el("span", "", "First annual archive (required)"));
      firstYear = el("input"); firstYear.type = "number"; firstYear.name = "psi_start_year"; firstYear.id = "psi-start-year"; firstYear.min = "1990"; firstYear.max = String(currentYear); firstYear.step = "1"; firstYear.inputMode = "numeric"; firstYear.required = true; firstYear.value = String(scopeProfile.value === "full-data" ? 1990 : (isBackfill ? Math.max(1990, startingYear - 1) : startingYear));
      append(firstLabel, firstYear, el("small", "field-help", cachedPsiYears.length
        ? `Detected official archive years: ${cachedPsiYears.join(", ")}.`
        : "PSI years are explicit source partitions, not an opaque incremental cursor."));
      append(scopeFields, firstLabel);
      const lastLabel = el("label", "field");
      append(lastLabel, el("span", "", "Last annual archive (required)"));
      lastYear = el("input"); lastYear.type = "number"; lastYear.name = "psi_end_year"; lastYear.id = "psi-end-year"; lastYear.min = "1990"; lastYear.max = String(currentYear); lastYear.step = "1"; lastYear.inputMode = "numeric"; lastYear.required = true; lastYear.value = String(scopeProfile.value === "full-data" ? currentYear - 1 : startingYear);
      append(lastLabel, lastYear, el("small", "field-help", "Complete mode uses annual archives from 1990 through last year, then every published Monday archive in the current year."));
      append(scopeFields, lastLabel);
      append(wrapper, scopeFields);
      const syncPsiMode = () => {
        const complete = scopeProfile.value === "full-data";
        firstYear.disabled = complete;
        lastYear.disabled = complete;
        if (complete) {
          firstYear.value = "1990";
          lastYear.value = String(currentYear - 1);
        }
      };
      scopeProfile.addEventListener("change", syncPsiMode);
      syncPsiMode();
    }
    if (gnaf) {
      const limitLabel = el("label", "field");
      append(limitLabel, el("span", "", "Maximum addresses (required)"));
      maximumRecords = el("input");
      maximumRecords.type = "number";
      maximumRecords.name = "maximum_records";
      maximumRecords.id = "maximum-records";
      maximumRecords.min = "1";
      maximumRecords.max = String(Math.min(Number(job.max_rows || 50000), 50000));
      maximumRecords.step = "1";
      maximumRecords.inputMode = "numeric";
      maximumRecords.required = true;
      maximumRecords.value = String(job.scope_json?.maximum_records || 5000);
      append(limitLabel, maximumRecords, el("small", "field-help", "Only this many addresses will be included in the new version."));
      append(wrapper, limitLabel);
    }

    const advanced = el("details", "technical scope-editor");
    const scope = el("textarea"); scope.name = "advanced_scope"; scope.id = "advanced-scope"; scope.value = JSON.stringify(job.scope_json || {}, null, 2); scope.setAttribute("aria-label", "Advanced partition JSON");
    append(advanced, el("summary", "", "Advanced partition JSON (optional)"), el("p", "", "Registered partition overrides only. Complete PSI mode always selects all annual and current weekly partitions."), scope);
    append(wrapper, advanced);
    const requestedScope = () => {
      const value = parseJsonField(scope.value, "Advanced partition JSON", "advanced_scope");
      value.profile = scopeProfile.value;
      if (gnaf) {
        const maximum = Number(maximumRecords.max);
        const requested = parseIntegerField(maximumRecords.value, "Maximum addresses", { fieldName: "maximum_records", minimum: 1, maximum });
        value.maximum_records = requested;
      }
      if (!psi) return value;
      if (scopeProfile.value === "full-data") {
        delete value.maximum_records;
        delete value.years;
        value.all_history = true;
        value.include_current_weekly = true;
        value.partition_type = "annual_and_weekly";
        return value;
      }
      const start = parseIntegerField(firstYear.value, "First annual archive", { fieldName: "psi_start_year", minimum: 1990, maximum: currentYear });
      const end = parseIntegerField(lastYear?.value || firstYear.value, "Last annual archive", { fieldName: "psi_end_year", minimum: 1990, maximum: currentYear });
      if (start > end) throw new FieldValidationError("psi_end_year", "Last annual archive must be the same as or later than the first annual archive.");
      const years = psiYearRange(start, end, { maximum: currentYear + 1 });
      delete value.source_year;
      value.years = years;
      value.partition_type = "source_year";
      return value;
    };

    const preview = button("Preview update", "button secondary");
    const evidence = el("div");
    append(wrapper, preview, evidence);
    const previewGuard = createSubmissionGuard(async () => {
      evidence.replaceChildren(el("p", "", "Checking the source, limits and proposed work…"));
      try {
        const payload = { run_mode: mode.value, scope: requestedScope() };
        const result = await request(`jobs/${job.id}/plans`, { method: "POST", body: payload });
        const scopeSummary = psi && payload.scope.all_history ? "Complete sales history: annual archives from 1990 plus current weekly updates" : psi ? `${payload.scope.years.length} annual sales partition${payload.scope.years.length === 1 ? "" : "s"}: ${payload.scope.years.join(", ")}` : payload.scope.profile === "full-data" ? "Official source data" : "Example data";
        evidence.replaceChildren(el("div", "notice", `Update checked · ${scopeSummary}. Review the work and limits before starting.`), technicalDetails(result.body, "Technical plan details"));
      } catch (error) {
        evidence.replaceChildren(el("div", "notice negative", `${error.message}${error.requestId ? ` Request ID ${error.requestId}.` : ""} Your update settings are unchanged.`));
        if (error instanceof FieldValidationError && scope.form) presentFormError(scope.form, scope.form.querySelector(".form-error"), error);
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
