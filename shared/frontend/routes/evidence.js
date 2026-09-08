import { append, badge, cell, el, formatDate, formatNumber, humanise, link, notice, pageHeader, panel, requestJson, table } from "../core.js";

const REQUIRED_COPY = Object.freeze([
  "headerDescription", "releasePanelDescription", "agentPanelDescription",
  "releaseEmpty", "releaseError", "agentEmpty", "agentError", "transitionLabel",
]);
const DEFAULT_ADAPTER_TIMEOUT_MS = 350;

export class EvidenceAdapterError extends TypeError {}

function requireString(value, path) {
  if (typeof value !== "string" || !value) throw new EvidenceAdapterError(`Evidence adapter is missing ${path}.`);
}

function requireFunction(value, path) {
  if (typeof value !== "function") throw new EvidenceAdapterError(`Evidence adapter is missing ${path}().`);
}

function requireSameOriginPath(value, path, { allowHash = false } = {}) {
  requireString(value, path);
  let target;
  try {
    target = new URL(value, "https://propertyscope.invalid/");
  } catch {
    throw new EvidenceAdapterError(`Evidence adapter ${path} must be a same-origin path.`);
  }
  if (!value.startsWith("/") || value.startsWith("//") || value.includes("\\")
      || target.origin !== "https://propertyscope.invalid" || (!allowHash && target.hash)) {
    throw new EvidenceAdapterError(`Evidence adapter ${path} must be a same-origin path.`);
  }
}

function requireFeatureModulePath(feature) {
  const value = feature?.evidenceAdapterPath;
  requireSameOriginPath(value, "feature.evidenceAdapterPath");
  requireSameOriginPath(feature?.frontendBase, "feature.frontendBase");
  const target = new URL(value, "https://propertyscope.invalid/");
  const frontend = new URL(feature.frontendBase, "https://propertyscope.invalid/");
  if (target.search || target.hash || target.pathname !== value
      || !target.pathname.startsWith(frontend.pathname)) {
    throw new EvidenceAdapterError(
      "Evidence adapter module must use a canonical path inside its feature frontend namespace.",
    );
  }
  return value;
}

function requireClosed(value, names, path) {
  const unexpected = Object.keys(value).find((name) => !names.includes(name));
  if (unexpected) throw new EvidenceAdapterError(`Evidence adapter ${path} contains unsupported ${unexpected}.`);
}

/** Validate the optional, domain-neutral shell boundary without interpreting feature records. */
export function validateEvidenceAdapter(adapter) {
  if (!adapter || typeof adapter !== "object") throw new EvidenceAdapterError("Evidence adapter must be an object.");
  requireClosed(adapter, ["action", "copy", "published", "agentRuns"], "root");
  requireString(adapter.action?.label, "action.label");
  requireSameOriginPath(adapter.action?.href, "action.href", { allowHash: true });
  requireClosed(adapter.action, ["label", "href"], "action");
  for (const name of REQUIRED_COPY) requireString(adapter.copy?.[name], `copy.${name}`);
  requireClosed(adapter.copy, REQUIRED_COPY, "copy");
  for (const section of ["published", "agentRuns"]) {
    requireSameOriginPath(adapter[section]?.path, `${section}.path`);
    requireFunction(adapter[section]?.project, `${section}.project`);
    requireFunction(adapter[section]?.href, `${section}.href`);
    requireClosed(adapter[section], ["path", "project", "href"], section);
  }
  return adapter;
}

/** Load one enabled feature's manifest-declared evidence adapter without feature vocabulary. */
export async function loadEvidenceAdapter(feature, {
  importer = (path) => import(path),
  overrides = {},
  timeoutMs = DEFAULT_ADAPTER_TIMEOUT_MS,
  onLateAdapter,
  onError,
} = {}) {
  const path = requireFeatureModulePath(feature);
  const reportError = typeof onError === "function"
    ? onError
    : (error) => console.error(`Shell evidence adapter could not be loaded for ${feature?.featureKey || "unknown feature"}.`, error);
  const createAdapter = (module) => {
    if (typeof module?.createShellEvidenceAdapter !== "function") {
      throw new EvidenceAdapterError("Evidence adapter module must export createShellEvidenceAdapter().");
    }
    return validateEvidenceAdapter(module.createShellEvidenceAdapter(overrides));
  };
  let timer;
  try {
    const timedOut = Symbol("evidence-adapter-timeout");
    const modulePromise = Promise.resolve().then(() => importer(path));
    const module = await Promise.race([
      modulePromise,
      new Promise((resolve) => { timer = setTimeout(() => resolve(timedOut), timeoutMs); }),
    ]);
    if (module === timedOut) {
      const lateAdapter = modulePromise.then(createAdapter);
      if (typeof onLateAdapter === "function") lateAdapter.then(onLateAdapter).catch(reportError);
      else lateAdapter.catch(reportError);
      return null;
    }
    return createAdapter(module);
  } catch (error) {
    if (error instanceof EvidenceAdapterError) throw error;
    reportError(error);
    return null;
  } finally {
    clearTimeout(timer);
  }
}

export function projectEvidenceRows(section, body, currentHref) {
  const rows = section.project(body);
  if (!Array.isArray(rows)) {
    throw new EvidenceAdapterError("Evidence adapter project() must return an array.");
  }
  return rows.map((item) => {
    if (!item || typeof item !== "object") {
      throw new EvidenceAdapterError("Evidence adapter projected rows must be objects.");
    }
    const href = section.href(item.id, currentHref);
    requireString(href, "projected href");
    const target = new URL(href, currentHref);
    if (!/^https?:$/.test(target.protocol) || target.origin !== new URL(currentHref).origin) {
      throw new EvidenceAdapterError("Evidence adapter projected href must remain same-origin.");
    }
    return { item, href: target.href };
  });
}

function statusTone(value) {
  if (["accepted", "succeeded", "confirmed"].includes(value)) return "confirmed";
  if (["failed", "partial", "review_required"].includes(value)) return "partial";
  return "unknown";
}

function publicationCard({ item, href }, transitionLabel) {
  const card = el("article", "publication-card");
  const title = el("div", "publication-card__title");
  append(title, el("p", "ps-eyebrow", "Published reference"), el("h3", "", item.dataset), el("p", "", item.area));
  const facts = el("dl", "publication-facts");
  for (const [term, value] of [["Records", formatNumber(item.records)], ["Coverage", humanise(item.coverage)], ["Published", formatDate(item.acceptedAt)], ["Version", item.version]]) {
    const fact = el("div");
    append(fact, el("dt", "", term), el("dd", "", value));
    append(facts, fact);
  }
  const footer = el("div", "publication-card__footer");
  append(footer, el("span", "", transitionLabel), link("Inspect published record →", href, "ps-button"));
  append(card, title, facts, footer);
  return card;
}

export function createEvidenceRoute({ getEvidenceAdapters, announce, requestJson: request = requestJson }) {
  return async function renderEvidence(root) {
    const candidates = getEvidenceAdapters?.();
    const evidenceAdapters = Array.isArray(candidates)
      ? candidates.map(validateEvidenceAdapter)
      : [];
    if (!evidenceAdapters.length) {
      append(root, pageHeader("About the data", "Sources and history", "Feature evidence is temporarily unavailable while its public adapter loads."));
      append(root, notice("warning", "History unavailable", "Reload this page to retry if the feature connection remains unavailable."));
      announce("The shared evidence index is waiting for its feature provider.");
      return;
    }
    const headerDescription = evidenceAdapters.length === 1
      ? evidenceAdapters[0].copy.headerDescription
      : "See the published datasets and AI reviews exposed by each enabled research area.";
    append(root, pageHeader(
      "About the data",
      "Sources and history",
      headerDescription,
      evidenceAdapters.map((evidence) => link(evidence.action.label, evidence.action.href, "ps-button")),
    ));
    const state = el("div", "dashboard-state", "Loading current records…");
    state.setAttribute("role", "status");
    state.dataset.loadState = "loading";
    const languagePanel = panel("How statuses are used", "A missing record means that the answer is unknown, not that something is absent.");
    append(root, state, el("div", "ps-grid ps-grid-2 evidence-grid"));
    const grid = root.querySelector(".evidence-grid");
    const providers = evidenceAdapters.map((evidence) => {
      const prefix = evidenceAdapters.length === 1 ? "" : `${evidence.action.label}: `;
      const releasePanel = panel(`${prefix}Published datasets`, evidence.copy.releasePanelDescription);
      const agentPanel = panel(`${prefix}AI review history`, evidence.copy.agentPanelDescription);
      append(grid, releasePanel.card, agentPanel.card);
      return { evidence, releasePanel, agentPanel };
    });
    append(root, languagePanel.card);
    const definitions = el("dl", "evidence-definitions");
    for (const [label, tone, detail] of [
      ["Confirmed", "confirmed", "Supported by a published source and version."],
      ["Partial", "partial", "Some information is available, with limitations shown."],
      ["Stale", "partial", "Evidence has an observed or effective date that needs attention."],
      ["Unknown", "unknown", "No supported conclusion can be made from current evidence."],
    ]) {
      const item = el("div");
      append(item, el("dt", "", ""), badge(label, tone), el("dd", "", detail));
      append(definitions, item);
    }
    append(languagePanel.body, definitions);

    const results = await Promise.all(providers.map(async (provider) => ({
      ...provider,
      settled: await Promise.allSettled([
        request(provider.evidence.published.path),
        request(provider.evidence.agentRuns.path),
      ]),
    })));
    const settledResults = results.flatMap((result) => result.settled);
    const cancellation = settledResults
      .find((item) => item.status === "rejected" && item.reason?.name === "AbortError");
    if (cancellation) throw cancellation.reason;
    let failureCount = settledResults.filter((item) => item.status === "rejected").length;

    for (const { evidence, releasePanel, agentPanel, settled } of results) {
      const copy = evidence.copy;
      const [releasesResult, runsResult] = settled;
      if (releasesResult.status === "fulfilled") {
        try {
          const releases = projectEvidenceRows(evidence.published, releasesResult.value.body, window.location.href);
          if (releases.length) {
            const publications = el("div", "publication-list");
            // Lead with the provider's first reference; the complete index stays directly below.
            append(publications, publicationCard(releases[0], copy.transitionLabel));
            append(releasePanel.body, publications);
          }
          if (releases.length) append(releasePanel.body, table(["Dataset", "Research area", "Published version", "Records", "Coverage", "Published"], releases, ({ item, href }) => {
            const tr = el("tr");
            const dataset = el("div", "table-primary");
            append(dataset, link(item.dataset, href), el("span", "table-secondary area-transition-label", copy.transitionLabel), el("code", "table-secondary mono", typeof item.hash === "string" && item.hash ? `${item.hash.slice(0, 12)}…` : "Hash unknown"));
            append(tr, cell(dataset), cell(item.area), cell(item.version, "mono"), cell(formatNumber(item.records), "numeric"), cell(badge(humanise(item.coverage), statusTone(item.coverage))), cell(formatDate(item.acceptedAt)));
            return tr;
          }, "Published dataset references"));
          else append(releasePanel.body, notice("info", "No published references", copy.releaseEmpty));
        } catch {
          failureCount += 1;
          append(releasePanel.body, notice("warning", "Published data projection unavailable", `${copy.releaseError} The feature adapter returned unsupported evidence.`));
        }
      } else append(releasePanel.body, notice("warning", "Published data index unavailable", `${copy.releaseError} Request ID: ${releasesResult.reason.requestId || "not supplied"}.`));

      if (runsResult.status === "fulfilled") {
        try {
          const runs = projectEvidenceRows(evidence.agentRuns, runsResult.value.body, window.location.href);
          if (runs.length) append(agentPanel.body, table(["Run", "Area", "Objective", "State", "Updated"], runs, ({ item, href }) => {
            const tr = el("tr");
            const identifier = typeof item.id === "string" ? item.id.slice(0, 8) : "Unknown";
            append(tr, cell(link(identifier, href, "mono"), "primary-cell"), cell(item.area), cell(item.objective), cell(badge(humanise(item.status), statusTone(item.status))), cell(formatDate(item.updatedAt)));
            return tr;
          }, "AI review references"));
          else append(agentPanel.body, notice("info", "No assisted activity", copy.agentEmpty));
        } catch {
          failureCount += 1;
          append(agentPanel.body, notice("warning", "Activity projection unavailable", `${copy.agentError} The feature adapter returned unsupported evidence.`));
        }
      } else append(agentPanel.body, notice("warning", "Activity index unavailable", `${copy.agentError} Request ID: ${runsResult.reason.requestId || "not supplied"}.`));
    }
    state.replaceChildren(notice(failureCount ? "warning" : "success", failureCount ? "Some history is unavailable" : "Sources and history loaded", failureCount ? "Available sections are still shown. Try again later for anything missing." : "Current records loaded."));
    state.dataset.loadState = "settled";
    announce(failureCount ? "The shared evidence index loaded with unavailable providers." : "The shared evidence index loaded current references.");
  };
}
