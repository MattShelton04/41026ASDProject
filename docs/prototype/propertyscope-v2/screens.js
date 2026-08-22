import {
  icon, escapeHtml, route, button, iconButton, badge, tag, releaseChip,
  screenHeader, panel, card, metricCard, notice, evidenceState, field, table,
  propertyHero, mapFrame, barChart, lineChart, sparkline, timeline, agentLoop,
  toolCall, lineage, featureCard, quickAction, coverageState, emptyState,
} from "./components.js";
import {
  properties, sources, jobs, runs, releases, qualityRules, artifacts, coverage,
  saleHistory, comparables, crimeCategories, planningFacts, buyerPriorities,
  followups, agentRuns, groundedCitations, roadmap,
} from "./data.js";

const primaryProperty = properties[0];
const statusLabel = (value) => value === "success" ? "Succeeded" : value === "failed" ? "Failed" : value === "warning" ? "Warning" : value === "review" ? "Review" : value === "active" ? "Active" : value === "draft" ? "Draft" : value;
const evidenceLabel = (value) => value === "confirmed" ? "Confirmed" : value === "partial" ? "Partial" : value === "conflicting" ? "Conflicting" : "Unknown";
const apiPill = (text) => `<span class="mono tag">${escapeHtml(text)}</span>`;

function toolbar({ search = "Search", controls = "", actions = "" } = {}) {
  return `<div class="toolbar"><div class="toolbar-fields">${search ? field({ label: "Search", type: "search", placeholder: search, className: "search" }) : ""}${controls}</div><div class="cluster">${actions}</div></div>`;
}

function propertyResults(selected = primaryProperty.ref) {
  return `<div class="property-result-list">${properties.map((property) => `<a class="property-result ${property.ref === selected ? "selected" : ""}" href="#/property" data-route="property">
    <span class="property-result-icon">${icon("house")}</span>
    <span><strong>${escapeHtml(property.address)}</strong><span>${escapeHtml(`${property.type} · ${property.match}`)}</span></span>
    <span class="property-result-meta"><strong>${escapeHtml(property.askingPrice)}</strong><span>${escapeHtml(property.freshness)}</span></span>
  </a>`).join("")}</div>`;
}

function coverageTiles() {
  const tiles = [
    ["Property identity", "confirmed", "8 source records", "building"],
    ["Market evidence", "confirmed", "4 recorded sales", "trend"],
    ["Suburb context", "confirmed", "Crime + schools", "map"],
    ["Planning & site", "partial", "Flood needs verification", "layers"],
    ["Buyer workspace", "confirmed", "5 priorities tracked", "briefcase"],
  ];
  return `<div class="coverage-grid">${tiles.map(([label, state, detail, iconName]) => `<div class="coverage-tile"><span class="coverage-tile-icon">${icon(iconName)}</span><strong>${escapeHtml(label)}</strong><span>${escapeHtml(detail)}</span>${badge(evidenceLabel(state), state, "no-dot")}</div>`).join("")}</div>`;
}

function healthGrid() {
  const services = [
    ["Shared shell", "Healthy", "18 ms", 98, "success"],
    ["Feature 1 API", "Healthy", "42 ms", 94, "success"],
    ["PostgreSQL / PostGIS", "Healthy", "11 ms", 99, "success"],
    ["OpenAI · GPT-5.6 Luna", "Ready", "1 model", 87, "success"],
    ["MCP server", "Designed", "R1 local", 38, "warning"],
    ["RAG server", "Designed", "R1 local", 32, "warning"],
    ["Multi-agent", "Designed", "R2 local", 14, "warning"],
    ["Cloud deployment", "Not deployed", "R2", 4, "unknown"],
  ];
  return `<div class="health-grid">${services.map(([name, status, detail, progress, state]) => `<article class="health-card"><div class="health-card-head"><strong>${escapeHtml(name)}</strong>${badge(status, state, "no-dot")}</div><p>${escapeHtml(detail)}</p><div class="progress-bar ${state === "warning" ? "warning" : ""}"><span style="width:${progress}%"></span></div></article>`).join("")}</div>`;
}

function evidenceDefinitions() {
  return `<div class="stack">
    ${evidenceState("confirmed", "Confirmed", "Supported by a current, attributable source and a valid property match.")}
    ${evidenceState("partial", "Partial", "Some relevant evidence exists, but coverage or interpretation is incomplete.")}
    ${evidenceState("conflicting", "Conflicting", "Sources disagree or refer to incompatible identities, periods, or definitions.")}
    ${evidenceState("unknown", "Unknown", "No supported evidence is available in the bounded corpus. Not the same as ‘no’. ")}
  </div>`;
}

function architectureDiagram(release = 0) {
  const services = [
    { title: "Shared shell", detail: "Navigation + design system", icon: "home" },
    { title: "Feature APIs", detail: "Flask REST boundaries", icon: "server" },
    { title: "Databases", detail: "Independently owned", icon: "database" },
    { title: "AI-mode", detail: "OpenAI Responses API", icon: "bot" },
  ];
  if (release >= 1) services.push({ title: "MCP + RAG", detail: "Local grounded context", icon: "book" });
  if (release >= 2) services.push({ title: "Multi-agent", detail: "Planner / Worker / Reviewer", icon: "users" });
  services.push({ title: release >= 2 ? "Local + cloud" : "Docker Compose", detail: release >= 2 ? "Cloud uses AI-mode only" : "Integrated runtime", icon: release >= 2 ? "cloud" : "box" });
  return lineage(services);
}

function featureHome() {
  return `
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">NSW property research, with the evidence left attached</p>
        <h1 class="display-title">Research a property.<br>See what is known.</h1>
        <p class="lede">PropertyScope brings property identity, market evidence, suburb context, planning signals and buyer follow-ups into one bounded research workspace. It shows coverage, provenance and uncertainty instead of pretending every question has an answer.</p>
        <div class="hero-actions">${button("Explore NSW properties", { kind: "inverse-strong", iconName: "search", route: "explore" })}${button("Open data operations", { kind: "inverse", iconName: "database", route: "data-overview" })}</div>
        <div class="cluster" style="margin-top:1rem">${badge("Release 0 prototype", "live", "no-dot")}${tag("Non-government service")}${tag("Evidence-first")}</div>
      </div>
      <div class="hero-card">
        <div class="cluster-between"><div><p class="eyebrow">Start with an address</p><h2 style="margin-bottom:.25rem">Property research</h2></div>${badge("8 sources ready", "confirmed", "no-dot")}</div>
        <label class="field" style="margin-top:.8rem"><span>Search address, suburb or PropertyScope reference</span><div class="search-composer"><input class="input" value="12 Example Street, Parramatta NSW" aria-label="Property search"><a class="button primary" href="#/property" data-route="property">${icon("search")}Research</a></div></label>
        <div class="stack" style="margin-top:.75rem;gap:.45rem">${evidenceState("confirmed", "Identity matched", "G-NAF property reference and address match")}${evidenceState("partial", "Planning coverage", "Selected council layers; verify flood interpretation")}${evidenceState("unknown", "Building records", "No supported match in current bounded corpus")}</div>
      </div>
    </section>

    <div class="cluster-between" style="margin:1.3rem 0 .7rem"><div><p class="eyebrow">One platform, five owned features</p><h2>Research workflow</h2></div>${route("release-roadmap", "View release roadmap", { className: "text-link", iconName: "arrowRight" })}</div>
    <div class="grid grid-5">
      ${featureCard({ number: 1, title: "Data & discovery", description: "Source registry, ingestion jobs, release evidence and verified NSW property identity.", route: "data-overview", iconName: "database", status: "Implemented", release: "R0–R2", owner: "Feature 1" })}
      ${featureCard({ number: 2, title: "Market intelligence", description: "Recorded sale history, transparent comparable selection and bounded market cases.", route: "market-cases", iconName: "trend", status: "Prototype", release: "R0–R2", owner: "Feature 2" })}
      ${featureCard({ number: 3, title: "Suburb context", description: "Crime trends, schools and comparison views with clear count, rate and coverage semantics.", route: "suburb-comparison", iconName: "map", status: "Prototype", release: "R0–R2", owner: "Feature 3" })}
      ${featureCard({ number: 4, title: "Site due diligence", description: "Planning, environmental and building evidence separated from professional verification.", route: "site-reviews", iconName: "layers", status: "Prototype", release: "R0–R2", owner: "Feature 4" })}
      ${featureCard({ number: 5, title: "Buyer workspace", description: "Shortlists, evidence dossiers, review queues and stakeholder follow-up tasks.", route: "buyer-workspace", iconName: "briefcase", status: "Prototype", release: "R0–R2", owner: "Feature 5" })}
    </div>

    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "System readiness", description: "Shared services and release-gated capabilities", body: healthGrid(), footer: `<span class="muted">Local prototype state · no live service checks</span>${route("system-status", "Open system status", { className: "text-link" })}` })}
      ${panel({ title: "Quick paths", description: "High-value demonstration journeys", body: `<div class="stack" style="gap:.55rem">${quickAction({ title: "Research a property", description: "Identity → evidence → dossier", route: "property", iconName: "house" })}${quickAction({ title: "Review a failed release", description: "Quality gate → AI diagnosis", route: "release-review", iconName: "alert" })}${quickAction({ title: "Inspect an agent run", description: "Plan → Act → Observe → Adapt", route: "agent-run", iconName: "workflow" })}</div>` })}
    </div>
  `;
}

function exploreScreen() {
  return `
    ${screenHeader({ eyebrow: "Shared property discovery", title: "Explore NSW properties", description: "Resolve addresses to a stable PropertyScope reference before opening feature evidence. Search results distinguish verified, high-confidence and unresolved identity matches.", actions: button("Data coverage", { route: "coverage", iconName: "layers" }), meta: `${badge("4 showcase results", "confirmed")}${tag("G-NAF backed identity")}` })}
    ${toolbar({ search: "Search address, suburb or reference", controls: `${field({ label: "Property type", type: "select", value: "All types", options: ["All types", "Detached house", "Townhouse", "Apartment"] })}${field({ label: "Evidence coverage", type: "select", value: "Any coverage", options: ["Any coverage", "Confirmed only", "Has partial evidence"] })}`, actions: `${button("Map", { kind: "primary", iconName: "map", size: "small" })}${button("List", { kind: "secondary", iconName: "list", size: "small" })}` })}
    <div class="grid grid-map-list">
      ${panel({ title: "Results", description: "Stable identities, not listing duplicates", body: propertyResults(), footer: `<span class="muted">Showing 4 of 4 showcase identities</span>${button("Save search", { kind: "ghost", iconName: "bookmark", size: "small" })}` })}
      ${mapFrame({ properties, selected: primaryProperty.ref, legend: `<strong>Evidence coverage</strong><div class="legend-row"><span class="legend-swatch confirmed"></span>Verified identity</div><div class="legend-row"><span class="legend-swatch partial"></span>High-confidence match</div>` })}
    </div>
  `;
}

function propertyScreen() {
  return `
    ${propertyHero(primaryProperty, `${button("Add to shortlist", { kind: "primary", iconName: "bookmark", route: "shortlist" })}${button("Build dossier", { kind: "secondary", iconName: "file", route: "dossier-builder" })}`)}
    <div class="section-gap">${coverageTiles()}</div>
    <div class="grid grid-wide-aside section-gap">
      <div class="stack">
        ${panel({ title: "Evidence snapshot", description: "What the current accepted releases support", body: `<div class="grid grid-3">${metricCard({ label: "Latest recorded sale", value: "$1.21m", foot: "May 2026 · exact address", footState: "positive", iconName: "trend" })}${metricCard({ label: "Comparable evidence", value: "3", foot: "Included within current rules", iconName: "scales" })}${metricCard({ label: "Open follow-ups", value: "4", foot: "2 need professional verification", footState: "warning", iconName: "clipboard" })}</div><div class="section-gap">${notice({ state: "warning", iconName: "alert", title: "Flood evidence is partial", body: "A mapped study is available, but the interpretation should be confirmed with council, a conveyancer or a qualified professional." })}</div>` })}
        ${panel({ title: "Sale history", description: "Recorded transactions attached to the verified property identity", actions: route("market-detail", "Open market case", { className: "text-link" }), body: table({ columns: [
          { label: "Sale date", key: "date" }, { label: "Price", render: (r) => `<strong>${escapeHtml(r.price)}</strong>` }, { label: "Record class", key: "class" }, { label: "Identity match", render: (r) => badge(r.match, "confirmed", "no-dot") }, { label: "Evidence", key: "source" },
        ], rows: saleHistory }) })}
      </div>
      <div class="stack">
        ${mapFrame({ properties: [primaryProperty], selected: primaryProperty.ref, compact: true, overlays: ["flood"], legend: `<strong>Selected layers</strong><div class="legend-row"><span class="legend-swatch partial"></span>Flood study coverage</div>` })}
        ${panel({ title: "Evidence state", description: "Consistent language across every feature", body: evidenceDefinitions() })}
      </div>
    </div>
  `;
}

function systemStatusScreen() {
  return `
    ${screenHeader({ eyebrow: "Shared operations", title: "System status", description: "A single place to understand application readiness, dependency boundaries and the deliberate difference between local and cloud release modes.", actions: `${button("Refresh status", { kind: "primary", iconName: "refresh" })}${button("Architecture", { route: "release-roadmap", iconName: "workflow" })}`, meta: `${badge("Local mode", "live")}${tag("Prototype telemetry")}` })}
    ${notice({ state: "info", title: "Prototype status values are representative", body: "The full HTML prototype is static. The implementation blueprint maps these cards to health endpoints and Compose service checks." })}
    <div class="section-gap">${healthGrid()}</div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Release 0 topology", description: "Required integrated path for the first showcase", body: architectureDiagram(0), footer: `${apiPill("frontend → API → OpenAI LLM")}<span class="muted">MCP/RAG/multi-agent remain release-gated</span>` })}
      ${panel({ title: "Deployment mode", description: "Capability gating is explicit", body: `<div class="stack">${evidenceState("confirmed", "Local · Release 0", "AI-mode and OpenAI provider enabled")}${evidenceState("partial", "Local · Release 1/2", "MCP, RAG and multi-agent designed but not active")}${evidenceState("unknown", "Cloud · Release 2", "Not yet deployed; MCP/RAG/multi-agent must be disabled")}</div>` })}
    </div>
    ${panel({ title: "Service contracts", description: "What the shell depends on, without sharing feature databases", body: table({ columns: [
      { label: "Capability", key: "name" }, { label: "Owner", key: "owner" }, { label: "Endpoint / contract", render: (r) => apiPill(r.endpoint) }, { label: "Readiness", render: (r) => badge(r.status, r.state, "no-dot") }, { label: "Failure UX", key: "failure" },
    ], rows: [
      { name: "Property identity search", owner: "Feature 1", endpoint: "GET /api/data-platform/properties", status: "Ready", state: "success", failure: "Keep search usable; show bounded unavailable state" },
      { name: "AI-mode run", owner: "Shared AI", endpoint: "POST /api/ai-mode/runs", status: "Ready", state: "success", failure: "Trace retained; deterministic timeout message" },
      { name: "Market case", owner: "Feature 2", endpoint: "GET /api/market/cases/:id", status: "Planned", state: "planned", failure: "No fabricated valuation; evidence unavailable" },
      { name: "Grounded answer", owner: "Shared AI", endpoint: "POST /api/grounded/answers", status: "Release 1", state: "planned", failure: "Separate retrieval failure from model failure" },
      { name: "Dossier run", owner: "Feature 5", endpoint: "POST /api/dossiers/:id/runs", status: "Planned", state: "planned", failure: "Keep draft and completed evidence sections" },
    ] }) })}
  `;
}

function agentRunsScreen() {
  return `
    ${screenHeader({ eyebrow: "Shared AI operations", title: "Agent runs", description: "Every assisted operation exposes its objective, bounded tools, phase, evidence and review state. A polished UI does not hide the Plan → Act → Observe → Adapt loop.", actions: button("New assisted task", { kind: "primary", iconName: "sparkles", route: "ai-diagnosis" }), meta: `${badge("4 recent runs", "info")}${tag("Qwen 2.5 3B")}` })}
    ${toolbar({ search: "Search objective or run ID", controls: `${field({ label: "Feature", type: "select", value: "All features", options: ["All features", "Feature 1", "Feature 2", "Feature 3", "Feature 4", "Feature 5"] })}${field({ label: "State", type: "select", value: "Any state", options: ["Any state", "Complete", "Human review", "Failed"] })}`, actions: button("Export trace", { iconName: "download", size: "small" }) })}
    ${panel({ title: "Run ledger", description: "Shared immutable execution summaries", body: table({ columns: [
      { label: "Run", render: (r) => `<a class="row-link mono" href="#/agent-run" data-route="agent-run">${escapeHtml(r.id)}</a><span class="table-secondary">${escapeHtml(r.started)}</span>` },
      { label: "Objective", render: (r) => `<span class="table-primary">${escapeHtml(r.objective)}</span><span class="table-secondary">${escapeHtml(r.feature)}</span>` },
      { label: "Phase", key: "phase" }, { label: "Tools", key: "tools" }, { label: "Model", key: "model" }, { label: "Elapsed", key: "elapsed" }, { label: "Status", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") },
    ], rows: agentRuns }) })}
  `;
}

function agentRunScreen() {
  return `
    ${screenHeader({ eyebrow: "Agent run · AGT-2041", title: "Diagnose failed crime release", description: "Propose the safest recovery while preserving the prior accepted release and requiring a human decision before publication.", actions: `${button("Approve recovery", { kind: "primary", iconName: "check" })}${button("Reject", { kind: "secondary", iconName: "x" })}`, meta: `${badge("Human review", "review")}${tag("5 tool calls")}${tag("38 seconds")}` })}
    ${agentLoop("adapt", { plan: "Inspect candidate release, predecessor and quality policy.", act: "Read structured evidence and recovery runbook.", observe: "Blocking month-continuity rule failed.", adapt: "Retain predecessor; propose cached reprocess after verification." })}
    <div class="grid grid-wide-aside section-gap">
      <div class="stack">
        ${panel({ title: "Recommended action", description: "Reviewer-visible output, not an autonomous publication", body: `${notice({ state: "warning", title: "Do not accept candidate 2026.06-candidate.2", body: "The November 2025 month is absent. Keep 2026.05.1 as the accepted Feature 3 release, verify the source archive, then reprocess the cached acquisition." })}<div class="grid grid-3 section-gap">${metricCard({ label: "Confidence", value: "High", foot: "3 corroborating evidence items", iconName: "shield" })}${metricCard({ label: "Affected target", value: "Feature 3", foot: "Current release remains available", iconName: "map" })}${metricCard({ label: "Recovery risk", value: "Low", foot: "No destructive overwrite", footState: "positive", iconName: "refresh" })}</div>` })}
        ${panel({ title: "Tool trace", description: "Inputs and outputs are inspectable", body: `${toolCall({ name: "data.get_release", detail: "REL-CRIME-2026-06-C → 11 / 12 months", meta: "42 ms" })}${toolCall({ name: "data.get_quality_results", detail: "1 blocking failure, 2 warnings, 3 passes", meta: "31 ms" })}${toolCall({ name: "data.get_accepted_predecessor", detail: "2026.05.1 remains imported by Feature 3", meta: "28 ms" })}${toolCall({ name: "rag.search_runbook", detail: "Retrieved BOCSAR recovery procedure · section 3", meta: "61 ms" })}${toolCall({ name: "policy.propose_recovery", detail: "Human approval required for any release-state change", meta: "19 ms" })}` })}
      </div>
      <div class="stack">
        ${panel({ title: "Execution timeline", body: timeline([
          { title: "Objective received", detail: "Scope and non-destructive constraints parsed", time: "10:47:02", state: "success", icon: "target" },
          { title: "Evidence gathered", detail: "Candidate, quality results and predecessor loaded", time: "10:47:11", state: "success", icon: "database" },
          { title: "Runbook retrieved", detail: "One relevant passage selected", time: "10:47:24", state: "success", icon: "book" },
          { title: "Recommendation drafted", detail: "Recovery plan and uncertainty recorded", time: "10:47:35", state: "success", icon: "edit" },
          { title: "Human review", detail: "No state-changing tool has been invoked", time: "Now", state: "warning", icon: "user" },
        ]) })}
        ${panel({ title: "Guardrails", body: `<div class="stack">${evidenceState("confirmed", "Bounded tools", "Read-only evidence tools used during reasoning")}${evidenceState("confirmed", "No silent fallback", "MCP and RAG evidence paths shown separately")}${evidenceState("confirmed", "Human gate", "Release acceptance remains a reviewer action")}</div>` })}
      </div>
    </div>
  `;
}

function evidenceScreen() {
  const rows = [
    { id: "EVD-PROP-21489", claim: "Address resolves to PS-NSW-00021489", source: "G-NAF Open NSW · 2026.05", feature: "Feature 1", state: "confirmed", fresh: "12 Aug" },
    { id: "EVD-SALE-88710", claim: "Recorded sale of $1,210,000 in May 2026", source: "NSW PSI · 2026 partition", feature: "Feature 2", state: "confirmed", fresh: "8 Aug" },
    { id: "EVD-CRIME-412", claim: "Parramatta crime series available through May 2026", source: "BOCSAR · accepted 2026.05.1", feature: "Feature 3", state: "confirmed", fresh: "22 Jul" },
    { id: "EVD-FLOOD-86", claim: "Flood study coverage exists; point interpretation incomplete", source: "Council study · Feb 2026", feature: "Feature 4", state: "partial", fresh: "7 Aug" },
    { id: "EVD-BLDG-00", claim: "No supported building-record match", source: "Bounded Feature 4 corpus", feature: "Feature 4", state: "unknown", fresh: "7 Aug" },
  ];
  return `
    ${screenHeader({ eyebrow: "Shared evidence model", title: "Evidence ledger", description: "Claims remain attached to source version, identity, feature owner, freshness and an explicit evidence state. ‘Unknown’ never silently becomes ‘no’. ", actions: button("Export evidence", { iconName: "download" }), meta: `${badge("5 showcase claims", "info")}${tag("Source-attributed")}` })}
    <div class="grid grid-main-aside">
      ${panel({ title: "Evidence claims", description: "Reusable across property views, AI answers and dossiers", body: table({ columns: [
        { label: "Evidence", render: (r) => `<span class="mono table-primary">${escapeHtml(r.id)}</span><span class="table-secondary">${escapeHtml(r.feature)}</span>` }, { label: "Supported claim", key: "claim" }, { label: "Source", key: "source" }, { label: "Fresh", key: "fresh" }, { label: "State", render: (r) => badge(evidenceLabel(r.state), r.state, "no-dot") },
      ], rows }) })}
      ${panel({ title: "Evidence language", description: "One system-wide contract", body: evidenceDefinitions() })}
    </div>
    <div class="section-gap">${panel({ title: "Lineage example", description: "A claim can be traced from source acquisition to user-facing interpretation", body: lineage([
      { title: "Source file", detail: "Published archive", icon: "file" }, { title: "Artifact", detail: "Checksum recorded", icon: "box" }, { title: "Normalise", detail: "Typed schema", icon: "workflow" }, { title: "Quality gate", detail: "Rules + samples", icon: "shield" }, { title: "Release", detail: "Accepted version", icon: "bookmark" }, { title: "Evidence", detail: "Claim + source", icon: "link" }, { title: "View / AI", detail: "Cited output", icon: "eye" },
    ]) })}</div>
  `;
}

function releaseRoadmapScreen() {
  return `
    ${screenHeader({ eyebrow: "Full-semester product architecture", title: "Release roadmap", description: "The product is designed once for all three releases, while deployment and AI capabilities remain visibly gated. This avoids a Release 0 dead end without pretending future services already exist.", actions: button("System status", { route: "system-status", iconName: "activity" }), meta: `${releaseChip("R0", "Foundations")}${releaseChip("R1", "Grounded")}${releaseChip("R2", "Multi-agent + cloud")}` })}
    <div class="grid grid-3">${roadmap.map((item, index) => card(`<div class="cluster-between"><span class="feature-number">${icon(index === 0 ? "box" : index === 1 ? "book" : "cloud")}</span>${badge(item.status, index === 0 ? "live" : "planned", "no-dot")}</div><p class="eyebrow" style="margin-top:.9rem">${escapeHtml(item.release)} · ${escapeHtml(item.date)}</p><h2>${escapeHtml(item.label)}</h2><ul class="clean-list">${item.capabilities.map((cap) => `<li>${icon("check")}<span>${escapeHtml(cap)}</span></li>`).join("")}</ul>`, index === 0 ? "tint-ocean" : index === 1 ? "" : "tint-sand")).join("")}</div>
    <div class="stack section-gap">
      ${panel({ title: "Release 0 · integrated foundations", description: "Local only — five slices, AI-mode and shared agent loop", body: architectureDiagram(0) })}
      ${panel({ title: "Release 1 · grounded intelligence", description: "Local only — Release 0 plus separate MCP and RAG services", body: architectureDiagram(1) })}
      ${panel({ title: "Release 2 · multi-agent and cloud", description: "Local has all services; cloud deliberately disables MCP, RAG and multi-agent", body: architectureDiagram(2), footer: `${notice({ state: "warning", title: "Cloud capability gate", body: "The cloud deployment enables AI-mode and its remote LLM provider only. MCP, RAG and multi-agent remain disabled." })}` })}
    </div>
  `;
}

// Feature 1 — Data Platform, Provenance and Property Discovery
function dataOverviewScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Data platform", title: "Data operations overview", description: "Operate data sources, ingestion jobs, artifacts, quality gates and accepted releases that the rest of PropertyScope consumes. Feature 1 owns evidence reliability, not the business interpretation of every downstream feature.", actions: `${button("Plan a run", { kind: "primary", iconName: "play", route: "run-plan" })}${button("Register source", { iconName: "plus", route: "sources" })}`, meta: `${badge("Feature 1 implemented", "live")}${tag("PostgreSQL / PostGIS")}${tag("CRUD + AI-mode")}` })}
    <div class="grid grid-4">${metricCard({ label: "Registered sources", value: "8", foot: "6 active · 2 draft", iconName: "database" })}${metricCard({ label: "Accepted releases", value: "4", foot: "Across Features 1–3", footState: "positive", iconName: "bookmark" })}${metricCard({ label: "Runs · 7 days", value: "14", foot: "11 succeeded · 2 failed", iconName: "activity" })}${metricCard({ label: "Blocking issue", value: "1", foot: "Crime month continuity", footState: "negative", iconName: "alert" })}</div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Recent runs", description: "Every run retains request, stage, artifact and quality evidence", actions: route("runs", "View all runs", { className: "text-link" }), body: table({ columns: [
        { label: "Run", render: (r) => `<a class="row-link mono" href="#/run-detail" data-route="run-detail">${escapeHtml(r.id)}</a><span class="table-secondary">${escapeHtml(r.started)}</span>` }, { label: "Job", render: (r) => `<span class="table-primary">${escapeHtml(r.job)}</span><span class="table-secondary">${escapeHtml(r.mode)}</span>` }, { label: "Stage", key: "stage" }, { label: "Rows", key: "rows" }, { label: "State", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") },
      ], rows: runs.slice(0, 5) }) })}
      <div class="stack">
        ${panel({ title: "Current release gate", description: "Crime series · candidate 2026.06-candidate.2", body: `${notice({ state: "danger", iconName: "alert", title: "1 blocking quality failure", body: "November 2025 is missing. The previous accepted release remains available to Feature 3." })}<div style="margin-top:.8rem">${button("Review candidate", { kind: "warning", iconName: "eye", route: "release-review" })}</div>` })}
        ${panel({ title: "Feature 1 scope", body: `<div class="stack" style="gap:.5rem">${quickAction({ title: "Sources", description: "Registry, licence and adapter CRUD", route: "sources", iconName: "database" })}${quickAction({ title: "Jobs", description: "Strategies, limits and targets", route: "jobs", iconName: "workflow" })}${quickAction({ title: "Property discovery", description: "Stable identities and coverage", route: "discovery", iconName: "search" })}${quickAction({ title: "AI diagnosis", description: "Explain failure and safe recovery", route: "ai-diagnosis", iconName: "sparkles" })}</div>` })}
      </div>
    </div>
    <div class="section-gap">${panel({ title: "Data lineage", description: "Shared reliability path for every supported dataset", body: lineage([
      { title: "Source", detail: "Registered + licensed", icon: "database" }, { title: "Acquire", detail: "Bounded download", icon: "download" }, { title: "Stage", detail: "Immutable artifact", icon: "box" }, { title: "Normalise", detail: "Typed records", icon: "workflow" }, { title: "Quality", detail: "Blocking + warning", icon: "shield" }, { title: "Release", detail: "Human accepted", icon: "bookmark" }, { title: "Feature", detail: "Version import", icon: "link" },
    ]) })}</div>
  `;
}

function sourcesScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Source CRUD", title: "Source registry", description: "Maintain attributable, licence-aware data sources independently from ingestion jobs. Source changes are reviewable and never overwrite accepted release evidence.", actions: button("Register source", { kind: "primary", iconName: "plus" }), meta: `${badge("8 sources", "info")}${tag("Minimum 10 seeded records in implementation")}` })}
    ${toolbar({ search: "Search source, publisher or adapter", controls: `${field({ label: "Status", type: "select", value: "All statuses", options: ["All statuses", "Active", "Draft", "Disabled"] })}${field({ label: "Domain", type: "select", value: "All domains", options: ["All domains", "Address registry", "Recorded sales", "Crime series", "Planning", "Environmental"] })}`, actions: button("Export registry", { iconName: "download", size: "small" }) })}
    ${panel({ title: "Registered sources", description: "Source metadata is separate from each versioned acquisition", body: table({ columns: [
      { label: "Source", render: (r) => `<div class="cluster"><span class="source-logo">${escapeHtml(r.initials)}</span><span><a class="row-link" href="#/source-detail" data-route="source-detail">${escapeHtml(r.name)}</a><span class="table-secondary mono">${escapeHtml(r.id)}</span></span></div>` },
      { label: "Publisher", render: (r) => `<span class="table-primary">${escapeHtml(r.publisher)}</span><span class="table-secondary">${escapeHtml(r.domain)}</span>` },
      { label: "Cadence", key: "cadence" }, { label: "Adapter", render: (r) => apiPill(r.adapter) }, { label: "Records", key: "records" }, { label: "Freshness", key: "freshness" }, { label: "State", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") }, { label: "", render: () => iconButton("Open source", "chevronRight", { route: "source-detail", kind: "ghost" }) },
    ], rows: sources }) })}
  `;
}

function sourceDetailScreen() {
  const source = sources[2];
  return `
    ${screenHeader({ eyebrow: `Feature 1 · ${source.id}`, title: source.name, description: "Source metadata, ownership, licence constraints and adapter contract. Editing this registry record does not mutate past acquisitions or releases.", actions: `${button("Save changes", { kind: "primary", iconName: "check" })}${button("Run source test", { iconName: "play" })}`, meta: `${badge("Active", "active")}${tag(source.domain)}${tag(source.publisher)}` })}
    <div class="grid grid-wide-aside">
      ${panel({ title: "Source configuration", description: "Update operation · validation is server-owned", body: `<div class="form-grid">${field({ label: "Display name", value: source.name })}${field({ label: "Source ID", value: source.id, attrs: "readonly" })}${field({ label: "Publisher", value: source.publisher })}${field({ label: "Domain", type: "select", value: source.domain, options: [source.domain, "Address registry", "Recorded sales", "Planning", "Environmental"] })}${field({ label: "Release cadence", value: source.cadence })}${field({ label: "Adapter key", value: source.adapter, help: "Resolved by the Feature 1 adapter registry" })}${field({ label: "Licence classification", value: source.licence })}${field({ label: "Lifecycle state", type: "select", value: "Active", options: ["Draft", "Active", "Disabled"] })}${field({ label: "Acquisition notes", type: "textarea", value: "Bulk recorded-crime release used for bounded suburb and category series. Preserve source period labels and explicit zero/missing semantics.", className: "wide" })}</div>` })}
      <div class="stack">
        ${panel({ title: "Contract summary", body: `<dl class="detail-grid" style="grid-template-columns:1fr"><div><dt>Acquisition</dt><dd>Manual URL or source snapshot</dd></div><div><dt>Maximum size</dt><dd>200 MB</dd></div><div><dt>Allowed content</dt><dd>ZIP / CSV</dd></div><div><dt>Default job</dt><dd><a class="row-link" href="#/job-detail" data-route="job-detail">JOB-CRIME</a></dd></div><div><dt>Downstream target</dt><dd>Feature 3</dd></div></dl>` })}
        ${panel({ title: "Audit", body: timeline([
          { title: "Source created", detail: "Registry seed · Student 1", time: "2 Aug", state: "success", icon: "plus" },
          { title: "Adapter contract updated", detail: "Added zero/missing semantics", time: "7 Aug", state: "success", icon: "edit" },
          { title: "Last acquisition", detail: "Candidate source archive stored", time: "12 Aug", state: "success", icon: "download" },
        ]) })}
      </div>
    </div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Versioned acquisitions", description: "Immutable source artifacts and checksums", body: table({ columns: [
        { label: "Version", render: (r) => `<span class="mono table-primary">${escapeHtml(r.version)}</span><span class="table-secondary">${escapeHtml(r.date)}</span>` }, { label: "Artifact", render: (r) => apiPill(r.artifact) }, { label: "Checksum", render: (r) => `<span class="mono">${escapeHtml(r.hash)}</span>` }, { label: "State", render: (r) => badge(r.state, r.state, "no-dot") },
      ], rows: [
        { version: "2026.06-source.2", date: "12 Aug 2026", artifact: "bocsar/2026-06/source.zip", hash: "746a…9a10", state: "accepted" },
        { version: "2026.06-source.1", date: "10 Aug 2026", artifact: "bocsar/2026-06/source-old.zip", hash: "415c…a089", state: "stale" },
        { version: "2026.05-source.1", date: "22 Jul 2026", artifact: "bocsar/2026-05/source.zip", hash: "d807…c910", state: "accepted" },
      ] }) })}
      ${panel({ title: "Danger zone", description: "Delete operation is constrained by release evidence", body: `${notice({ state: "warning", title: "This source has immutable references", body: "Past artifacts and accepted release records are retained even if the source registry entry is disabled." })}<div class="cluster" style="margin-top:.75rem">${button("Disable source", { kind: "warning", iconName: "lock" })}${button("Delete draft", { kind: "danger", iconName: "trash", attrs: "disabled" })}</div>` })}
    </div>
  `;
}

function jobsScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Job CRUD", title: "Ingestion jobs", description: "Configure repeatable acquisition and normalisation strategies with explicit resource limits, target feature contracts and safe rerun modes.", actions: button("Create job", { kind: "primary", iconName: "plus" }), meta: `${badge("5 showcase jobs", "info")}${tag("Idempotent execution")}` })}
    ${toolbar({ search: "Search job or dataset", controls: `${field({ label: "Target", type: "select", value: "All features", options: ["All features", "Feature 1", "Feature 2", "Feature 3", "Feature 4"] })}${field({ label: "State", type: "select", value: "Active + draft", options: ["Active + draft", "Active", "Draft", "Disabled"] })}`, actions: button("Plan selected", { iconName: "play", size: "small", route: "run-plan" }) })}
    ${panel({ title: "Configured jobs", description: "A job references one source but can publish a versioned release to another feature", body: table({ columns: [
      { label: "Job", render: (r) => `<a class="row-link" href="#/job-detail" data-route="job-detail">${escapeHtml(r.name)}</a><span class="table-secondary mono">${escapeHtml(r.id)}</span>` }, { label: "Dataset", render: (r) => apiPill(r.dataset) }, { label: "Source", key: "source" }, { label: "Strategy", render: (r) => `<span class="table-primary">${escapeHtml(r.strategy)}</span><span class="table-secondary">${escapeHtml(r.mode)}</span>` }, { label: "Target", key: "target" }, { label: "Last / next", render: (r) => `<span class="table-primary">${escapeHtml(r.last)}</span><span class="table-secondary">${escapeHtml(r.next)}</span>` }, { label: "State", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") },
    ], rows: jobs }) })}
  `;
}

function jobDetailScreen() {
  const job = jobs[2];
  return `
    ${screenHeader({ eyebrow: `Feature 1 · ${job.id}`, title: job.name, description: "A repeatable data pipeline contract with bounded inputs, deterministic stages and a target release schema owned by Feature 3.", actions: `${button("Plan run", { kind: "primary", iconName: "play", route: "run-plan" })}${button("Save job", { iconName: "check" })}`, meta: `${badge("Active", "active")}${tag(job.dataset)}${tag(job.target)}` })}
    <div class="grid grid-wide-aside">
      ${panel({ title: "Job configuration", description: "Create/update fields", body: `<div class="form-grid">${field({ label: "Job name", value: job.name })}${field({ label: "Job ID", value: job.id, attrs: "readonly" })}${field({ label: "Source", type: "select", value: "SRC-BOCSAR", options: ["SRC-BOCSAR", "SRC-GNAF", "SRC-PSI"] })}${field({ label: "Dataset contract", value: job.dataset })}${field({ label: "Execution strategy", type: "select", value: job.strategy, options: ["Full snapshot", "Partition replacement", "Versioned manual import"] })}${field({ label: "Default mode", type: "select", value: job.mode, options: ["Full refresh", "Reprocess cached"] })}${field({ label: "Target feature", type: "select", value: job.target, options: ["Feature 1", "Feature 2", "Feature 3", "Feature 4", "Feature 5"] })}${field({ label: "Resource guard", value: job.limits })}${field({ label: "Run parameters (JSON)", type: "textarea", value: '{\n  "series_granularity": "suburb-month",\n  "preserve_missing": true\n}', className: "wide" })}</div>` })}
      <div class="stack">
        ${panel({ title: "Stage contract", body: timeline([
          { title: "Acquire", detail: "Fetch or select immutable source artifact", time: "Stage 1", state: "success", icon: "download" },
          { title: "Stage", detail: "Extract and record checksums", time: "Stage 2", state: "success", icon: "box" },
          { title: "Normalise", detail: "Typed suburb/category/month rows", time: "Stage 3", state: "success", icon: "workflow" },
          { title: "Validate", detail: "Continuity, coverage, drift, semantics", time: "Stage 4", state: "warning", icon: "shield" },
          { title: "Candidate", detail: "Create reviewable release; no auto-accept", time: "Stage 5", state: "running", icon: "bookmark" },
        ]) })}
        ${panel({ title: "Safety controls", body: `<div class="stack">${evidenceState("confirmed", "Idempotency key", "Duplicate request returns the existing run")}${evidenceState("confirmed", "Resource limits", "Size and row caps enforced before normalisation")}${evidenceState("confirmed", "Acceptance gate", "Candidate release requires explicit human action")}</div>` })}
      </div>
    </div>
    <div class="section-gap">${panel({ title: "Recent executions", body: table({ columns: [
      { label: "Run", render: (r) => `<a class="row-link mono" href="#/run-detail" data-route="run-detail">${escapeHtml(r.id)}</a>` }, { label: "Started", key: "started" }, { label: "Mode", key: "mode" }, { label: "Rows", key: "rows" }, { label: "Detail", key: "detail" }, { label: "State", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") },
    ], rows: runs.filter((r) => r.job.includes("BOCSAR")) }) })}</div>
  `;
}

function runPlanScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Plan", title: "Plan an ingestion run", description: "Preview the exact source, strategy, limits, expected artifacts and release impact before executing. Planning is a first-class stage in the shared agentic workflow.", actions: button("Run history", { route: "runs", iconName: "history" }), meta: `${badge("No changes executed", "info")}${tag("Dry-run validation")}` })}
    <div class="grid grid-wide-aside">
      ${panel({ title: "Run request", description: "Inputs are validated before a run record is created", body: `<div class="form-grid">${field({ label: "Job", type: "select", value: "JOB-CRIME", options: jobs.map((j) => ({ value: j.id, label: `${j.id} — ${j.name}` })) })}${field({ label: "Execution mode", type: "select", value: "Reprocess cached", options: ["Full refresh", "Reprocess cached"] })}${field({ label: "Source version", type: "select", value: "2026.06-source.2", options: ["2026.06-source.2", "2026.05-source.1"] })}${field({ label: "Idempotency key", value: "crime-2026-06-reprocess-02" })}${field({ label: "Reason", type: "textarea", value: "Reprocess the verified source archive after investigating the missing-month quality failure.", className: "wide" })}<label class="checkbox-row wide"><input type="checkbox" checked><span><strong>Create candidate release</strong><span class="table-secondary">The candidate remains unavailable downstream until accepted.</span></span></label></div><div class="cluster" style="margin-top:1rem">${button("Validate plan", { iconName: "shield" })}${button("Start run", { kind: "primary", iconName: "play", route: "run-detail" })}</div>` })}
      <div class="stack">
        ${panel({ title: "Plan summary", body: `<dl class="detail-grid" style="grid-template-columns:1fr"><div><dt>Source</dt><dd>BOCSAR recorded crime data</dd></div><div><dt>Acquisition</dt><dd>Use cached immutable source.zip</dd></div><div><dt>Target</dt><dd>Feature 3 · crime-series</dd></div><div><dt>Maximum rows</dt><dd>2,000,000</dd></div><div><dt>Expected artifacts</dt><dd>3 staged + 1 release export</dd></div><div><dt>State change</dt><dd>Candidate only</dd></div></dl>` })}
        ${notice({ state: "success", title: "Plan is safe to execute", body: "No accepted release will be overwritten. The cached artifact checksum matches the selected source version." })}
      </div>
    </div>
    <div class="section-gap">${panel({ title: "Planned execution", description: "Plan → Act → Observe → Adapt", body: agentLoop("plan", { plan: "Validate source version, mode, limits and release intent.", act: "Acquire cached artifact; normalise and run quality rules.", observe: "Compare candidate with accepted predecessor and thresholds.", adapt: "Accept, reject or create a recovery plan after human review." }) })}</div>
  `;
}

function runsScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Run ledger", title: "Ingestion runs", description: "Search every execution by request, job, stage and outcome. Run history remains immutable even when source or job configuration changes.", actions: button("Plan new run", { kind: "primary", iconName: "play", route: "run-plan" }), meta: `${badge("6 showcase runs", "info")}${tag("Immutable trace")}` })}
    ${toolbar({ search: "Search run, request or job", controls: `${field({ label: "Outcome", type: "select", value: "Any outcome", options: ["Any outcome", "Succeeded", "Failed", "Warning"] })}${field({ label: "Mode", type: "select", value: "Any mode", options: ["Any mode", "Full refresh", "Reprocess cached"] })}`, actions: button("Export ledger", { iconName: "download", size: "small" }) })}
    ${panel({ title: "Execution history", body: table({ columns: [
      { label: "Run / request", render: (r) => `<a class="row-link mono" href="#/run-detail" data-route="run-detail">${escapeHtml(r.id)}</a><span class="table-secondary mono">${escapeHtml(r.request)}</span>` }, { label: "Job", render: (r) => `<span class="table-primary">${escapeHtml(r.job)}</span><span class="table-secondary">${escapeHtml(r.mode)}</span>` }, { label: "Stage", key: "stage" }, { label: "Started", key: "started" }, { label: "Elapsed", key: "elapsed" }, { label: "Rows", key: "rows" }, { label: "Outcome", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") },
    ], rows: runs }) })}
  `;
}

function runDetailScreen() {
  const run = runs[0];
  return `
    ${screenHeader({ eyebrow: `Feature 1 · ${run.id}`, title: "Run failed at quality validation", description: run.detail, actions: `${button("Ask AI to diagnose", { kind: "primary", iconName: "sparkles", route: "ai-diagnosis" })}${button("Reprocess", { iconName: "refresh", route: "run-plan" })}`, meta: `${badge("Failed", "failed")}${tag(run.job)}${tag(run.elapsed)}` })}
    ${notice({ state: "danger", iconName: "alert", title: "Candidate was not published", body: "A blocking completeness rule failed. The accepted Feature 3 release remains 2026.05.1 and downstream availability is unaffected." })}
    <div class="grid grid-4 section-gap">${metricCard({ label: "Rows normalised", value: "96,840", foot: "+2.8% vs predecessor", iconName: "table" })}${metricCard({ label: "Quality checks", value: "6", foot: "1 failed · 2 warning", footState: "negative", iconName: "shield" })}${metricCard({ label: "Artifacts", value: "4", foot: "Checksums retained", iconName: "box" })}${metricCard({ label: "Downstream impact", value: "None", foot: "Prior release retained", footState: "positive", iconName: "link" })}</div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Stage timeline", description: "Observed execution state", body: timeline([
        { title: "Request accepted", detail: `${run.request} · idempotency check passed`, time: "10:42:00", state: "success", icon: "check" },
        { title: "Cached acquisition selected", detail: "source.zip checksum 746a…9a10", time: "10:42:07", state: "success", icon: "box" },
        { title: "Normalisation complete", detail: "96,840 typed rows", time: "10:42:54", state: "success", icon: "workflow" },
        { title: "Quality validation failed", detail: "crime.month_continuity · 2025-11 missing", time: "10:43:41", state: "failed", icon: "x" },
        { title: "Candidate retained for review", detail: "No accepted release changed", time: "10:43:48", state: "warning", icon: "eye" },
      ]) })}
      ${panel({ title: "Run details", body: `<dl class="detail-grid" style="grid-template-columns:1fr"><div><dt>Run ID</dt><dd class="mono">${run.id}</dd></div><div><dt>Request ID</dt><dd class="mono">${run.request}</dd></div><div><dt>Job</dt><dd>JOB-CRIME</dd></div><div><dt>Mode</dt><dd>${run.mode}</dd></div><div><dt>Started</dt><dd>${run.started}</dd></div><div><dt>Elapsed</dt><dd>${run.elapsed}</dd></div><div><dt>Runner</dt><dd>student-1-runner</dd></div><div><dt>Schema</dt><dd>crime-series.v1</dd></div></dl>` })}
    </div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Quality results", actions: route("quality", "View all quality rules", { className: "text-link" }), body: table({ columns: [
        { label: "Rule", render: (r) => `<span class="mono table-primary">${escapeHtml(r.rule)}</span><span class="table-secondary">${escapeHtml(r.dimension)}</span>` }, { label: "Severity", key: "severity" }, { label: "Observed", key: "observed" }, { label: "Expected", key: "expected" }, { label: "Sample", key: "sample" }, { label: "Outcome", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") },
      ], rows: qualityRules }) })}
      ${panel({ title: "Evidence lineage", body: lineage([
        { title: "source.zip", detail: "746a…9a10", icon: "file" }, { title: "combined.csv", detail: "41.8 MB", icon: "file" }, { title: "normalised", detail: "96,840 rows", icon: "table" }, { title: "quality", detail: "1 blocked", icon: "alert" }, { title: "candidate", detail: "Review only", icon: "bookmark" },
      ]) })}
    </div>
  `;
}

function releasesScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Release catalogue", title: "Data releases", description: "Accepted, candidate and draft releases are explicit versioned products. Downstream features import accepted versions rather than reading Feature 1 tables directly.", actions: button("Compare releases", { iconName: "scales" }), meta: `${badge("4 accepted", "success")}${badge("1 review", "review")}${badge("1 draft", "draft")}` })}
    ${toolbar({ search: "Search dataset or version", controls: `${field({ label: "Target", type: "select", value: "All targets", options: ["All targets", "Feature 1", "Feature 2", "Feature 3", "Feature 4"] })}${field({ label: "Lifecycle", type: "select", value: "All states", options: ["All states", "Accepted", "Review", "Draft", "Rejected"] })}` })}
    ${panel({ title: "Release catalogue", body: table({ columns: [
      { label: "Dataset / version", render: (r) => `<a class="row-link" href="#/release-review" data-route="release-review">${escapeHtml(r.dataset)}</a><span class="table-secondary mono">${escapeHtml(r.version)}</span>` }, { label: "Target", key: "target" }, { label: "Records", key: "records" }, { label: "Coverage", key: "coverage" }, { label: "Checksum", render: (r) => `<span class="mono">${escapeHtml(r.checksum)}</span>` }, { label: "Created", key: "created" }, { label: "State", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") }, { label: "", render: () => iconButton("Review release", "chevronRight", { route: "release-review", kind: "ghost" }) },
    ], rows: releases }) })}
  `;
}

function releaseReviewScreen() {
  const candidate = releases[0];
  return `
    ${screenHeader({ eyebrow: `Feature 1 · ${candidate.id}`, title: "Review crime-series candidate", description: "Compare the candidate with its accepted predecessor, inspect quality evidence, then accept or reject with an auditable human decision.", actions: `${button("Reject candidate", { kind: "secondary", iconName: "x" })}${button("Accept release", { kind: "primary", iconName: "check", attrs: "disabled", })}`, meta: `${badge("Blocked", "failed")}${tag(candidate.version)}${tag(candidate.target)}` })}
    ${notice({ state: "danger", title: "Acceptance is disabled", body: "A blocking rule failed: 11 months were observed where 12 were required. Resolve or explicitly change the approved quality policy before acceptance." })}
    <div class="grid grid-4 section-gap">${metricCard({ label: "Candidate records", value: candidate.records, foot: "+2.8% vs accepted", iconName: "table" })}${metricCard({ label: "Month coverage", value: candidate.coverage, foot: "November 2025 missing", footState: "negative", iconName: "calendar" })}${metricCard({ label: "Blocking failures", value: "1", foot: "Completeness", footState: "negative", iconName: "alert" })}${metricCard({ label: "Downstream state", value: "Unchanged", foot: "Feature 3 uses 2026.05.1", footState: "positive", iconName: "link" })}</div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Candidate vs accepted predecessor", body: table({ columns: [
        { label: "Measure", key: "measure" }, { label: "Candidate · 2026.06-candidate.2", render: (r) => `<strong>${escapeHtml(r.candidate)}</strong>` }, { label: "Accepted · 2026.05.1", render: (r) => `<strong>${escapeHtml(r.accepted)}</strong>` }, { label: "Assessment", render: (r) => badge(r.assessment, r.state, "no-dot") },
      ], rows: [
        { measure: "Records", candidate: "96,840", accepted: "94,170", assessment: "Within drift band", state: "success" },
        { measure: "Month continuity", candidate: "11 / 12", accepted: "12 / 12", assessment: "Blocking", state: "failed" },
        { measure: "Locality coverage", candidate: "34 / 34", accepted: "34 / 34", assessment: "Pass", state: "success" },
        { measure: "Category coverage", candidate: "18", accepted: "18", assessment: "Pass", state: "success" },
        { measure: "Zero/missing semantics", candidate: "Valid", accepted: "Valid", assessment: "Pass", state: "success" },
      ] }) })}
      ${panel({ title: "Review decision", description: "A human owns the lifecycle transition", body: `<div class="stack">${field({ label: "Decision", type: "select", value: "Needs remediation", options: ["Needs remediation", "Reject", "Accept with approved exception"] })}${field({ label: "Reviewer note", type: "textarea", value: "Keep 2026.05.1 accepted. Verify the June archive and reprocess after confirming the missing November file." })}${button("Record review", { kind: "warning", iconName: "edit" })}</div>` })}
    </div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Quality evidence", body: table({ columns: [
        { label: "Rule", render: (r) => `<span class="mono table-primary">${escapeHtml(r.rule)}</span><span class="table-secondary">${escapeHtml(r.dimension)}</span>` }, { label: "Severity", key: "severity" }, { label: "Observed", key: "observed" }, { label: "Expected", key: "expected" }, { label: "Outcome", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") },
      ], rows: qualityRules }) })}
      ${panel({ title: "AI-assisted diagnosis", description: "Optional explanation, never the decision-maker", body: `${notice({ state: "info", iconName: "sparkles", title: "Suggested safe recovery", body: "Retain the predecessor, verify source completeness, then use reprocess-cached mode. No destructive action is required." })}<div style="margin-top:.8rem">${button("Open full diagnosis", { iconName: "sparkles", route: "ai-diagnosis" })}</div>` })}
    </div>
  `;
}

function qualityScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Quality governance", title: "Quality rules and results", description: "Blocking, warning and informational checks are versioned policy. Results include observed values and samples so reviewers can understand why a release was gated.", actions: button("Create rule", { kind: "primary", iconName: "plus" }), meta: `${badge("6 evaluated rules", "info")}${tag("Policy version qg-1.3")}` })}
    <div class="grid grid-4">${metricCard({ label: "Pass", value: "3", foot: "Blocking and informational", footState: "positive", iconName: "check" })}${metricCard({ label: "Warning", value: "2", foot: "Review but not blocking", footState: "warning", iconName: "alert" })}${metricCard({ label: "Failed", value: "1", foot: "Candidate blocked", footState: "negative", iconName: "x" })}${metricCard({ label: "Policy coverage", value: "100%", foot: "All required dimensions", iconName: "shield" })}</div>
    <div class="section-gap">${panel({ title: "Result set · crime-series 2026.06-candidate.2", body: table({ columns: [
      { label: "Rule", render: (r) => `<span class="mono table-primary">${escapeHtml(r.rule)}</span><span class="table-secondary">${escapeHtml(r.dimension)}</span>` }, { label: "Severity", render: (r) => badge(r.severity, r.severity === "Blocking" ? "danger" : r.severity === "Warning" ? "warning" : "info", "no-dot") }, { label: "Observed", key: "observed" }, { label: "Expected", key: "expected" }, { label: "Evidence sample", render: (r) => `<span class="mono">${escapeHtml(r.sample)}</span>` }, { label: "Outcome", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") },
    ], rows: qualityRules }) })}</div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Policy design", description: "Rules are data, not hard-coded UI assumptions", body: `<div class="form-grid">${field({ label: "Rule key", value: "crime.month_continuity" })}${field({ label: "Dimension", type: "select", value: "Completeness", options: ["Completeness", "Validity", "Coverage", "Drift", "Reproducibility"] })}${field({ label: "Severity", type: "select", value: "Blocking", options: ["Blocking", "Warning", "Info"] })}${field({ label: "Expected expression", value: "observed_months == expected_months" })}${field({ label: "Human description", type: "textarea", value: "Every expected month must be present. Missing and zero values must remain distinct.", className: "wide" })}</div>` })}
      ${panel({ title: "Semantics contract", body: `<div class="stack">${evidenceState("confirmed", "Zero", "A valid observed value of zero incidents")}${evidenceState("unknown", "Missing", "No source observation for the period")}${evidenceState("conflicting", "Duplicate / conflict", "More than one incompatible value for the same grain")}</div>` })}
    </div>
  `;
}

function artifactsScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Reproducibility", title: "Artifact registry", description: "Immutable source, staged, normalised and release artifacts with checksums, retention policy and run lineage.", actions: button("Verify checksums", { kind: "primary", iconName: "shield" }), meta: `${badge("5 showcase artifacts", "info")}${tag("Content-addressed evidence")}` })}
    ${toolbar({ search: "Search artifact key, run or hash", controls: `${field({ label: "Kind", type: "select", value: "All kinds", options: ["All kinds", "Source archive", "Staged extract", "Normalised data", "Release export"] })}${field({ label: "Retention", type: "select", value: "Any retention", options: ["Any retention", "Candidate", "Accepted release", "Release evidence"] })}` })}
    ${panel({ title: "Stored artifacts", body: table({ columns: [
      { label: "Artifact", render: (r) => `<span class="mono table-primary">${escapeHtml(r.key)}</span><span class="table-secondary">${escapeHtml(r.kind)}</span>` }, { label: "Size", key: "size" }, { label: "Checksum", render: (r) => `<span class="mono">${escapeHtml(r.hash)}</span>` }, { label: "Retention", key: "retention" }, { label: "Origin run", render: (r) => `<a class="row-link mono" href="#/run-detail" data-route="run-detail">${escapeHtml(r.run)}</a>` }, { label: "State", render: (r) => badge(statusLabel(r.status), r.status, "no-dot") }, { label: "", render: () => iconButton("Download artifact", "download", { kind: "ghost" }) },
    ], rows: artifacts }) })}
    <div class="section-gap">${panel({ title: "Selected artifact lineage", description: "bocsar/2026-06/feature-3-release.jsonl", body: lineage([
      { title: "Source registry", detail: "SRC-BOCSAR", icon: "database" }, { title: "Run", detail: "RUN-0826-1042", icon: "activity" }, { title: "Source archive", detail: "82.4 MB", icon: "file" }, { title: "Normalised", detail: "15.2 MB", icon: "table" }, { title: "Quality", detail: "Candidate blocked", icon: "alert" }, { title: "Release export", detail: "8ae1…c410", icon: "box" },
    ]) })}</div>
  `;
}

function coverageScreen() {
  return `
    ${screenHeader({ eyebrow: "Shared coverage, owned by Feature 1", title: "Data coverage matrix", description: "Coverage is a first-class product output. It shows which datasets are confirmed, partial or unknown for selected showcase areas and which feature owns the interpretation.", actions: button("Export matrix", { iconName: "download" }), meta: `${badge("8 dataset families", "info")}${tag("Freshness visible")}` })}
    ${notice({ state: "info", title: "Coverage does not imply a property finding", body: "For example, flood-study coverage means a study can be queried; it does not by itself state that a property is or is not flood affected." })}
    <div class="section-gap">${panel({ title: "Coverage by area", description: "Current accepted releases", body: table({ columns: [
      { label: "Dataset", render: (r) => `<span class="table-primary">${escapeHtml(r.dataset)}</span><span class="table-secondary">${escapeHtml(r.owner)} · refreshed ${escapeHtml(r.fresh)}</span>` }, { label: "Parramatta", render: (r) => coverageState(r.parramatta) }, { label: "Newtown", render: (r) => coverageState(r.newtown) }, { label: "Mosman", render: (r) => coverageState(r.mosman) }, { label: "Wollongong", render: (r) => coverageState(r.wollongong) },
    ], rows: coverage }) })}</div>
    <div class="grid grid-main-aside section-gap">
      ${mapFrame({ properties, selected: primaryProperty.ref, compact: true, overlays: ["flood", "bushfire"], legend: `<strong>Coverage layers</strong><div class="legend-row"><span class="legend-swatch partial"></span>Flood study</div><div class="legend-row"><span class="legend-swatch conflicting"></span>Bush fire layer</div>` })}
      ${panel({ title: "Coverage states", body: evidenceDefinitions() })}
    </div>
  `;
}

function discoveryScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · Property identity", title: "Property discovery operations", description: "Test address resolution, inspect candidate matches and verify which accepted source records support the stable PropertyScope identity used by all other features.", actions: button("Open buyer view", { route: "explore", iconName: "external" }), meta: `${badge("G-NAF release 2026.08.12", "success")}${tag("4.18m NSW records")}` })}
    ${toolbar({ search: "12 Example Street, Parramatta NSW", controls: `${field({ label: "Match threshold", type: "select", value: "High confidence", options: ["Exact only", "High confidence", "Include unresolved"] })}`, actions: button("Resolve", { kind: "primary", iconName: "search", size: "small" }) })}
    <div class="grid grid-map-list">
      ${panel({ title: "Candidate identities", description: "Best match selected; alternatives remain inspectable", body: propertyResults(), footer: `${badge("4 candidates", "info", "no-dot")}<span class="muted">Response 37 ms</span>` })}
      ${mapFrame({ properties, selected: primaryProperty.ref })}
    </div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Selected identity evidence", body: table({ columns: [
        { label: "Source record", render: (r) => `<span class="mono table-primary">${escapeHtml(r.record)}</span><span class="table-secondary">${escapeHtml(r.source)}</span>` }, { label: "Address string", key: "address" }, { label: "Role", key: "role" }, { label: "Confidence", render: (r) => badge(r.confidence, r.state, "no-dot") }, { label: "Release", key: "release" },
      ], rows: [
        { record: "GNAF-NSW-9011842", source: "G-NAF", address: primaryProperty.address, role: "Canonical identity", confidence: "Exact", state: "success", release: "2026.08.12" },
        { record: "PSI-PROP-777120", source: "NSW PSI", address: "12 EXAMPLE ST PARRAMATTA 2150", role: "Sale linkage", confidence: "High", state: "success", release: "2026.08.08" },
        { record: "PLAN-PT-2201", source: "Planning showcase", address: "Parcel point match", role: "Spatial evidence", confidence: "Point intersect", state: "info", release: "2026.05.1" },
      ] }) })}
      ${panel({ title: "Identity contract", body: `<dl class="detail-grid" style="grid-template-columns:1fr"><div><dt>Reference</dt><dd class="mono">${primaryProperty.ref}</dd></div><div><dt>Canonical source</dt><dd>G-NAF</dd></div><div><dt>Geometry</dt><dd>Point · EPSG:4326</dd></div><div><dt>Resolution state</dt><dd>${badge("Verified", "confirmed", "no-dot")}</dd></div><div><dt>Downstream rule</dt><dd>Features store the reference and imported release, not raw Feature 1 foreign keys</dd></div></dl>` })}
    </div>
  `;
}

function featurePropertyDetailScreen() {
  return `
    ${propertyHero(primaryProperty, `${button("Open shared property view", { kind: "primary", iconName: "external", route: "property" })}${button("Inspect raw evidence", { iconName: "database", route: "evidence" })}`)}
    <div class="grid grid-4 section-gap">${metricCard({ label: "Identity records", value: "3", foot: "1 canonical · 2 linked", iconName: "link" })}${metricCard({ label: "Release imports", value: "7", foot: "Across four feature owners", iconName: "bookmark" })}${metricCard({ label: "Coverage gaps", value: "2", foot: "Planning + building", footState: "warning", iconName: "alert" })}${metricCard({ label: "Conflict count", value: "0", foot: "No identity conflicts", footState: "positive", iconName: "check" })}</div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Property evidence index", description: "Feature 1 provides identity and source availability; domain owners provide interpretation", body: table({ columns: [
        { label: "Evidence family", key: "family" }, { label: "Owner", key: "owner" }, { label: "Imported release", render: (r) => `<span class="mono">${escapeHtml(r.release)}</span>` }, { label: "Records", key: "records" }, { label: "State", render: (r) => badge(evidenceLabel(r.state), r.state, "no-dot") }, { label: "Open", render: (r) => `<a class="row-link" href="#/${escapeHtml(r.route)}" data-route="${escapeHtml(r.route)}">View</a>` },
      ], rows: [
        { family: "Canonical identity", owner: "Feature 1", release: "property-registry@2026.08.12", records: "1", state: "confirmed", route: "discovery" },
        { family: "Recorded sales", owner: "Feature 2", release: "sale-observations@2026.08.08", records: "4", state: "confirmed", route: "market-detail" },
        { family: "Crime + schools", owner: "Feature 3", release: "crime-series@2026.05.1", records: "18 series", state: "confirmed", route: "suburb-comparison" },
        { family: "Planning + site", owner: "Feature 4", release: "planning-showcase@2026.05.1", records: "8 facts", state: "partial", route: "site-detail" },
        { family: "Buyer workspace", owner: "Feature 5", release: "user workspace", records: "11 items", state: "confirmed", route: "buyer-workspace" },
      ] }) })}
      ${panel({ title: "Source freshness", body: `<div class="stack">${sources.slice(0, 5).map((s) => evidenceState(s.status === "draft" ? "partial" : "confirmed", s.name, s.freshness)).join("")}</div>` })}
    </div>
  `;
}

function aiDiagnosisScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 1 · AI-mode", title: "Diagnose a data operation", description: "Use the configured remote model to explain a selected run or release, propose bounded next steps and leave the evidence trace visible. It cannot accept releases or mutate data without an explicit human action.", actions: button("Past agent runs", { route: "agent-runs", iconName: "history" }), meta: `${badge("OpenAI ready", "success")}${tag("GPT-5.6 Luna")}${tag("Release 0 AI-mode")}` })}
    <div class="grid grid-wide-aside">
      ${panel({ title: "Assisted task", description: "The source object constrains the prompt and available tools", body: `<div class="form-grid">${field({ label: "Context type", type: "select", value: "Failed run", options: ["Failed run", "Candidate release", "Source", "Job", "Property identity"] })}${field({ label: "Context object", type: "select", value: "RUN-0826-1042", options: ["RUN-0826-1042", "REL-CRIME-2026-06-C", "SRC-BOCSAR", "JOB-CRIME"] })}${field({ label: "Objective", type: "textarea", value: "Explain why this run failed, what downstream impact exists, and the safest non-destructive recovery plan.", className: "wide" })}<label class="checkbox-row wide"><input type="checkbox" checked><span><strong>Require human review</strong><span class="table-secondary">Recommended for any workflow that proposes a state-changing next step.</span></span></label></div><div class="cluster" style="margin-top:1rem">${button("Generate diagnosis", { kind: "primary", iconName: "sparkles", route: "agent-run" })}${button("Preview context", { iconName: "eye" })}</div>` })}
      ${panel({ title: "Bounded tool access", description: "Release 0 uses backend tools around the local model", body: `<div class="stack" style="gap:.5rem">${toolCall({ name: "data.get_run", detail: "Read run, stage and request metadata", meta: "read-only" })}${toolCall({ name: "data.get_quality_results", detail: "Read evaluated rules and evidence samples", meta: "read-only" })}${toolCall({ name: "data.get_release", detail: "Read candidate and accepted predecessor", meta: "read-only" })}${toolCall({ name: "data.create_recovery_plan", detail: "Create a reviewable draft only", state: "warning", meta: "human gate" })}</div>` })}
    </div>
    <div class="section-gap">${panel({ title: "Agentic workflow", description: "Visible in every release", body: agentLoop("plan", { plan: "Select evidence objects and define safety constraints.", act: "Invoke bounded read-only Feature 1 tools and the local LLM.", observe: "Check whether the answer is supported and whether tools failed.", adapt: "Ask a clarifying question, propose a recovery or hand off for review." }) })}</div>
    <div class="section-gap">${notice({ state: "info", title: "Release 1 extension", body: "The same screen adds MCP structured resources, RAG runbooks and source citations. Release 2 can delegate to Planner, Worker and Reviewer agents in local mode." })}</div>
  `;
}

// Feature 2 — Sales and Market Intelligence
function marketCasesScreen() {
  const cases = [
    { id: "MKT-0142", property: "12 Example Street, Parramatta", stage: "Comparable review", sales: "4 history · 3 comps", period: "12 months", updated: "12 Aug", state: "review" },
    { id: "MKT-0138", property: "24 Park Road, North Parramatta", stage: "Evidence ready", sales: "3 history · 4 comps", period: "18 months", updated: "11 Aug", state: "success" },
    { id: "MKT-0131", property: "Unit 3, 9 Sample Avenue, Parramatta", stage: "Draft", sales: "2 history · 5 comps", period: "6 months", updated: "9 Aug", state: "draft" },
    { id: "MKT-0127", property: "18 Example Street, Parramatta", stage: "Evidence ready", sales: "5 history · 3 comps", period: "12 months", updated: "8 Aug", state: "success" },
  ];
  return `
    ${screenHeader({ eyebrow: "Feature 2 · Sales & market intelligence", title: "Market cases", description: "Build bounded market evidence around a verified property identity. Feature 2 explains recorded sale history and comparable selection; it does not manufacture an automated valuation or buying recommendation.", actions: button("Create market case", { kind: "primary", iconName: "plus", route: "market-detail" }), meta: `${badge("Feature 2 scoped", "planned")}${tag("Recorded evidence, not valuation")}` })}
    <div class="grid grid-4">${metricCard({ label: "Open cases", value: "4", foot: "1 awaiting review", iconName: "briefcase" })}${metricCard({ label: "Accepted sales release", value: "2026.08", foot: "318,420 records", iconName: "bookmark" })}${metricCard({ label: "Median evidence age", value: "21d", foot: "Showcase areas", iconName: "clock" })}${metricCard({ label: "Comparable overrides", value: "2", foot: "Reason required", footState: "warning", iconName: "edit" })}</div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Research cases", description: "Each case stores selection rules, included/excluded evidence and reviewer notes", body: table({ columns: [
        { label: "Case", render: (r) => `<a class="row-link mono" href="#/market-detail" data-route="market-detail">${escapeHtml(r.id)}</a><span class="table-secondary">${escapeHtml(r.updated)}</span>` }, { label: "Property", render: (r) => `<span class="table-primary">${escapeHtml(r.property)}</span><span class="table-secondary">Verified PropertyScope identity</span>` }, { label: "Evidence", key: "sales" }, { label: "Window", key: "period" }, { label: "Stage", render: (r) => badge(r.stage, r.state, "no-dot") }, { label: "", render: () => iconButton("Open market case", "chevronRight", { route: "market-detail", kind: "ghost" }) },
      ], rows: cases }) })}
      ${panel({ title: "Feature boundary", description: "Deliberately separated from Feature 1 and Feature 5", body: `<div class="stack">${evidenceState("confirmed", "Feature 1 supplies", "Stable property identity and accepted sales release metadata")}${evidenceState("confirmed", "Feature 2 owns", "Sale linkage, comparable rules, market case review and narrative")}${evidenceState("unknown", "Not claimed", "Automated valuation, future price prediction or purchase advice")}</div>` })}
    </div>
    <div class="section-gap">${panel({ title: "Create case", body: `<div class="form-grid">${field({ label: "Property", value: primaryProperty.address })}${field({ label: "Evidence window", type: "select", value: "12 months", options: ["6 months", "12 months", "18 months", "24 months"] })}${field({ label: "Maximum distance", value: "1.0 km" })}${field({ label: "Property class", type: "select", value: "Detached house", options: ["Detached house", "Townhouse", "Apartment"] })}${field({ label: "Research question", type: "textarea", value: "What recent recorded sales are genuinely comparable, and which important differences should a reviewer keep in mind?", className: "wide" })}</div>` })}</div>
  `;
}

function marketDetailScreen() {
  const trendSeries = [
    { name: "Subject sale history", values: [372, 592, 845, 1210] },
    { name: "Suburb index", values: [390, 555, 820, 1165] },
  ];
  return `
    ${propertyHero(primaryProperty, `${button("Add market evidence to dossier", { kind: "primary", iconName: "file", route: "dossier-builder" })}${button("Edit comparable rules", { iconName: "settings" })}`)}
    <div class="screen-meta" style="margin:1rem 0">${badge("Market case MKT-0142", "review")}${tag("12-month comparable window")}${tag("1 km radius")}${tag("Detached house")}</div>
    <div class="grid grid-4">${metricCard({ label: "Latest recorded sale", value: "$1.21m", foot: "May 2026 · exact address", iconName: "trend" })}${metricCard({ label: "Included comparables", value: "3", foot: "2 excluded with reason", iconName: "scales" })}${metricCard({ label: "Comparable range", value: "$1.10–1.27m", foot: "Recorded prices only", iconName: "chart" })}${metricCard({ label: "Market evidence state", value: "Confirmed", foot: "Accepted PSI release", footState: "positive", iconName: "shield" })}</div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Recorded sale history", description: "Nominal prices — no hidden inflation adjustment", body: `<div class="chart-legend"><span class="chart-legend-item"><span class="chart-dot"></span>Subject history</span><span class="chart-legend-item"><span class="chart-dot secondary"></span>Illustrative suburb index</span></div>${lineChart(trendSeries, { labels: ["2004", "2011", "2018", "2026"], ariaLabel: "Recorded sale history and suburb index" })}` })}
      ${panel({ title: "Interpretation guardrails", body: `<div class="stack">${evidenceState("confirmed", "Recorded prices", "Four linked sale observations from accepted PSI releases")}${evidenceState("partial", "Property differences", "Land, condition and improvements are only partly represented")}${evidenceState("unknown", "Fair value", "Not calculated or claimed by PropertyScope")}</div>` })}
    </div>
    <div class="section-gap">${panel({ title: "Comparable selection", description: "Inclusion and exclusion are both visible", body: table({ columns: [
      { label: "Comparable", render: (r) => `<span class="table-primary">${escapeHtml(r.address)}</span><span class="table-secondary">${escapeHtml(r.distance)} · sold ${escapeHtml(r.sold)}</span>` }, { label: "Price", render: (r) => `<strong>${escapeHtml(r.price)}</strong>` }, { label: "Land", key: "land" }, { label: "Beds", key: "beds" }, { label: "Decision", render: (r) => badge(r.inclusion, r.inclusion === "Included" ? "success" : "unknown", "no-dot") }, { label: "Reason", key: "reason" },
    ], rows: comparables }) })}</div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Reviewer narrative", description: "A bounded explanation rather than a valuation", body: `<p>The three included sales sit between <strong>$1.095m and $1.265m</strong>. They are nearby detached houses sold within the selected window, but they differ in land size, bedrooms and likely condition. The subject’s May 2026 recorded sale at $1.210m is the most direct evidence; current asking-price context is user-supplied and is not itself a recorded transaction.</p>${notice({ state: "warning", title: "Do not treat this range as a valuation", body: "Comparable selection is evidence for professional and buyer review. Contract terms, condition, improvements and market timing may materially differ." })}` })}
      ${panel({ title: "Evidence provenance", body: `<dl class="detail-grid" style="grid-template-columns:1fr"><div><dt>Release</dt><dd class="mono">sale-observations@2026.08.08</dd></div><div><dt>Property identity</dt><dd class="mono">${primaryProperty.ref}</dd></div><div><dt>Selection rule</dt><dd class="mono">comp.detached.1km.12m.v1</dd></div><div><dt>Reviewer</dt><dd>Pending</dd></div></dl>` })}
    </div>
  `;
}

// Feature 3 — Suburb, Crime and Liveability
function suburbComparisonScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 3 · Suburb context", title: "Compare suburb evidence", description: "Compare selected suburbs using consistent periods, visible source coverage and explicit count/rate semantics. A comparison is a research aid, not a safety ranking or lifestyle verdict.", actions: `${button("Save comparison", { kind: "primary", iconName: "bookmark" })}${button("Crime detail", { iconName: "chart", route: "crime-trends" })}`, meta: `${badge("Feature 3 scoped", "planned")}${tag("Parramatta vs Newtown vs Mosman")}` })}
    ${toolbar({ search: "Add suburb", controls: `${field({ label: "Period", type: "select", value: "12 months to May 2026", options: ["12 months to May 2026", "Calendar 2025", "36-month trend"] })}${field({ label: "Measure", type: "select", value: "Counts and supported rates", options: ["Counts and supported rates", "Counts only", "Rates only"] })}`, actions: button("Add suburb", { iconName: "plus", size: "small" }) })}
    <div class="comparison-grid">
      <div class="comparison-cell header label">Evidence dimension</div>
      ${["Parramatta", "Newtown", "Mosman"].map((name, i) => `<div class="comparison-cell header"><span class="feature-number">${icon(i === 0 ? "building" : i === 1 ? "house" : "tree")}</span><strong style="margin-top:.5rem">${name}</strong><small>${i === 0 ? "Selected property area" : "Peer comparison"}</small></div>`).join("")}
      ${[
        ["Crime release", ["2026.05.1 · confirmed", "2026.05.1 · confirmed", "2026.05.1 · confirmed"]],
        ["Steal from motor vehicle", ["188 per supported period", "146 per supported period", "42 per supported period"]],
        ["Malicious damage", ["154", "171", "38"]],
        ["Government schools", ["3 nearby points", "4 nearby points", "3 nearby points"]],
        ["Property identity coverage", ["Confirmed", "Confirmed", "Confirmed"]],
        ["Planning showcase", ["Partial", "Partial", "Unknown"]],
        ["Interpretation note", ["Regional centre and transport hub", "Dense inner-city context", "Lower population; rate denominator required"]],
      ].map(([label, vals]) => `<div class="comparison-cell label">${escapeHtml(label)}</div>${vals.map((v) => `<div class="comparison-cell">${escapeHtml(v)}</div>`).join("")}`).join("")}
    </div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Selected crime categories", description: "Same period and source release", body: barChart(crimeCategories, { max: 210, labelKey: "name", valueKey: "parramatta", secondaryKey: "peer" }), footer: `<div class="chart-legend"><span class="chart-legend-item"><span class="chart-dot"></span>Parramatta</span><span class="chart-legend-item"><span class="chart-dot secondary"></span>Newtown peer</span></div><span class="muted">Counts shown unless a supported denominator is selected</span>` })}
      ${panel({ title: "Comparison quality", body: `<div class="stack">${evidenceState("confirmed", "Consistent period", "All crime observations use 12 months to May 2026")}${evidenceState("partial", "Rate availability", "One selected category has count-only evidence")}${evidenceState("unknown", "Personal safety", "Cannot be inferred from area-level recorded incidents alone")}</div>` })}
    </div>
  `;
}

function crimeTrendsScreen() {
  const months = ["Jun", "Aug", "Oct", "Dec", "Feb", "Apr", "May"];
  const trend = [
    { name: "Parramatta", values: [16, 14, 18, 15, 17, 20, 19] },
    { name: "Newtown", values: [13, 12, 15, 14, 11, 16, 15] },
  ];
  return `
    ${screenHeader({ eyebrow: "Feature 3 · Crime evidence", title: "Recorded crime trends", description: "Explore selected categories with zero/missing distinction, visible release coverage and honest denominator constraints.", actions: button("Add to suburb comparison", { kind: "primary", iconName: "plus", route: "suburb-comparison" }), meta: `${badge("Accepted release 2026.05.1", "success")}${tag("12 / 12 months")}` })}
    ${toolbar({ search: "Search offence category", controls: `${field({ label: "Area", type: "select", value: "Parramatta", options: ["Parramatta", "Newtown", "Mosman"] })}${field({ label: "Category", type: "select", value: "Steal from motor vehicle", options: crimeCategories.map((c) => c.name) })}${field({ label: "Measure", type: "select", value: "Monthly count", options: ["Monthly count", "Supported rate", "12-month rolling count"] })}` })}
    <div class="grid grid-4">${metricCard({ label: "12-month count", value: "188", foot: "+4.2% vs previous period", footState: "warning", iconName: "chart" })}${metricCard({ label: "Monthly median", value: "16", foot: "Range 12–20", iconName: "calendar" })}${metricCard({ label: "Missing periods", value: "0", foot: "Accepted release complete", footState: "positive", iconName: "check" })}${metricCard({ label: "Rate support", value: "Available", foot: "Population denominator versioned", iconName: "scales" })}</div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Monthly observations", description: "Steal from motor vehicle · selected areas", body: `<div class="chart-legend"><span class="chart-legend-item"><span class="chart-dot"></span>Parramatta</span><span class="chart-legend-item"><span class="chart-dot secondary"></span>Newtown</span></div>${lineChart(trend, { labels: months, ariaLabel: "Monthly recorded crime trend" })}` })}
      ${panel({ title: "How to read this", body: `<div class="stack">${evidenceState("confirmed", "Zero is a value", "A reported zero remains distinct from missing source data")}${evidenceState("confirmed", "Period complete", "Accepted release contains every expected month")}${evidenceState("partial", "Recorded incidents", "Reporting and policing patterns can affect observations")}${evidenceState("unknown", "Individual risk", "Not estimated from this dataset")}</div>` })}
    </div>
    <div class="section-gap">${panel({ title: "Category summary", body: table({ columns: [
      { label: "Category", render: (r) => `<span class="table-primary">${escapeHtml(r.name)}</span><span class="table-secondary">${escapeHtml(r.status)}</span>` }, { label: "Parramatta", render: (r) => `<strong>${r.parramatta}</strong>` }, { label: "Newtown peer", render: (r) => `<strong>${r.peer}</strong>` }, { label: "Period change", render: (r) => badge(r.change, r.change.startsWith("+") ? "warning" : "success", "no-dot") }, { label: "Evidence", render: (r) => badge(r.status, r.status.includes("available") ? "confirmed" : "partial", "no-dot") },
    ], rows: crimeCategories }) })}</div>
  `;
}

// Feature 4 — Site, Planning and Building Due Diligence
function siteReviewsScreen() {
  const reviews = [
    { id: "SITE-0094", property: "12 Example Street, Parramatta", state: "partial", status: "Needs verification", flags: "Flood interpretation · building records", owner: "Matt", updated: "12 Aug" },
    { id: "SITE-0091", property: "24 Park Road, North Parramatta", state: "confirmed", status: "Evidence reviewed", flags: "No mapped heritage item", owner: "Alex", updated: "11 Aug" },
    { id: "SITE-0088", property: "Unit 3, 9 Sample Avenue, Parramatta", state: "partial", status: "Draft", flags: "Strata documents outside corpus", owner: "Jordan", updated: "9 Aug" },
    { id: "SITE-0082", property: "18 Example Street, Parramatta", state: "unknown", status: "Coverage incomplete", flags: "No flood study in bounded corpus", owner: "Sam", updated: "7 Aug" },
  ];
  return `
    ${screenHeader({ eyebrow: "Feature 4 · Site due diligence", title: "Site reviews", description: "Collect planning, environmental and building evidence into a reviewable checklist. Coverage, no-intersection and no-supported-record are deliberately different outcomes.", actions: button("Create site review", { kind: "primary", iconName: "plus", route: "site-detail" }), meta: `${badge("Feature 4 scoped", "planned")}${tag("Professional verification supported")}` })}
    <div class="grid grid-4">${metricCard({ label: "Open reviews", value: "4", foot: "2 need verification", iconName: "clipboard" })}${metricCard({ label: "Planning layers", value: "4", foot: "Selected showcase councils", iconName: "layers" })}${metricCard({ label: "Environmental layers", value: "2", foot: "Flood + bush fire", iconName: "tree" })}${metricCard({ label: "Unknown findings", value: "3", foot: "Not converted to ‘no’", footState: "warning", iconName: "help" })}</div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Review workspace", body: table({ columns: [
        { label: "Review", render: (r) => `<a class="row-link mono" href="#/site-detail" data-route="site-detail">${escapeHtml(r.id)}</a><span class="table-secondary">Updated ${escapeHtml(r.updated)}</span>` }, { label: "Property", key: "property" }, { label: "Findings requiring attention", key: "flags" }, { label: "Owner", key: "owner" }, { label: "State", render: (r) => badge(r.status, r.state, "no-dot") }, { label: "", render: () => iconButton("Open site review", "chevronRight", { route: "site-detail", kind: "ghost" }) },
      ], rows: reviews }) })}
      ${panel({ title: "Outcome vocabulary", body: `<div class="stack">${evidenceState("confirmed", "No intersection", "A supported map layer covers the point and reports no intersection")}${evidenceState("partial", "Coverage / interpretation partial", "A relevant source exists but cannot support a final conclusion")}${evidenceState("unknown", "No supported record", "The bounded corpus cannot answer; external verification is required")}</div>` })}
    </div>
  `;
}

function siteDetailScreen() {
  return `
    ${propertyHero(primaryProperty, `${button("Create follow-up tasks", { kind: "primary", iconName: "clipboard", route: "follow-ups" })}${button("Add to dossier", { iconName: "file", route: "dossier-builder" })}`)}
    <div class="screen-meta" style="margin:1rem 0">${badge("Site review SITE-0094", "partial")}${tag("8 evidence questions")}${tag("2 external verifications")}</div>
    <div class="grid grid-wide-aside">
      ${mapFrame({ properties: [primaryProperty], selected: primaryProperty.ref, overlays: ["flood", "bushfire"], legend: `<strong>Evidence overlays</strong><div class="legend-row"><span class="legend-swatch partial"></span>Flood study coverage</div><div class="legend-row"><span class="legend-swatch conflicting"></span>Bush fire prone layer</div>` })}
      ${panel({ title: "Review summary", body: `<div class="grid grid-2">${metricCard({ label: "Confirmed facts", value: "6", foot: "Current accepted layers", iconName: "check" })}${metricCard({ label: "Needs verification", value: "2", foot: "Flood + building records", footState: "warning", iconName: "alert" })}</div><div class="section-gap">${notice({ state: "warning", title: "Professional review recommended", body: "PropertyScope is a research organiser. Confirm planning, flood, title and building implications with the relevant authority and qualified advisers." })}</div>` })}
    </div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Planning and site facts", description: "Each fact keeps the source and state", body: `<div class="fact-list">${planningFacts.map((fact) => `<div class="fact-row"><span class="label">${escapeHtml(fact.label)}</span><span><span class="value">${escapeHtml(fact.value)}</span><span class="source">${escapeHtml(fact.source)}</span></span>${badge(evidenceLabel(fact.state), fact.state, "no-dot")}</div>`).join("")}</div>` })}
      ${panel({ title: "Questions to verify", body: `<div class="stack">${quickAction({ title: "Flood study interpretation", description: "Council / conveyancer", route: "follow-ups", iconName: "message" })}${quickAction({ title: "Building and pest inspection", description: "Qualified inspector", route: "follow-ups", iconName: "house" })}${quickAction({ title: "Approval history for works", description: "Selling agent / council", route: "follow-ups", iconName: "file" })}${quickAction({ title: "Contract and title review", description: "Conveyancer", route: "follow-ups", iconName: "scales" })}</div>` })}
    </div>
    <div class="section-gap">${panel({ title: "Evidence lineage", body: lineage([
      { title: "Property point", detail: primaryProperty.ref, icon: "pin" }, { title: "Layer release", detail: "Version imported", icon: "layers" }, { title: "Spatial query", detail: "Intersection / coverage", icon: "map" }, { title: "Evidence state", detail: "Confirmed / partial", icon: "shield" }, { title: "Review finding", detail: "Human-readable", icon: "eye" }, { title: "Follow-up", detail: "Stakeholder task", icon: "clipboard" },
    ]) })}</div>
  `;
}

// Feature 5 — Buyer Journey and Agent Workspace
function buyerWorkspaceScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 5 · Buyer workspace", title: "Good morning, Matt", description: "Move from scattered research to a reviewable purchase workflow. Saved properties, priorities, evidence gaps and next actions stay connected without turning PropertyScope into a financial or legal adviser.", actions: button("Add property", { kind: "primary", iconName: "plus", route: "explore" }), meta: `${badge("Feature 5 scoped", "planned")}${tag("1 active buyer profile")}` })}
    <div class="grid grid-4">${metricCard({ label: "Shortlisted", value: "3", foot: "1 high priority", iconName: "bookmark" })}${metricCard({ label: "Open follow-ups", value: "4", foot: "2 due before contract review", footState: "warning", iconName: "clipboard" })}${metricCard({ label: "Dossiers", value: "2", foot: "1 awaiting review", iconName: "file" })}${metricCard({ label: "Evidence gaps", value: "5", foot: "Across three properties", footState: "warning", iconName: "help" })}</div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Active shortlist", description: "Evidence state and fit are separate concepts", actions: route("shortlist", "Open shortlist", { className: "text-link" }), body: `<div class="property-result-list">${properties.slice(0, 3).map((p, index) => `<a class="property-result" href="#/dossier-builder" data-route="dossier-builder"><span class="property-result-icon">${icon("house")}</span><span><strong>${escapeHtml(p.address)}</strong><span>${index === 0 ? "High priority · 2 follow-ups" : index === 1 ? "Reviewing market evidence" : "Newly saved"}</span></span><span class="property-result-meta"><strong>${escapeHtml(p.askingPrice)}</strong><span>${badge(index === 0 ? "Partial" : "Confirmed", index === 0 ? "partial" : "confirmed", "no-dot")}</span></span></a>`).join("")}</div>` })}
      <div class="stack">
        ${panel({ title: "Next actions", body: `<div class="stack" style="gap:.55rem">${quickAction({ title: "Review flood question", description: "Due before contract review", route: "follow-ups", iconName: "alert" })}${quickAction({ title: "Finish dossier review", description: "12 Example Street", route: "dossier-review", iconName: "file" })}${quickAction({ title: "Compare shortlisted properties", description: "Evidence side-by-side", route: "shortlist", iconName: "scales" })}</div>` })}
        ${panel({ title: "Profile priorities", body: `<div class="stack" style="gap:.45rem">${buyerPriorities.slice(0, 4).map((p) => `<div class="cluster-between"><span><strong style="font-size:.72rem">${escapeHtml(p.label)}</strong><span class="table-secondary">${escapeHtml(p.evidence)}</span></span>${badge(p.weight, p.weight === "High" ? "info" : "unknown", "no-dot")}</div>`).join("")}</div>` })}
      </div>
    </div>
    <div class="section-gap">${panel({ title: "Buyer journey", description: "A product workflow spanning all five feature owners", body: lineage([
      { title: "Discover", detail: "Feature 1 identity", icon: "search" }, { title: "Market", detail: "Feature 2 evidence", icon: "trend" }, { title: "Suburb", detail: "Feature 3 context", icon: "map" }, { title: "Site", detail: "Feature 4 review", icon: "layers" }, { title: "Dossier", detail: "Feature 5 assembly", icon: "file" }, { title: "Human review", detail: "Buyer + advisers", icon: "user" }, { title: "Follow up", detail: "Tracked actions", icon: "clipboard" },
    ]) })}</div>
  `;
}

function shortlistScreen() {
  const shortlistRows = [
    { property: properties[0], priority: "High", fit: "4 / 5 priorities", evidence: "2 partial", next: "Confirm flood interpretation", state: "partial" },
    { property: properties[1], priority: "Medium", fit: "3 / 5 priorities", evidence: "1 partial", next: "Review market case", state: "confirmed" },
    { property: properties[3], priority: "Medium", fit: "3 / 5 priorities", evidence: "3 unknown", next: "Create site review", state: "unknown" },
  ];
  return `
    ${screenHeader({ eyebrow: "Feature 5 · Shortlist", title: "Compare shortlisted properties", description: "Compare fit, evidence state and open questions side-by-side. A higher personal fit does not erase weaker evidence coverage.", actions: `${button("Add property", { kind: "primary", iconName: "plus", route: "explore" })}${button("Export comparison", { iconName: "download" })}`, meta: `${badge("3 properties", "info")}${tag("Buyer profile · First home")}` })}
    <div class="comparison-grid">
      <div class="comparison-cell header label">Priority or evidence</div>
      ${shortlistRows.map((r) => `<div class="comparison-cell header"><span class="feature-number">${icon("house")}</span><strong style="margin-top:.5rem">${escapeHtml(r.property.short)}</strong><small>${escapeHtml(r.property.locality)} · ${escapeHtml(r.property.askingPrice)}</small></div>`).join("")}
      ${[
        ["Buyer priority", shortlistRows.map((r) => r.priority)],
        ["Priority fit", shortlistRows.map((r) => r.fit)],
        ["Evidence state", shortlistRows.map((r) => evidenceLabel(r.state))],
        ["Latest recorded sale", ["$1.21m · May 2026", "$1.18m · Jul 2026", "$1.04m · Apr 2026"]],
        ["Planning / site", ["Partial flood evidence", "Confirmed layers", "3 unknown findings"]],
        ["Open action", shortlistRows.map((r) => r.next)],
      ].map(([label, vals]) => `<div class="comparison-cell label">${escapeHtml(label)}</div>${vals.map((v) => `<div class="comparison-cell">${escapeHtml(v)}</div>`).join("")}`).join("")}
    </div>
    <div class="section-gap">${panel({ title: "Shortlist ledger", body: table({ columns: [
      { label: "Property", render: (r) => `<span class="table-primary">${escapeHtml(r.property.address)}</span><span class="table-secondary mono">${escapeHtml(r.property.ref)}</span>` }, { label: "Priority", render: (r) => badge(r.priority, r.priority === "High" ? "info" : "unknown", "no-dot") }, { label: "Fit", key: "fit" }, { label: "Evidence gaps", key: "evidence" }, { label: "Next action", key: "next" }, { label: "State", render: (r) => badge(evidenceLabel(r.state), r.state, "no-dot") }, { label: "", render: () => button("Dossier", { size: "small", route: "dossier-builder" }) },
    ], rows: shortlistRows }) })}</div>
  `;
}

function dossierBuilderScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 5 · Dossier builder", title: "Build purchase research dossier", description: "Choose the property, evidence sections and buyer priorities. The generated document separates supported facts, bounded interpretation and questions requiring external verification.", actions: button("Saved dossiers", { route: "buyer-workspace", iconName: "history" }), meta: `${badge("Draft", "draft")}${tag(primaryProperty.ref)}` })}
    <div class="grid grid-wide-aside">
      ${panel({ title: "Dossier configuration", description: "Create/update workflow", body: `<div class="form-grid">${field({ label: "Dossier name", value: "12 Example Street — purchase research" })}${field({ label: "Property", value: primaryProperty.address, attrs: "readonly" })}${field({ label: "Buyer profile", type: "select", value: "Matt · First-home search", options: ["Matt · First-home search"] })}${field({ label: "Review deadline", type: "date", value: "2026-08-22" })}<div class="form-section wide"><div class="form-section-title">Include evidence sections</div><div class="grid grid-2">${["Property identity and coverage", "Recorded sale history", "Comparable market evidence", "Suburb and crime context", "Planning and site evidence", "Buyer priorities and follow-ups"].map((label) => `<label class="checkbox-row"><input type="checkbox" checked><span>${escapeHtml(label)}</span></label>`).join("")}</div></div>${field({ label: "Research objective", type: "textarea", value: "Assemble a balanced, source-attributed briefing for buyer, conveyancer and building inspector review. Emphasise evidence gaps and next questions.", className: "wide" })}</div><div class="cluster" style="margin-top:1rem">${button("Save draft", { iconName: "check" })}${button("Generate dossier", { kind: "primary", iconName: "sparkles", route: "dossier-run" })}</div>` })}
      <div class="stack">
        ${panel({ title: "Included evidence", body: `<div class="stack">${evidenceState("confirmed", "Property identity", "Verified · 8 source records")}${evidenceState("confirmed", "Market evidence", "4 history records · 3 included comps")}${evidenceState("confirmed", "Suburb context", "Accepted crime and school releases")}${evidenceState("partial", "Site evidence", "Flood interpretation and building records need follow-up")}</div>` })}
        ${panel({ title: "Output guardrails", body: `<ul class="clean-list">${["No automated valuation", "No legal, financial or planning advice", "Unknown is not rendered as ‘no’", "Every generated claim links to evidence", "Human review required before finalisation"].map((item) => `<li>${icon("shield")}<span>${escapeHtml(item)}</span></li>`).join("")}</ul>` })}
      </div>
    </div>
  `;
}

function dossierRunScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 5 · Agent run AGT-2038", title: "Generating purchase dossier", description: "The workflow gathers accepted evidence from each feature, drafts bounded summaries, verifies citations and pauses for human review.", actions: button("Cancel run", { kind: "secondary", iconName: "x" }), meta: `${badge("Reviewer phase", "review")}${tag("11 tool calls")}${tag("54 seconds")}` })}
    ${agentLoop("observe", { plan: "Resolve property, sections, audience and review deadline.", act: "Gather feature evidence and draft section summaries.", observe: "Reviewer checks citations, unsupported claims and missing sections.", adapt: "Repair issues or hand the dossier to human review." })}
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Generation progress", description: "Section-level work remains visible", body: timeline([
        { title: "Property identity gathered", detail: "Feature 1 · 8 evidence records", time: "09:52:08", state: "success", icon: "building" },
        { title: "Market case gathered", detail: "Feature 2 · sale history and comparable decisions", time: "09:52:17", state: "success", icon: "trend" },
        { title: "Suburb context gathered", detail: "Feature 3 · accepted crime and school releases", time: "09:52:24", state: "success", icon: "map" },
        { title: "Site review gathered", detail: "Feature 4 · 6 confirmed, 2 partial findings", time: "09:52:32", state: "success", icon: "layers" },
        { title: "Draft assembled", detail: "13 claims · 13 evidence links", time: "09:52:46", state: "success", icon: "file" },
        { title: "Reviewer checking", detail: "One wording repair proposed", time: "Now", state: "warning", icon: "eye" },
      ]) })}
      <div class="stack">
        ${panel({ title: "Run metrics", body: `<div class="grid grid-2">${metricCard({ label: "Sections", value: "6 / 6", foot: "All drafted", iconName: "file" })}${metricCard({ label: "Citations", value: "13", foot: "100% linked", footState: "positive", iconName: "link" })}${metricCard({ label: "Reviewer flags", value: "1", foot: "Wording precision", footState: "warning", iconName: "alert" })}${metricCard({ label: "Unsupported claims", value: "0", foot: "No fabrication found", footState: "positive", iconName: "shield" })}</div>` })}
        ${notice({ state: "warning", title: "Reviewer repair", body: "Replace ‘not flood affected’ with ‘the property point is outside the mapped modelled extent; professional interpretation is still recommended’." })}
        ${button("Open human review", { kind: "primary", iconName: "user", route: "dossier-review" })}
      </div>
    </div>
  `;
}

function dossierReviewScreen() {
  return `
    ${screenHeader({ eyebrow: "Feature 5 · Human review", title: "Review purchase dossier", description: "Approve, edit or reject generated sections before a dossier can be finalised or shared. The evidence remains attached to every material claim.", actions: `${button("Request revision", { iconName: "refresh" })}${button("Approve dossier", { kind: "primary", iconName: "check" })}`, meta: `${badge("1 reviewer flag", "review")}${tag("13 cited claims")}` })}
    <div class="grid grid-wide-aside">
      <article class="dossier-page">
        <div class="dossier-cover"><p class="eyebrow">PropertyScope NSW · Purchase research</p><h1>12 Example Street, Parramatta</h1><p>Evidence briefing prepared for buyer and professional adviser review · 12 August 2026</p><div class="dossier-summary"><div><strong>13</strong><span>Cited claims</span></div><div><strong>6</strong><span>Sections</span></div><div><strong>2</strong><span>Partial findings</span></div><div><strong>4</strong><span>Follow-ups</span></div></div></div>
        <div class="dossier-body">
          <section class="dossier-section"><div class="dossier-section-title"><h2>Executive evidence summary</h2>${badge("Reviewer flag", "review", "no-dot")}</div><p>The property identity is verified and market/suburb evidence is supported by current accepted releases. Planning controls are available for the showcase area. Flood evidence is partial and building-record coverage is unknown, so those matters remain follow-up questions.</p><div class="dossier-callout"><strong>Wording under review:</strong> The flood study maps the surrounding area, but PropertyScope does not provide a professional flood-risk conclusion.</div></section>
          <section class="dossier-section"><div class="dossier-section-title"><h2>Market evidence</h2>${badge("Confirmed", "confirmed", "no-dot")}</div><p>Four recorded sales are linked to the verified property identity. The latest is $1,210,000 in May 2026. Three nearby detached-house sales are included as comparables; two records are excluded with explicit reasons.</p></section>
          <section class="dossier-section"><div class="dossier-section-title"><h2>Planning and site</h2>${badge("Partial", "partial", "no-dot")}</div><p>R2 zoning, a 0.5:1 floor-space ratio and a 9 metre mapped height control are supported by the selected planning release. No mapped heritage item or bush-fire-prone intersection is shown at the property point. Flood interpretation and building history need external verification.</p></section>
          <section class="dossier-section"><div class="dossier-section-title"><h2>Next questions</h2>${badge("4 open", "warning", "no-dot")}</div><p>Confirm the flood-study interpretation, arrange building and pest inspection, ask whether recent works were approved, and have the contract and title documents reviewed by a conveyancer.</p></section>
        </div>
      </article>
      <div class="stack">
        ${panel({ title: "Review checklist", body: `<div class="stack">${evidenceState("confirmed", "Evidence links", "13 / 13 material claims have source references")}${evidenceState("confirmed", "Bounded language", "No valuation, legal advice or safety ranking")}${evidenceState("partial", "Flood wording", "One sentence needs precision before approval")}${evidenceState("confirmed", "Unknown handling", "Building records remain unknown, not ‘none’")}</div>` })}
        ${panel({ title: "Reviewer action", body: `<div class="stack">${field({ label: "Flagged section", type: "select", value: "Executive evidence summary", options: ["Executive evidence summary", "Market evidence", "Planning and site", "Next questions"] })}${field({ label: "Review note", type: "textarea", value: "Keep the revised wording that distinguishes map coverage from professional flood-risk interpretation." })}${button("Resolve flag", { kind: "warning", iconName: "check" })}</div>` })}
        ${panel({ title: "Evidence drawer", body: `<div class="stack" style="gap:.45rem">${groundedCitations.map((c) => `<div class="tool-call"><span class="tool-icon">${icon(c.type.includes("Document") ? "book" : "database")}</span><div><strong>${escapeHtml(c.id)}</strong><span>${escapeHtml(c.title)}</span></div>${badge(c.type, "info", "no-dot")}</div>`).join("")}</div>` })}
      </div>
    </div>
  `;
}

function followUpsScreen() {
  const columns = ["To verify", "Planned", "In progress", "Complete"];
  return `
    ${screenHeader({ eyebrow: "Feature 5 · Follow-up workflow", title: "Questions and actions", description: "Turn partial and unknown evidence into explicit stakeholder questions. Tasks retain the evidence gap that created them and never masquerade as resolved until a human records an outcome.", actions: button("Create task", { kind: "primary", iconName: "plus" }), meta: `${badge("6 tasks", "info")}${tag("4 open")}` })}
    <div class="kanban">${columns.map((column) => {
      const items = followups.filter((item) => item.status === column || (column === "Planned" && item.status === "Draft"));
      return `<section class="kanban-column"><div class="kanban-head"><strong>${escapeHtml(column)}</strong><span class="kanban-count">${items.length}</span></div>${items.length ? items.map((task) => `<article class="task-card"><h3>${escapeHtml(task.title)}</h3><p>${escapeHtml(task.evidence)}</p><div class="task-meta"><span>${escapeHtml(task.stakeholder)}</span><span>${escapeHtml(task.due)}</span></div></article>`).join("") : `<div class="empty-state" style="min-height:130px;padding:.7rem"><div><p>No tasks</p></div></div>`}</section>`;
    }).join("")}</div>
    <div class="grid grid-main-aside section-gap">
      ${panel({ title: "Task ledger", body: table({ columns: [
        { label: "Task", render: (r) => `<span class="mono table-primary">${escapeHtml(r.id)}</span><span class="table-secondary">${escapeHtml(r.title)}</span>` }, { label: "Stakeholder", key: "stakeholder" }, { label: "Due", key: "due" }, { label: "Origin evidence", key: "evidence" }, { label: "State", render: (r) => badge(r.status, r.status === "Complete" ? "success" : r.status === "In progress" ? "info" : r.status === "To verify" ? "warning" : "draft", "no-dot") },
      ], rows: followups }) })}
      ${panel({ title: "Create from evidence", body: `<div class="stack">${field({ label: "Evidence gap", type: "select", value: "Flood evidence · partial", options: ["Flood evidence · partial", "Building records · unknown", "School enrolment · unknown"] })}${field({ label: "Stakeholder", type: "select", value: "Council / conveyancer", options: ["Council / conveyancer", "Inspector", "Selling agent", "School authority", "Lender / broker"] })}${field({ label: "Question", type: "textarea", value: "Can you confirm how the current flood study should be interpreted for this property and contract review?" })}${button("Add task", { kind: "primary", iconName: "plus" })}</div>` })}
    </div>
  `;
}

// Release 1 and Release 2 shared AI views
function groundedAnswerScreen() {
  return `
    ${screenHeader({ eyebrow: "Release 1 · MCP + RAG", title: "Grounded answer workspace", description: "Structured facts come from MCP tools; explanatory passages come from the RAG corpus. The UI preserves that distinction and exposes retrieval failures independently from model failures.", actions: button("Start new question", { kind: "primary", iconName: "plus" }), meta: `${badge("Release 1 designed", "planned")}${tag("Local only")}${tag("Citations required")}` })}
    <div class="grid grid-wide-aside">
      ${panel({ title: "Question", body: `<div class="stack">${field({ label: "Context", type: "select", value: "Crime candidate release", options: ["Crime candidate release", "Property dossier", "Site review", "Market case"] })}${field({ label: "Question", type: "textarea", value: "Why can’t the June crime candidate be accepted, what should remain available to Feature 3, and what recovery procedure does the runbook recommend?" })}<div class="cluster">${button("Answer with evidence", { kind: "primary", iconName: "sparkles" })}${button("Inspect retrieval", { iconName: "eye" })}</div></div>` })}
      ${panel({ title: "Retrieval status", body: `<div class="stack">${evidenceState("confirmed", "MCP structured evidence", "2 resources and 2 tool results selected")}${evidenceState("confirmed", "RAG document context", "1 runbook passage selected")}${evidenceState("confirmed", "Prompt-injection filter", "No untrusted instruction accepted")}${evidenceState("unknown", "External web", "Not available in the bounded local workflow")}</div>` })}
    </div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Grounded answer", description: "Generated wording remains reviewable", body: `<p>The June candidate cannot be accepted because the blocking <span class="mono">crime.month_continuity</span> rule observed only 11 of the expected 12 months; November 2025 is missing. Feature 3 should continue using accepted release <span class="mono">2026.05.1</span>, which has complete month coverage.</p><p>The recovery runbook recommends retaining the accepted predecessor, verifying the source archive, then reprocessing the cached acquisition. The candidate should remain review-only until the continuity rule passes or an authorised policy change is recorded.</p>${notice({ state: "success", title: "Grounding check passed", body: "Every material factual statement maps to at least one selected evidence item." })}` })}
      ${panel({ title: "Evidence used", body: `<div class="stack">${groundedCitations.map((c) => `<article class="card soft" style="padding:.75rem"><div class="cluster-between">${badge(c.type, c.type.includes("Document") ? "info" : "confirmed", "no-dot")}<span class="mono subtle">${escapeHtml(c.id)}</span></div><h3 style="margin-top:.55rem">${escapeHtml(c.title)}</h3><p class="muted" style="font-size:.67rem">${escapeHtml(c.detail)}</p><span class="table-secondary">${escapeHtml(c.source)}</span></article>`).join("")}</div>` })}
    </div>
    <div class="section-gap">${panel({ title: "Grounded request flow", body: lineage([
      { title: "User question", detail: "Bounded context", icon: "message" }, { title: "MCP", detail: "Structured facts", icon: "database" }, { title: "RAG", detail: "Document passages", icon: "book" }, { title: "Context policy", detail: "Sanitise + budget", icon: "shield" }, { title: "Local LLM", detail: "Compose answer", icon: "bot" }, { title: "Citation check", detail: "Claim support", icon: "link" }, { title: "Human", detail: "Review / act", icon: "user" },
    ]) })}</div>
  `;
}

function multiAgentReviewScreen() {
  return `
    ${screenHeader({ eyebrow: "Release 2 · Multi-agent local mode", title: "Multi-agent review queue", description: "Planner, Worker and Reviewer agents collaborate locally, then stop at a human gate. Cloud mode falls back to AI-mode only, with MCP, RAG and multi-agent explicitly disabled.", actions: `${button("Approve plan", { kind: "primary", iconName: "check" })}${button("Return to planner", { iconName: "refresh" })}`, meta: `${badge("Human review", "review")}${tag("Local mode")}${tag("3 agents")}` })}
    <div class="grid grid-3">
      ${card(`<div class="cluster-between"><span class="feature-number">${icon("clipboard")}</span>${badge("Complete", "success", "no-dot")}</div><p class="eyebrow" style="margin-top:.8rem">Planner agent</p><h2>Research plan</h2><p class="muted">Resolve identity, gather accepted evidence from Features 1–4, assemble a dossier draft, then require review for partial findings.</p><div class="cluster">${tag("6 steps")}${tag("8 tools")}</div>`, "tint-ocean")}
      ${card(`<div class="cluster-between"><span class="feature-number">${icon("workflow")}</span>${badge("Complete", "success", "no-dot")}</div><p class="eyebrow" style="margin-top:.8rem">Worker agent</p><h2>Evidence execution</h2><p class="muted">Executed bounded feature tools, built section drafts and recorded 13 evidence links without state-changing operations.</p><div class="cluster">${tag("13 claims")}${tag("0 tool errors")}</div>`)}
      ${card(`<div class="cluster-between"><span class="feature-number">${icon("eye")}</span>${badge("1 repair", "review", "no-dot")}</div><p class="eyebrow" style="margin-top:.8rem">Reviewer agent</p><h2>Grounding review</h2><p class="muted">Flagged one overconfident flood sentence and proposed wording that preserves the evidence limitation.</p><div class="cluster">${tag("1 flag")}${tag("High confidence")}</div>`, "tint-sand")}
    </div>
    <div class="grid grid-wide-aside section-gap">
      ${panel({ title: "Shared task trace", body: timeline([
        { title: "Planner created bounded plan", detail: "No purchasing recommendation or autonomous acceptance", time: "09:51:58", state: "success", icon: "clipboard" },
        { title: "Worker gathered feature evidence", detail: "8 structured tool calls and 3 document retrievals", time: "09:52:32", state: "success", icon: "workflow" },
        { title: "Reviewer inspected 13 claims", detail: "Evidence links and uncertainty vocabulary checked", time: "09:52:49", state: "success", icon: "eye" },
        { title: "Repair proposed", detail: "Flood wording narrowed to supported coverage finding", time: "09:52:53", state: "warning", icon: "edit" },
        { title: "Human review required", detail: "No final dossier or external action without approval", time: "Now", state: "warning", icon: "user" },
      ]) })}
      <div class="stack">
        ${panel({ title: "Reviewer finding", body: `${notice({ state: "warning", title: "Overconfident interpretation", body: "Worker draft said ‘not flood affected’. Evidence only supports that the point is outside the mapped modelled extent in the selected study." })}<div class="code-block" style="margin-top:.7rem">Suggested repair:\n“The selected flood study provides area coverage. The matched property point is outside the mapped modelled extent; confirm implications with council or a qualified adviser.”</div>` })}
        ${panel({ title: "Deployment gate", body: `<div class="stack">${evidenceState("confirmed", "Local mode", "AI-mode + MCP + RAG + multi-agent enabled")}${evidenceState("partial", "Cloud mode", "AI-mode and approved local model enabled")}${evidenceState("unknown", "Cloud MCP/RAG/multi-agent", "Deliberately disabled by Release 2 architecture")}</div>` })}
      </div>
    </div>
  `;
}

export const screenDefinitions = {
  home: { title: "Home", feature: "Shared", render: featureHome },
  explore: { title: "Explore properties", feature: "Shared", render: exploreScreen },
  property: { title: "Property research", feature: "Shared", render: propertyScreen },
  "system-status": { title: "System status", feature: "Shared", render: systemStatusScreen },
  "agent-runs": { title: "Agent runs", feature: "Shared", render: agentRunsScreen },
  "agent-run": { title: "Agent run detail", feature: "Shared", render: agentRunScreen },
  evidence: { title: "Evidence ledger", feature: "Shared", render: evidenceScreen },
  "release-roadmap": { title: "Release roadmap", feature: "Shared", render: releaseRoadmapScreen },

  "data-overview": { title: "Data overview", feature: "Feature 1", render: dataOverviewScreen },
  sources: { title: "Sources", feature: "Feature 1", render: sourcesScreen },
  "source-detail": { title: "Source detail", feature: "Feature 1", render: sourceDetailScreen },
  jobs: { title: "Jobs", feature: "Feature 1", render: jobsScreen },
  "job-detail": { title: "Job detail", feature: "Feature 1", render: jobDetailScreen },
  "run-plan": { title: "Plan run", feature: "Feature 1", render: runPlanScreen },
  runs: { title: "Runs", feature: "Feature 1", render: runsScreen },
  "run-detail": { title: "Run detail", feature: "Feature 1", render: runDetailScreen },
  releases: { title: "Releases", feature: "Feature 1", render: releasesScreen },
  "release-review": { title: "Release review", feature: "Feature 1", render: releaseReviewScreen },
  quality: { title: "Quality", feature: "Feature 1", render: qualityScreen },
  artifacts: { title: "Artifacts", feature: "Feature 1", render: artifactsScreen },
  coverage: { title: "Coverage", feature: "Feature 1", render: coverageScreen },
  discovery: { title: "Property discovery", feature: "Feature 1", render: discoveryScreen },
  "property-detail": { title: "Property evidence", feature: "Feature 1", render: featurePropertyDetailScreen },
  "ai-diagnosis": { title: "AI diagnosis", feature: "Feature 1", render: aiDiagnosisScreen },

  "market-cases": { title: "Market cases", feature: "Feature 2", render: marketCasesScreen },
  "market-detail": { title: "Market case detail", feature: "Feature 2", render: marketDetailScreen },
  "suburb-comparison": { title: "Suburb comparison", feature: "Feature 3", render: suburbComparisonScreen },
  "crime-trends": { title: "Crime trends", feature: "Feature 3", render: crimeTrendsScreen },
  "site-reviews": { title: "Site reviews", feature: "Feature 4", render: siteReviewsScreen },
  "site-detail": { title: "Site review detail", feature: "Feature 4", render: siteDetailScreen },
  "buyer-workspace": { title: "Buyer workspace", feature: "Feature 5", render: buyerWorkspaceScreen },
  shortlist: { title: "Shortlist", feature: "Feature 5", render: shortlistScreen },
  "dossier-builder": { title: "Dossier builder", feature: "Feature 5", render: dossierBuilderScreen },
  "dossier-run": { title: "Dossier generation", feature: "Feature 5", render: dossierRunScreen },
  "dossier-review": { title: "Dossier review", feature: "Feature 5", render: dossierReviewScreen },
  "follow-ups": { title: "Follow-up tasks", feature: "Feature 5", render: followUpsScreen },

  "grounded-answer": { title: "Grounded answer", feature: "Release 1", render: groundedAnswerScreen },
  "multi-agent-review": { title: "Multi-agent review", feature: "Release 2", render: multiAgentReviewScreen },
};

export const screenOrder = Object.keys(screenDefinitions);
