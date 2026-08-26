import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { capabilityManifest, capabilityState } from "./capabilities.js";
import { parseShellRoute } from "./core.js";
import { featureRegistry, findFeature, researchAreaLabel } from "./features.js";
import { loadFeature1Bridge, validateFeature1Adapter } from "./feature-1-bridge.js";
import { resolveResearchAreaContext } from "./operations/ai-mode/contexts.js";
import { classifyHealth, overallReadiness } from "./routes/status.js";
import { SHARED_ASSISTANT_SCOPES, sharedAssistantSuggestions } from "./routes/assistant.js";

test("shared hash routes are bounded and unknown fragments return home", () => {
  assert.equal(parseShellRoute("#system-status"), "system-status");
  assert.equal(parseShellRoute("#/evidence?view=accepted"), "evidence");
  assert.equal(parseShellRoute("#release-roadmap"), "release-roadmap");
  assert.equal(parseShellRoute("#features"), "features");
  assert.equal(parseShellRoute("#assistant?scope=feature"), "assistant");
  assert.equal(parseShellRoute("#operations"), "home");
  assert.equal(parseShellRoute("#future-student-feature"), "home");
});

test("shared assistant wrapper owns product and feature vocabulary", () => {
  assert.deepEqual(SHARED_ASSISTANT_SCOPES.map((scope) => scope.id), ["application", "feature"]);
  assert.equal(sharedAssistantSuggestions("feature").some((message) => message.includes("Property data")), true);
  const sharedDefinitions = readFileSync(new URL("./ai-chat/definitions.js", import.meta.url), "utf8");
  assert.doesNotMatch(sharedDefinitions, /Property data|Parramatta|dataset/);
});

test("feature registry is the bounded source for shell routes and availability", () => {
  const features = featureRegistry();
  assert.equal(features.length, 5);
  assert.equal(features.filter((item) => item.href).length, 1);
  assert.equal(findFeature("data-platform").href, "/features/data-platform/#properties");
  assert.equal(findFeature("student-4-due-diligence").frontendBase, "/features/due-diligence/");
  assert.equal(findFeature("market-intelligence").href, undefined);
  assert.ok(features.every((item) => item.healthPath?.startsWith("/api/shared-health/")));
  assert.equal(featureRegistry({ featureHrefs: { "property-records": "/custom/#properties" } })[0].href, "/custom/#properties");
  assert.equal(features[0].label, "Property data");
});

test("shared navigation distinguishes global destinations from research-area transitions", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  assert.match(html, /src="app\.js\?v=13"/);
  assert.match(html, /class="area-launcher"/);
  assert.match(html, /Open research area/);
  assert.match(html, /class="rail-area-link"/);
  assert.match(html, /Address search continues in the <strong>Property data<\/strong> research area/);
  assert.doesNotMatch(html, /<a data-config-link="propertyDiscovery"[^>]*>Property search<\/a>/);
});

test("capability manifest separates implemented, enabled and planned states", () => {
  const manifest = capabilityManifest({ featureHrefs: { "property-records": "/properties" }, agentRuns: "/runs" });
  assert.equal(manifest.release, "release-0");
  assert.equal(manifest.features.filter((item) => item.enabled).length, 1);
  assert.equal(manifest.features.find((item) => item.id === "property-records").href, "/properties");
  assert.equal(manifest.features.find((item) => item.id === "sales-market").href, undefined);
  assert.deepEqual(capabilityState(manifest.services.find((item) => item.id === "rag")), { label: "Planned", tone: "planned" });
});

test("status aggregation ignores deliberate capability gates", () => {
  assert.equal(classifyHealth({ status: "healthy" }).readiness, "ready");
  assert.equal(classifyHealth({ status: "unhealthy" }).readiness, "unavailable");
  assert.equal(classifyHealth({ status: "degraded" }).readiness, "degraded");
  assert.equal(overallReadiness([
    { enabled: true, readiness: "ready" },
    { enabled: false, readiness: "unavailable" },
  ]), "ready");
  assert.equal(overallReadiness([{ enabled: true, readiness: "unknown" }]), "degraded");
});

test("research area labels come from the bounded registry", () => {
  assert.equal(researchAreaLabel("feature-3"), "Suburb context");
});

test("the Feature 1 bridge validates its complete nested contract", async () => {
  const expected = {
    links: { propertyDiscovery: "/properties", dataOperations: "/operations", agentRuns: "/runs" },
    primarySearchHref() {}, statusDependencies() {},
    evidence: {
      copy: Object.fromEntries(["headerDescription", "releasePanelDescription", "agentPanelDescription", "releaseEmpty", "releaseError", "agentEmpty", "agentError", "transitionLabel"].map((key) => [key, key])),
      published: { path: "/published", project() {}, href() {} },
      agentRuns: { path: "/runs", project() {}, href() {} },
    },
  };
  assert.equal(await loadFeature1Bridge({ importer: async () => ({
    createFeature1ShellAdapter: () => expected,
  }) }), expected);
  await assert.rejects(
    loadFeature1Bridge({ importer: async () => ({}) }),
    /createFeature1ShellAdapter/,
  );
  assert.throws(() => validateFeature1Adapter({ ...expected, evidence: {} }), /evidence\.copy/);
  assert.equal(await loadFeature1Bridge({ importer: async () => { throw new Error("offline"); } }), null);
  const started = performance.now();
  assert.equal(await loadFeature1Bridge({ importer: () => new Promise(() => {}), timeoutMs: 5 }), null);
  assert.ok(performance.now() - started < 100);
  let receiveLate;
  const lateAdapter = new Promise((resolve) => { receiveLate = resolve; });
  assert.equal(await loadFeature1Bridge({
    importer: () => new Promise((resolve) => setTimeout(() => resolve({ createFeature1ShellAdapter: () => expected }), 360)),
    onLateAdapter: receiveLate,
  }), null);
  assert.equal(await lateAdapter, expected);
});

test("the shell renders before its optional Feature 1 projection loads", () => {
  const app = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  assert.match(app, /feature-1-bridge\.js\?v=12/);
  assert.ok(app.indexOf("renderRoute();") < app.indexOf("loadFeature1Bridge({ overrides: externalConfig"));
  assert.doesNotMatch(app, /await\s+loadFeature1Bridge/);
});

test("AI activity context accepts only the bounded Feature 1 transition", () => {
  const valid = new URLSearchParams({
    feature_key: "student-1-propertyscope-data-platform",
    feature_label: "Property data",
    return_to: "/features/data-platform/#properties",
  });
  assert.equal(resolveResearchAreaContext(valid)?.label, "Property data");
  for (const params of [
    new URLSearchParams({ ...Object.fromEntries(valid), feature_label: "Spoofed bank" }),
    new URLSearchParams({ ...Object.fromEntries(valid), feature_key: "feature-4" }),
    new URLSearchParams({ ...Object.fromEntries(valid), return_to: "//evil.example" }),
    new URLSearchParams({ ...Object.fromEntries(valid), return_to: "/\\evil.example" }),
    new URLSearchParams({ ...Object.fromEntries(valid), feature_label: "x".repeat(81) }),
  ]) assert.equal(resolveResearchAreaContext(params), null);
});

test("shared routes use public same-origin projections and safe DOM rendering", () => {
  const nginx = readFileSync(new URL("./nginx.conf", import.meta.url), "utf8");
  const statusRoute = readFileSync(new URL("./routes/status.js", import.meta.url), "utf8");
  const evidenceRoute = readFileSync(new URL("./routes/evidence.js", import.meta.url), "utf8");
  assert.match(nginx, /location = \/api\/shared-health\/data-platform/);
  assert.match(nginx, /location \/api\/data-platform\//);
  assert.match(nginx, /location \/api\/ai-mode\//);
  assert.match(nginx, /location \/api\/v1\//);
  assert.match(nginx, /location \/api\//);
  assert.match(nginx, /location \/features\/data-platform\//);
  assert.match(nginx, /market-intelligence\|suburb-analytics\|due-diligence\|buyer-workspaces/);
  assert.match(nginx, /location \/operations\/ai-mode\//);
  assert.match(nginx, /proxy_pass \$data_platform_frontend_upstream/);
  assert.match(nginx, /resolver 127\.0\.0\.11/);
  assert.match(nginx, /absolute_redirect off/);
  assert.match(nginx, /proxy_pass \$data_platform_upstream/);
  assert.match(nginx, /proxy_pass \$ai_mode_upstream/);
  assert.doesNotMatch(statusRoute, /innerHTML/);
  assert.match(statusRoute, /featureRegistry\(config\)/);
  assert.doesNotMatch(evidenceRoute, /innerHTML/);
});

test("design tokens expose shared type, control, focus and layering contracts", () => {
  const tokens = readFileSync(new URL("./design-system/tokens.css", import.meta.url), "utf8");
  for (const token of ["--ps-type-body", "--ps-leading-body", "--ps-control-height", "--ps-focus-outline", "--ps-z-navigation"]) {
    assert.match(tokens, new RegExp(`${token}:`));
  }
  assert.match(tokens, /--ps-color-focus: var\(--ps-ocean-800\)/);
  assert.match(tokens, /--ps-color-focus-inverse: var\(--ps-ocean-200\)/);
  assert.match(tokens, /--ps-focus-outline: 3px solid var\(--ps-color-focus\)/);
  assert.match(tokens, /--ps-focus-outline-inverse: 3px solid var\(--ps-color-focus-inverse\)/);
  assert.doesNotMatch(tokens, /--ps-focus-outline:[^;]*rgba/);
});

test("AI workload dashboard leads with outcome and bounded recovery evidence", () => {
  const html = readFileSync(new URL("./operations/ai-mode/index.html", import.meta.url), "utf8");
  const app = readFileSync(new URL("./operations/ai-mode/app.js", import.meta.url), "utf8");
  assert.match(html, /assets\/app\.js\?v=11/);
  assert.match(app, /assets\/contexts\.js\?v=1/);
  assert.match(html, /AI review result/);
  assert.match(html, /aria-label="PropertyScope navigation"/);
  assert.match(html, /class="research-area-return"/);
  assert.match(html, /Back to research area/);
  assert.doesNotMatch(html, /student-1-propertyscope-data-platform/);
  assert.doesNotMatch(html, />Property data<\/option>/);
  assert.doesNotMatch(html, /<a href="\/features\/data-platform\/#properties">Property search<\/a>/);
  assert.match(html, /Technical performance/);
  for (const evidence of ["Schema repairs", "Provider retries", "Tool failures", "Replans"]) {
    assert.match(app, new RegExp(evidence));
  }
  assert.match(app, /Review summary/);
  assert.match(app, /What did not change/);
  assert.match(html, /id="feedback" class="inline-feedback" hidden/);
  assert.doesNotMatch(html, /id="feedback"[^>]+role=/);
  assert.match(html, /id="announcement"[^>]+role="status"/);
  assert.match(app, /Could not copy automatically/);
  assert.match(app, /if \(!navigator\.clipboard\?\.writeText\)/);
  assert.doesNotMatch(app, /safe failure/i);
  assert.doesNotMatch(app, /innerHTML/);
});
