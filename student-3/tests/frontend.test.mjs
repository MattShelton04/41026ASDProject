import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
const js = readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");

test("readiness follows the feature ingress on both direct and shared hosts", () => {
  assert.match(js, /fetch\(new URL\("\.\/health\/ready", import\.meta\.url\)\)/);
  assert.doesNotMatch(js, /fetch\("\/health\/ready"\)/);
  assert.equal(new URL("./health/ready", "http://localhost:5600/app.js").href,
    "http://localhost:5600/health/ready");
  assert.equal(new URL("./health/ready", "http://localhost:5100/features/suburb-analytics/app.js").href,
    "http://localhost:5100/features/suburb-analytics/health/ready");
});

test("frontend exposes map, chart table, CRUD and responsible-use language", () => {
  assert.match(html, /id="map"/);
  assert.match(html, /id="suburb-detail"/);
  assert.match(html, /id="offence"/);
  assert.match(html, /id="assistant-root"/);
  assert.match(html, /<table>/);
  assert.match(html, /New comparison/);
  assert.match(html, /does not label suburbs safe, unsafe, good or bad/);
  assert.match(js, /crime\/compare/);
  assert.match(js, /area-series/);
  assert.match(js, /createFeatureAssistant/);
  assert.match(js, /\(missing\)/);
  assert.match(js, /setLayerData\("suburbs"/);
  assert.match(js, /createMap/);
});
