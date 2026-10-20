import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync("student-2/frontend/index.html", "utf8");
const app = readFileSync("student-2/frontend/app.js", "utf8");
const fragment = readFileSync("student-2/frontend/integration/research-area.html", "utf8");
const styles = readFileSync("student-2/frontend/styles.css", "utf8");
const brief = readFileSync("student-2/frontend/integration/market-brief.js", "utf8");

test("market page exposes CRUD, evidence and AI regions", () => {
  for (const marker of ["case-list", "case-form", "volume-chart", "sales-body", "assistant-root"]) {
    assert.match(page, new RegExp(`id="${marker}"`));
  }
  // Criterion 4 is marked on citations and confidence, which the shared renderer owns.
  assert.match(page, /ai-chat\/styles\.css/);
  assert.match(page, /not a valuation or buying recommendation/i);
  assert.match(page, /Selected property/);
  assert.match(page, /The service checks the reference when you save/);
  assert.doesNotMatch(page, /property reference|UUID/i);
});

test("browser code uses the owned API and all CRUD verbs", () => {
  assert.match(app, /\/api\/market-intelligence\/v1/);
  for (const verb of ["POST", "PUT", "DELETE"]) assert.match(app, new RegExp(`method: "${verb}"`));
  assert.match(app, /form-property-choice/);
});

test("the assistant is the shared grounded renderer, scoped to the selected case", () => {
  assert.match(app, /createFeatureAssistant/);
  assert.match(app, /from "\.\/ai-chat\/index\.js"/);
  assert.match(app, /apiRoot: `\$\{API\}\/assistant`/);
  assert.match(app, /featureKey: "student-2-market-intelligence"/);
  // The selected case must reach the turn as context, or every answer is unscoped.
  assert.match(app, /setContext\(/);
  assert.match(app, /market_case_id: item\.id/);
});

test("research area fragment replaces the planned sales row", () => {
  assert.match(fragment, /data-feature-id="sales-market"/);
  assert.match(fragment, /data-feature-state="available"/);
  assert.match(fragment, /\/features\/market-intelligence\/#market-cases/);
});

test("the assistant is withheld until a market case is bound", () => {
  // An unscoped turn is rejected as a missing case_id, which reads as a fault to the user.
  assert.match(page, /id="assistant-root" hidden/);
  assert.match(page, /id="assistant-requires-case"/);
  assert.match(app, /byId\("assistant-root"\)\.hidden = !item/);
  // Creating the assistant lazily is what removes the load-order race with loadCases().
  assert.match(app, /initialiseAssistant\(\)/);
  assert.doesNotMatch(app, /^initialiseAssistant\(\);$/m);
});

test("the assistant is its own workspace column, not nested in the case detail", () => {
  // Nested in the detail panel it scrolled out of view on a long case.
  const workspace = page.slice(page.indexOf('id="market-cases"'));
  const detailEnd = workspace.indexOf('class="assistant-panel"');
  assert.ok(detailEnd > 0, "assistant-panel must exist inside the workspace");
  assert.ok(
    workspace.indexOf('class="detail-panel"') < detailEnd,
    "assistant-panel must be a sibling that follows the detail panel",
  );
  assert.doesNotMatch(page, /two-column/);
  assert.match(styles, /\.assistant-panel \{[^}]*position: sticky/);
  assert.match(styles, /--f2-assistant/);
});


test("both case-scoped surfaces are rebuilt when the selected case changes", () => {
  // setContext alone leaks case A's transcript into case B: the shared controller ignores it
  // while a turn is active and never clears completed turns. Release 2 requires the scope to be
  // rebound including any active run, so the surfaces are destroyed and remounted.
  assert.match(app, /function teardownCaseSurfaces\(\)/);
  assert.match(app, /state\.brief\?\.destroy\(\)/);
  assert.match(app, /state\.boundCaseId === item\.id/);
  assert.match(app, /state\.boundCaseId = item\.id;/);
  assert.match(app, /mountMarketBrief\(\{/);
});

test("the multi-agent panel is mounted through the shared barrel and withheld until a case is bound", () => {
  assert.match(app, /from "\.\/integration\/market-brief\.js"/);
  assert.match(page, /id="brief-root" hidden/);
  assert.match(page, /id="brief-requires-case"/);
  assert.match(page, /multi-agent\/styles\.css/);
  assert.match(app, /byId\("brief-root"\)\.hidden = !item/);
});

test("the brief panel is titled by its case rather than repeating the card heading", () => {
  // The shared panel renders its own <h2>, defaulting to the template title "Market case brief".
  // That is the card's own heading verbatim, so the page showed it twice until the mount passed
  // an explicit title.
  assert.match(page, /<h3 id="brief-title">Market case brief<\/h3>/);
  assert.match(brief, /title: caseName \? `Brief: \$\{caseName\}` : ""/);
  assert.match(app, /caseName: item\.name/);
});

test("the address is cleared where the brief is rebound, not on every case click", () => {
  // Clearing it in the click handler also stripped it when the reader re-clicked the case
  // already bound: syncCaseSurfaces() returns early there, so nothing put the run back and a
  // run still on screen stopped being linkable.
  const handler = app.slice(app.indexOf('byId("case-list").addEventListener'));
  const handlerBody = handler.slice(0, handler.indexOf("});"));
  assert.doesNotMatch(handlerBody, /showBriefInAddress/);
  assert.match(app, /if \(!keepRun\) showBriefInAddress\(null\);/);
});

test("a renamed case rebinds its surfaces and carries the open run across", () => {
  // The shared panel fixes its title at construction and exposes no setter, so a rename only
  // reaches the brief heading by remounting; the run must not be lost when that happens.
  assert.match(app, /state\.boundCaseId === item\.id && state\.boundCaseName === item\.name/);
  assert.match(app, /state\.boundCaseName = item\.name;/);
  assert.match(app, /const keepRun = state\.boundCaseId === item\.id \? state\.brief\?\.run\?\.id \|\| null : null;/);
  assert.match(app, /const resumed = keepRun/);
});

test("starting a brief outranks reopening a remembered one", () => {
  // The panel exposes no run id until its start POST returns, so the guard on state.brief.run
  // is not enough on its own: the lookup is cancelled the moment the reader submits.
  assert.match(app, /byId\("brief-root"\)\.addEventListener\(/);
  assert.match(app, /briefResumeTask\.cancel\(\)/);
});

test("the panel is withheld entirely where this deployment has no Multi-Agent Server", () => {
  // The server is a host process, so a Compose-only stack has none. Mounting anyway made the
  // page request a workflow template that could only answer 503, which failed visual capture.
  assert.match(page, /id="brief-unavailable"/);
  assert.match(page, /not enabled in this deployment/i);
  assert.match(app, /state\.briefEnabled = await marketBriefEnabled\(/);
  assert.match(app, /if \(!state\.briefEnabled\) return;/);
  assert.match(app, /byId\("brief-root"\)\.hidden = !item \|\| !state\.briefEnabled;/);
  // A brief that cannot run is not addressable either.
  assert.match(app, /state\.briefEnabled \? marketBriefRunId\(hash\) : null/);
});
