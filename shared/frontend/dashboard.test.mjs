import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { capabilityManifest, capabilityState } from "./capabilities.js";
import { parseShellRoute, researchAreaLabel } from "./core.js";
import { featureRegistry, findFeature } from "./features.js";
import { acceptedReleaseReferences, agentRunReferences } from "./routes/evidence.js";
import { classifyHealth, overallReadiness } from "./routes/status.js";

test("shared hash routes are bounded and unknown fragments return home", () => {
  assert.equal(parseShellRoute("#system-status"), "system-status");
  assert.equal(parseShellRoute("#/evidence?view=accepted"), "evidence");
  assert.equal(parseShellRoute("#release-roadmap"), "release-roadmap");
  assert.equal(parseShellRoute("#features"), "features");
  assert.equal(parseShellRoute("#operations"), "home");
  assert.equal(parseShellRoute("#future-student-feature"), "home");
});

test("feature registry is the bounded source for shell routes and availability", () => {
  const features = featureRegistry();
  assert.equal(features.length, 5);
  assert.equal(features.filter((item) => item.href).length, 1);
  assert.equal(findFeature("data-platform").href, "/features/data-platform/#properties");
  assert.equal(findFeature("student-4-due-diligence").frontendBase, "/features/due-diligence/");
  assert.equal(findFeature("market-intelligence").href, undefined);
  assert.ok(features.every((item) => item.healthPath?.startsWith("/api/shared-health/")));
  assert.equal(featureRegistry({ propertyDiscovery: "/custom/#properties" })[0].href, "/custom/#properties");
});

test("capability manifest separates implemented, enabled and planned states", () => {
  const manifest = capabilityManifest({ propertyDiscovery: "/properties", agentRuns: "/runs" });
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

test("evidence projections retain IDs, ownership labels, hashes and unknown coverage", () => {
  const releases = acceptedReleaseReferences({ items: [{
    id: "release-1", dataset_id: "addresses", target_feature: "feature-1",
    release_version: "2026.08", record_count: 10, content_sha256: "abc", accepted_at: "2026-08-15T00:00:00Z",
  }] });
  assert.deepEqual(releases[0], {
    id: "release-1", dataset: "addresses", area: "Property records", version: "2026.08",
    records: 10, acceptedAt: "2026-08-15T00:00:00Z", coverage: "unknown", hash: "abc",
  });
  const runs = agentRunReferences({ items: [{ id: "run-1", feature_key: "feature-4", status: "failed" }] });
  assert.equal(runs[0].area, "Site and planning");
  assert.equal(runs[0].objective, "Objective hidden by policy");
  assert.equal(researchAreaLabel("feature-3"), "Suburb context");
  assert.equal(agentRunReferences({ items: [{ id: "fixture", feature_key: "student-1-integration-test" }] }).length, 0);
  assert.equal(acceptedReleaseReferences({ items: [{ id: "future", target_feature: "feature-5" }] }).length, 0);
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
  assert.match(tokens, /--ps-focus-outline: 3px solid var\(--ps-ocean-800\)/);
  assert.doesNotMatch(tokens, /--ps-focus-outline:[^;]*rgba/);
});
