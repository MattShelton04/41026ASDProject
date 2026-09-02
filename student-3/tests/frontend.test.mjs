import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const html = readFileSync(new URL("../frontend/index.html", import.meta.url), "utf8");
const js = readFileSync(new URL("../frontend/app.js", import.meta.url), "utf8");

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
