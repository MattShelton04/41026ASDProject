import assert from "node:assert/strict";
import test from "node:test";

import {
  candidateNote,
  charRange,
  describeSearch,
  groupDocuments,
  matchesFilter,
  sectionOf,
} from "./knowledge-model.js";

const chunk = (documentId, title, location, excerpt = "Text.") => ({
  chunk_id: `${documentId}-${location}`,
  document_id: documentId,
  title,
  source_uri: "https://example.org",
  source_date: "2026-09-26",
  evidence_kind: "project_guidance",
  location,
  excerpt,
});

test("locations yield their section heading and character range", () => {
  assert.equal(sectionOf("Guide: seifa; section Reading a decile; chars 400-900"), "Reading a decile");
  assert.equal(sectionOf("Guide: seifa; chars 1-399"), "");
  assert.deepEqual(charRange("chars 12-40"), { start: 12, end: 40 });
});

test("chunks are grouped by document and ordered by position", () => {
  const documents = groupDocuments([
    chunk("zeta", "Zeta", "section Later; chars 500-900"),
    chunk("zeta", "Zeta", "chars 1-499"),
    chunk("alpha", "Alpha", "chars 1-10"),
  ]);
  assert.deepEqual(documents.map((item) => item.documentId), ["alpha", "zeta"]);
  assert.deepEqual(documents[1].chunks.map((item) => item.section), ["", "Later"]);
});

test("filtering searches titles and passage text", () => {
  const [document] = groupDocuments([chunk("seifa", "SEIFA scores", "chars 1-5", "Decile 1 is lowest.")]);
  assert.ok(matchesFilter(document, "decile"));
  assert.ok(matchesFilter(document, ""));
  assert.ok(!matchesFilter(document, "flood"));
});

test("search summaries distinguish answerable, unmatched and unavailable questions", () => {
  const grounding = { min_score: 0.55, top_k: 5 };
  const ready = describeSearch({ status: "ready", grounding, candidates: [{ used_in_grounding: true }, { used_in_grounding: false }] });
  assert.match(ready.headline, /^1 passage /);
  assert.equal(describeSearch({ status: "no_match", grounding, candidates: [] }).tone, "partial");
  assert.match(describeSearch({ status: "unavailable" }).headline, /unavailable/);
});

test("each candidate explains why it was or was not sent", () => {
  const grounding = { min_score: 0.55 };
  assert.equal(candidateNote({ used_in_grounding: true, score: 0.8 }, grounding), "Sent to the assistant");
  assert.match(candidateNote({ used_in_grounding: false, score: 0.4 }, grounding), /Below relevance floor/);
  assert.match(candidateNote({ used_in_grounding: false, score: 0.6 }, grounding), /Not selected/);
});
