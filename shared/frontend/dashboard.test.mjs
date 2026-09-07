import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import test from "node:test";

import { capabilityManifest, capabilityState } from "./capabilities.js";
import { parseShellRoute } from "./core.js";
import { featureRegistry, findFeature, researchAreaLabel } from "./features.js";
import { loadFeature1Bridge, validateFeature1Adapter } from "./feature-1-bridge.js";
import { resolveResearchAreaContext } from "./operations/ai-mode/contexts.js";
import { classifyHealth, overallReadiness } from "./routes/status.js";
import { SHARED_ASSISTANT_SCOPES, sharedAssistantSuggestions } from "./routes/assistant.js";
import { loadEvidenceAdapter, projectEvidenceRows, validateEvidenceAdapter } from "./routes/evidence.js";

function attributes(source) {
  return Object.fromEntries(
    [...source.matchAll(/([a-z][a-z0-9-]*)="([^"]*)"/g)].map((match) => [match[1], match[2]]),
  );
}

function fragmentRows(source) {
  return [...source.matchAll(/<article\s+(?<attributes>[\s\S]*?)>(?<body>[\s\S]*?)<\/article>/g)]
    .map((match) => ({ attributes: attributes(match.groups.attributes), body: match.groups.body }));
}

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
  assert.equal(features.filter((item) => item.href).length, 5);
  assert.equal(findFeature("suburb-analytics").href, "/features/suburb-analytics/#suburbs");
  assert.equal(findFeature("data-platform").href, "/features/data-platform/#properties");
  assert.equal(findFeature("student-4-due-diligence").frontendBase, "/features/due-diligence/");
  assert.equal(
    findFeature("market-intelligence").href,
    "/features/market-intelligence/#market-cases",
  );
  assert.ok(features.every((item) => item.healthPath?.startsWith("/api/shared-health/")));
  assert.equal(featureRegistry({ featureHrefs: { "property-records": "/custom/#properties" } })[0].href, "/custom/#properties");
  assert.equal(features[0].label, "Property data");
});

test("shared navigation distinguishes global destinations from research-area transitions", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  assert.match(html, /src="app\.js\?v=18"/);
  assert.match(html, /class="area-launcher"/);
  assert.match(html, /aria-label="Open the Property data research area"/);
  assert.match(html, /class="rail-area-link"/);
  assert.match(html, /Address search continues in the <strong>Property data<\/strong> research area/);
  assert.doesNotMatch(html, /<a data-config-link="propertyDiscovery"[^>]*>Property search<\/a>/);
});

test("shared home loads the pinned local HTMX build with a strict configuration", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const app = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  const asset = readFileSync(new URL("./vendor/htmx-2.0.10.min.js", import.meta.url));
  const license = readFileSync(new URL("./vendor/HTMX-LICENSE.txt", import.meta.url), "utf8");
  const provenance = readFileSync(new URL("./vendor/README.md", import.meta.url), "utf8");

  assert.match(html, /src="vendor\/htmx-2\.0\.10\.min\.js"/);
  assert.ok(html.indexOf("htmx-2.0.10.min.js") < html.indexOf("app.js?v=18"));
  assert.match(html, /"allowEval":false/);
  assert.match(html, /"allowScriptTags":false/);
  assert.doesNotMatch(html, /https?:\/\/[^"']*htmx/i);
  assert.equal(
    createHash("sha256").update(asset).digest("hex"),
    "71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de",
  );
  assert.match(asset.toString(), /version:"2\.0\.10"/);
  assert.match(license, /^Zero-Clause BSD/);
  assert.match(provenance, /unpkg\.com\/htmx\.org@2\.0\.10\/dist\/htmx\.min\.js/);
  assert.match(provenance, /71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de/);
  assert.doesNotMatch(app, /homeFeatureRow|renderHomeFeatures/);
  assert.match(app, /window\.htmx\?\.process\(main\)/);
  assert.match(app, /htmx:responseError/);
  assert.match(app, /applyConfigLinks\(region\)/);
});

test("research-area fragment stays in exact parity with the feature registry", () => {
  const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
  const fragment = readFileSync(
    new URL("./fragments/research-areas.html", import.meta.url),
    "utf8",
  );
  const rows = fragmentRows(fragment);
  const features = featureRegistry();
  const renderedOrder = [
    ...features.filter((feature) => feature.enabled),
    ...features.filter((feature) => !feature.enabled),
  ];

  assert.match(html, /hx-get="\/fragments\/research-areas\.html"/);
  assert.match(html, /hx-trigger="load"/);
  assert.match(html, /hx-target="this"/);
  assert.match(html, /hx-swap="innerHTML"/);
  assert.match(html, /hx-indicator="#research-areas-loading"/);
  assert.match(html, /hx-disabled-elt="#research-areas-retry"/);
  assert.match(html, /id="research-areas-status"[^>]*role="status"[^>]*aria-live="polite"/);
  assert.match(html, /data-research-area-retry/);
  assert.match(html, /Property data remains available from the link above/);
  assert.equal(rows.length, 5);
  assert.deepEqual(
    rows.map((row) => row.attributes["data-feature-id"]),
    renderedOrder.map((feature) => feature.id),
  );

  for (const [index, feature] of renderedOrder.entries()) {
    const row = rows[index];
    assert.equal(row.attributes["data-feature-label"], feature.label);
    assert.equal(row.attributes["data-feature-owner"], feature.owner);
    assert.equal(
      row.attributes["data-feature-route"],
      `${feature.frontendBase}${feature.defaultHash}`,
    );
    assert.equal(row.attributes["data-feature-implemented"], String(feature.implemented));
    assert.equal(row.attributes["data-feature-enabled"], String(feature.enabled));
    if (feature.implemented && feature.enabled) {
      assert.equal(row.attributes["data-feature-state"], "available");
      assert.match(row.body, new RegExp(`href="${feature.frontendBase}${feature.defaultHash}"`));
    } else {
      assert.equal(row.attributes["data-feature-state"], "planned");
      assert.match(row.body, />Planned</);
      assert.match(row.body, />Not available yet</);
      assert.doesNotMatch(row.body, /<(?:a|button)\b/);
    }
  }
});

test("capability manifest separates implemented, enabled and planned states", () => {
  const manifest = capabilityManifest({ featureHrefs: { "property-records": "/properties" }, agentRuns: "/runs" });
  assert.equal(manifest.release, "release-0");
  assert.equal(manifest.features.filter((item) => item.enabled).length, 5);
  assert.equal(manifest.features.find((item) => item.id === "property-records").href, "/properties");
  assert.equal(
    manifest.features.find((item) => item.id === "sales-market").href,
    "/features/market-intelligence/#market-cases",
  );
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
      action: { label: "Open source workspace", href: "/operations" },
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
  assert.throws(() => validateFeature1Adapter({ ...expected, evidence: {} }), /evidence\.action/);
  let loadError = null;
  assert.equal(await loadFeature1Bridge({
    importer: async () => { throw new Error("offline"); },
    onError: (error) => { loadError = error; },
  }), null);
  assert.match(loadError.message, /offline/);
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
  let receiveLateError;
  const lateError = new Promise((resolve) => { receiveLateError = resolve; });
  assert.equal(await loadFeature1Bridge({
    importer: () => new Promise((resolve) => setTimeout(() => resolve({}), 10)),
    timeoutMs: 1,
    onLateAdapter: () => assert.fail("invalid adapter must not be installed"),
    onError: receiveLateError,
  }), null);
  assert.match((await lateError).message, /createFeature1ShellAdapter/);
});

test("the optional shell evidence adapter is domain-neutral, closed, and manifest-loaded", async () => {
  const adapter = {
    action: { label: "Open source workspace", href: "/source" },
    copy: Object.fromEntries(["headerDescription", "releasePanelDescription", "agentPanelDescription", "releaseEmpty", "releaseError", "agentEmpty", "agentError", "transitionLabel"].map((key) => [key, key])),
    published: { path: "/published", project() {}, href() {} },
    agentRuns: { path: "/runs", project() {}, href() {} },
  };
  assert.equal(validateEvidenceAdapter(adapter), adapter);
  assert.throws(() => validateEvidenceAdapter({ ...adapter, action: null }), /action\.label/);
  assert.throws(() => validateEvidenceAdapter({ ...adapter, published: { ...adapter.published, path: "" } }), /published\.path/);
  assert.throws(() => validateEvidenceAdapter({ ...adapter, published: { ...adapter.published, path: "https://other.example/releases" } }), /same-origin path/);
  assert.throws(() => validateEvidenceAdapter({ ...adapter, inventedFeatureEvidence: {} }), /unsupported inventedFeatureEvidence/);
  let importedPath = null;
  assert.equal(await loadEvidenceAdapter(
    {
      featureKey: "student-2-example",
      frontendBase: "/features/example/",
      evidenceAdapterPath: "/features/example/integration/evidence.js",
    },
    {
      importer: async (path) => {
        importedPath = path;
        return { createShellEvidenceAdapter: () => adapter };
      },
    },
  ), adapter);
  assert.equal(importedPath, "/features/example/integration/evidence.js");
  await assert.rejects(
    loadEvidenceAdapter(
      { featureKey: "student-2-example", frontendBase: "/features/example/", evidenceAdapterPath: "/features/example/evidence.js" },
      { importer: async () => ({}) },
    ),
    /createShellEvidenceAdapter/,
  );
  await assert.rejects(
    loadEvidenceAdapter({ featureKey: "student-2-example", frontendBase: "/features/example/", evidenceAdapterPath: "https://other.example/evidence.js" }),
    /same-origin path/,
  );
  await assert.rejects(
    loadEvidenceAdapter({ featureKey: "student-2-example", frontendBase: "/features/example/", evidenceAdapterPath: "/features/example/%2e%2e/other/evidence.js" }),
    /canonical path/,
  );
  assert.throws(
    () => projectEvidenceRows({ project: () => null, href: () => "/safe" }, {}, "https://propertyscope.test/"),
    /must return an array/,
  );
  assert.throws(
    () => projectEvidenceRows({ project: () => [{ id: "one" }], href: () => "javascript:alert(1)" }, {}, "https://propertyscope.test/"),
    /same-origin/,
  );
  const source = readFileSync(new URL("./routes/evidence.js", import.meta.url), "utf8");
  assert.doesNotMatch(source, /getFeature1Adapter|Property data|sale|crime|school|planning|buyer/i);
});

test("the shell renders before its optional Feature 1 projection loads", () => {
  const app = readFileSync(new URL("./app.js", import.meta.url), "utf8");
  assert.ok(app.indexOf("renderRoute();") < app.indexOf("loadFeature1Bridge({"));
  assert.doesNotMatch(app, /await\s+loadFeature1Bridge/);
  assert.match(app, /if \(feature1Enabled\) \{\s*loadFeature1Bridge\(/);
  assert.match(app, /ENABLED_FEATURES\.filter\(\(item\) => item\.evidenceAdapterPath\)/);
  assert.match(app, /loadEvidenceAdapter\(feature/);
  assert.match(app, /\["features", "system-status"\]\.includes\(parseShellRoute\(location\.hash\)\)/);
  assert.doesNotMatch(app, /parseShellRoute\(location\.hash\) !== "home"/);
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
  const nginx = [
    readFileSync(new URL("./nginx.conf", import.meta.url), "utf8"),
    readFileSync(new URL("./generated/enabled-feature-routes.conf", import.meta.url), "utf8"),
  ].join("\n");
  const statusRoute = readFileSync(new URL("./routes/status.js", import.meta.url), "utf8");
  const evidenceRoute = readFileSync(new URL("./routes/evidence.js", import.meta.url), "utf8");
  assert.match(nginx, /location = \/api\/shared-health\/data-platform/);
  assert.match(nginx, /location ~ \^\/health\(\?:\/\|\$\)/);
  assert.match(nginx, /Only \/healthz is supported by the Shared frontend/);
  assert.match(nginx, /location \^~ \/api\/data-platform\/v1\//);
  assert.match(nginx, /location \/api\/ai-mode\//);
  assert.match(nginx, /location \/api\/v1\//);
  assert.match(nginx, /location \/api\//);
  assert.match(nginx, /location \^~ \/features\/data-platform\//);
  assert.match(nginx, /market-intelligence\|suburb-analytics\|due-diligence\|buyer-workspaces/);
  assert.match(nginx, /location \/operations\/ai-mode\//);
  assert.match(nginx, /location \/fragments\/\s*\{\s*try_files \$uri =404;/);
  assert.match(nginx, /proxy_pass \$enabled_feature_0_frontend/);
  assert.match(nginx, /resolver 127\.0\.0\.11/);
  assert.match(nginx, /absolute_redirect off/);
  assert.match(nginx, /proxy_pass \$enabled_feature_0_backend/);
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
  assert.match(html, /assets\/app\.js\?v=12/);
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
