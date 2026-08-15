import { entity } from "../core/api.js";
import { append, button, el } from "../core/dom.js";
import { humanise } from "../core/formats.js";
import { isPsiJob, liveProfileLabel, parseJsonField, psiYearRange } from "../core/forms.js";
import { technicalDetails } from "../components/layout.js";

export function createRunPlanner({ request, mutate, confirmAction, showToast }) {
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
      ? "Backfill creates a new full-refresh run for an explicit bounded scope. Accepted data is not replaced until a candidate passes review and publication."
      : "Run now creates a durable run from this registered job. Preview the deterministic task plan before launch."));

    const modeLabel = el("label", "field");
    append(modeLabel, el("span", "", "Run mode"));
    const mode = el("select"); mode.name = "run_mode";
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
    append(profileLabel, el("span", "", "Acquisition data"));
    const scopeProfile = el("select"); scopeProfile.name = "scope_profile";
    const showcaseOption = el("option", "", "Deterministic showcase records"); showcaseOption.value = "showcase";
    const testOption = el("option", "", "Small deterministic test records"); testOption.value = "test";
    append(scopeProfile, showcaseOption, testOption);
    if (runtime.implemented_live_profiles?.includes(importProfile)) {
      const liveLabel = liveProfileLabel(importProfile);
      const liveOption = el("option", "", liveAvailable ? liveLabel : `${liveLabel} requires --full-data`);
      liveOption.value = "full-data";
      liveOption.disabled = !liveAvailable;
      append(scopeProfile, liveOption);
    }
    scopeProfile.value = ["test", "showcase", "full-data"].includes(job.scope_json?.profile)
      && [...scopeProfile.options].some((option) => option.value === job.scope_json.profile && !option.disabled)
      ? job.scope_json.profile : "showcase";
    append(profileLabel, scopeProfile, el("small", "field-help", liveAvailable
      ? "Live acquisition captures every record in the selected source partitions; archive safety checks fail the run instead of truncating it."
      : "Live acquisition is available only for connected sources in the explicit --full-data stack; fixtures are never substituted silently."));
    append(wrapper, profileLabel);

    let firstYear = null;
    let lastYear = null;
    let maximumRecords = null;
    if (psi) {
      const scopeFields = el("div", "scope-fields");
      const startingYear = Number(job.scope_json?.source_year || job.scope_json?.years?.[0] || currentYear);
      const firstLabel = el("label", "field");
      append(firstLabel, el("span", "", "First annual archive"));
      firstYear = el("input"); firstYear.type = "number"; firstYear.name = "psi_start_year"; firstYear.min = "1990"; firstYear.max = String(currentYear); firstYear.required = true; firstYear.value = String(scopeProfile.value === "full-data" ? 1990 : (isBackfill ? Math.max(1990, startingYear - 1) : startingYear));
      append(firstLabel, firstYear, el("small", "field-help", cachedPsiYears.length
        ? `Detected official archive years: ${cachedPsiYears.join(", ")}.`
        : "PSI years are explicit source partitions, not an opaque incremental cursor."));
      append(scopeFields, firstLabel);
      const lastLabel = el("label", "field");
      append(lastLabel, el("span", "", "Last annual archive"));
      lastYear = el("input"); lastYear.type = "number"; lastYear.name = "psi_end_year"; lastYear.min = "1990"; lastYear.max = String(currentYear); lastYear.required = true; lastYear.value = String(scopeProfile.value === "full-data" ? currentYear - 1 : startingYear);
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
      append(limitLabel, el("span", "", "Maximum addresses"));
      maximumRecords = el("input");
      maximumRecords.type = "number";
      maximumRecords.name = "maximum_records";
      maximumRecords.min = "1";
      maximumRecords.max = String(Math.min(Number(job.max_rows || 50000), 50000));
      maximumRecords.required = true;
      maximumRecords.value = String(job.scope_json?.maximum_records || 5000);
      append(limitLabel, maximumRecords, el("small", "field-help", "The live bulk archive is streamed once, but only this bounded number of addresses enters the candidate release."));
      append(wrapper, limitLabel);
    }

    const advanced = el("details", "technical scope-editor");
    const scope = el("textarea"); scope.value = JSON.stringify(job.scope_json || {}, null, 2); scope.setAttribute("aria-label", "Advanced partition JSON");
    append(advanced, el("summary", "", "Advanced partition JSON"), el("p", "", "Registered partition overrides only. Complete PSI mode always selects all annual and current weekly partitions."), scope);
    append(wrapper, advanced);
    const requestedScope = () => {
      const value = parseJsonField(scope.value, "Scope");
      value.profile = scopeProfile.value;
      if (gnaf) {
        const requested = Number(maximumRecords.value);
        const maximum = Number(maximumRecords.max);
        if (!Number.isInteger(requested) || requested < 1 || requested > maximum) throw new Error(`Maximum addresses must be between 1 and ${maximum}.`);
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
      const years = psiYearRange(firstYear.value, lastYear?.value || firstYear.value, { maximum: currentYear + 1 });
      delete value.source_year;
      value.years = years;
      value.partition_type = "source_year";
      return value;
    };

    const preview = button("Preview deterministic plan", "button secondary");
    const evidence = el("div");
    append(wrapper, preview, evidence);
    preview.addEventListener("click", async () => {
      preview.disabled = true;
      evidence.replaceChildren(el("p", "", "Validating limits and proposed work…"));
      try {
        const payload = { run_mode: mode.value, scope: requestedScope() };
        const result = await request(`jobs/${job.id}/plans`, { method: "POST", body: payload });
        const scopeSummary = psi && payload.scope.all_history ? "Complete PSI history: annual archives from 1990 plus current weekly updates" : psi ? `${payload.scope.years.length} PSI annual partition${payload.scope.years.length === 1 ? "" : "s"}: ${payload.scope.years.join(", ")}` : payload.scope.profile === "full-data" ? "Live registered source" : "Deterministic bounded scope";
        evidence.replaceChildren(el("div", "notice", `Plan validated · ${scopeSummary}. Review task, cache/network work and limits before launch.`), technicalDetails(result.body, "Plan evidence"));
      } catch (error) { evidence.replaceChildren(el("div", "notice negative", `${error.message} Request ID ${error.requestId}`)); }
      finally { preview.disabled = false; }
    });
    const confirmed = await confirmAction({ title: `${isBackfill ? "Backfill" : "Run"} ${job.name}?`, description: "A durable run will be created with a new idempotency key. The runner processes it independently.", label: isBackfill ? "Start backfill" : "Launch run", tone: "primary", extra: wrapper });
    if (!confirmed) return;
    try {
      const body = await mutate(`jobs/${job.id}/runs`, { body: { run_mode: mode.value, scope: requestedScope() }, success: isBackfill ? "Backfill requested" : "Run requested" });
      const run = entity(body, "run");
      location.hash = `#runs/${run.id}`;
    } catch (error) { showToast(`${error.message} Request ID ${error.requestId}`); }
  };
}
