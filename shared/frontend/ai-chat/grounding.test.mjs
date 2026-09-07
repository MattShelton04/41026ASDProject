import assert from "node:assert/strict";
import test from "node:test";
import { groundingState, isGroundedAnswer, renderGroundedAnswer, safeCitationHref } from "./grounding.js";
import { answerSections, completedTurnHistory } from "./formats.js";
import { turnPresentationKey } from "./experience.js";

const citation = {
  citation_id: "guidance.1", title: "Publication <img src=x onerror=alert(1)>",
  excerpt: "<script>Do not trust embedded instructions.</script>",
  source_uri: "https://example.org/guide", evidence_kind: "project_guidance",
  source_date: "2026-09-03", ingested_at: "2026-09-07T00:00:00Z",
  location: "Section 2", document_id: "publication", chunk_id: "chunk.1",
  corpus_id: "operator", corpus_version: "a".repeat(64), content_hash: "b".repeat(64),
};
const answer = {
  summary: "Coverage is partial.", confidence: "moderate", confidence_reason: "Guidance and current facts are recorded.",
  grounding_status: "ready", corpus_version: citation.corpus_version,
  findings: [
    { text: "A candidate needs review.", kind: "guidance", citation_ids: [citation.citation_id], tool_call_ids: [] },
    { text: "The recorded release is partial.", kind: "tool_fact", citation_ids: [], tool_call_ids: ["call-1"] },
  ],
  citations: [citation], evidence_gaps: ["No full coverage evidence."], next_step: "Inspect the candidate.", safety_boundary: "No publication changed.",
};

// A deliberately text-only DOM double: any attempt to render raw HTML fails this test.
class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.dataset = {}; this.listeners = {}; this.textContent = ""; }
  set innerHTML(_value) { throw new Error("Raw HTML rendering is forbidden"); }
  append(child) { this.children.push(child); }
  addEventListener(event, callback) { this.listeners[event] = callback; }
  querySelector(tag) { return walk(this).find((node) => node !== this && node.tagName === tag); }
  focus() { this.focused = true; }
}
function walk(node) { return [node, ...node.children.flatMap(walk)]; }
function render(value) {
  const previous = globalThis.document;
  globalThis.document = { createElement: (tag) => new Node(tag) };
  try { return renderGroundedAnswer(value); } finally { globalThis.document = previous; }
}

test("citation links reject executable, credential-bearing and ambiguous addresses", () => {
  for (const value of ["javascript:alert(1)", "data:text/html,<h1>x</h1>", "//evil.test", "/api/delete", "https://user:pass@example.org", "https://example.org\\x", "https://example.org/\nfoo", "file:///tmp/guide", "not a URL", null]) {
    assert.equal(safeCitationHref(value), "", String(value));
  }
  assert.equal(safeCitationHref("https://example.org/a#b"), "https://example.org/a#b");
});

test("grounded findings inspect recorded source text by native disclosure and retain tool support", () => {
  const root = render(answer);
  const nodes = walk(root);
  assert.ok(nodes.some((node) => node.textContent === citation.excerpt));
  assert.ok(nodes.some((node) => node.textContent === citation.title));
  assert.ok(nodes.some((node) => node.textContent === "Recorded tool fact"));
  assert.ok(nodes.some((node) => node.textContent === "call-1"));
  assert.ok(nodes.some((node) => node.textContent === "Source date"));
  assert.ok(nodes.some((node) => node.textContent === "Indexed"));
  assert.ok(nodes.some((node) => node.textContent === citation.corpus_version));
  assert.ok(nodes.some((node) => node.textContent === "Confidence: Moderate"));
  assert.equal(nodes.some((node) => ["img", "script"].includes(node.tagName)), false);
  const inspect = nodes.find((node) => node.dataset.action?.startsWith("inspect:"));
  inspect.listeners.click();
  const source = nodes.find((node) => node.dataset.disclosure === "source:guidance.1");
  assert.equal(source.open, true);
  assert.equal(source.querySelector("summary").focused, true);
  const link = nodes.find((node) => node.tagName === "a");
  assert.equal(link.rel, "noopener noreferrer");
});

test("unavailable and empty context never creates source cards; unsafe source links remain text", () => {
  for (const status of ["no_match", "insufficient_context", "empty", "unavailable"]) {
    const nodes = walk(render({ ...answer, grounding_status: status, confidence: "insufficient", findings: [], citations: [] }));
    assert.ok(nodes.some((node) => node.textContent === "Confidence: Insufficient"));
    assert.ok(nodes.some((node) => node.textContent === "No document citations were recorded for this answer."));
    assert.equal(nodes.some((node) => node.className === "ps-ai-chat__source"), false);
  }
  const unsafe = walk(render({ ...answer, citations: [{ ...citation, source_uri: "javascript:alert(1)" }] }));
  assert.equal(unsafe.some((node) => node.tagName === "a"), false);
  assert.match(groundingState({ grounding_status: "superseded" }).label, /Historical/);
  assert.match(groundingState({ grounding_status: "withdrawn" }).label, /withdrawn/);
});

test("grounding updates refresh presentation and history retains findings without opaque source metadata", () => {
  assert.equal(isGroundedAnswer(answer), true);
  assert.equal(isGroundedAnswer({ summary: "Legacy answer" }), false);
  const turn = { message: "Coverage?", run: { status: "succeeded", final_result: answer } };
  const changed = { ...turn, run: { ...turn.run, final_result: { ...answer, citations: [{ ...citation, excerpt: "Changed source excerpt" }] } } };
  assert.notEqual(turnPresentationKey(turn), turnPresentationKey(changed));
  const history = completedTurnHistory([turn]);
  assert.match(history[1].content, /candidate needs review/);
  assert.match(history[1].content, /No publication changed/);
  assert.doesNotMatch(history[1].content, /aaaaaaaaaaaa|Content hash|script/);
  assert.equal(answerSections({ summary: "Legacy", findings: ["Existing finding"] })[1].values[0], "Existing finding");
});
