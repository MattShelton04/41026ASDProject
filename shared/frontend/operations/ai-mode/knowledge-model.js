/** Pure helpers for the Knowledge sources page; no DOM or network access. */

export function sectionOf(location) {
  const match = /(?:^|; )section (.+?); chars \d+-\d+$/.exec(String(location || ""));
  return match ? match[1] : "";
}

export function charRange(location) {
  const match = /chars (\d+)-(\d+)$/.exec(String(location || ""));
  return match ? { start: Number(match[1]), end: Number(match[2]) } : null;
}

/** Group a corpus listing into documents with their chunks in reading order. */
export function groupDocuments(chunks) {
  const documents = new Map();
  for (const chunk of chunks || []) {
    if (!documents.has(chunk.document_id)) {
      documents.set(chunk.document_id, {
        documentId: chunk.document_id,
        title: chunk.title,
        sourceUri: chunk.source_uri,
        sourceDate: chunk.source_date || null,
        evidenceKind: chunk.evidence_kind,
        characters: 0,
        chunks: [],
      });
    }
    const document = documents.get(chunk.document_id);
    document.chunks.push({
      chunkId: chunk.chunk_id,
      section: sectionOf(chunk.location),
      location: chunk.location,
      excerpt: chunk.excerpt,
    });
    document.characters += chunk.excerpt.length;
  }
  for (const document of documents.values()) {
    document.chunks.sort((a, b) => (charRange(a.location)?.start || 0) - (charRange(b.location)?.start || 0));
  }
  return [...documents.values()].sort((a, b) => a.title.localeCompare(b.title));
}

export function matchesFilter(document, text) {
  const needle = String(text || "").trim().toLowerCase();
  if (!needle) return true;
  return [document.title, document.documentId, ...document.chunks.map((chunk) => chunk.excerpt)]
    .some((value) => String(value).toLowerCase().includes(needle));
}

/** One sentence on what a grounded run would receive for this question. */
export function describeSearch(result) {
  const floor = formatScore(result?.grounding?.min_score);
  const used = (result?.candidates || []).filter((item) => item.used_in_grounding).length;
  switch (result?.status) {
    case "ready":
      return {
        tone: "confirmed",
        headline: `${used} passage${used === 1 ? "" : "s"} would be given to the assistant.`,
        detail: `Passages scoring below ${floor}, beyond the top ${result.grounding.top_k}, or over the per-document and context limits are shown for comparison but not sent.`,
      };
    case "no_match":
      return {
        tone: "partial",
        headline: "No passage reaches the relevance floor.",
        detail: `Nothing scored ${floor} or higher, so the assistant would report insufficient context instead of answering from these documents.`,
      };
    case "empty":
      return { tone: "unknown", headline: "This corpus has no ingested documents.", detail: "Run the ingest command for this feature's corpus manifest." };
    default:
      return { tone: "partial", headline: "Retrieval is unavailable.", detail: "The RAG service did not return a result. Ordinary feature pages still work." };
  }
}

export function candidateNote(candidate, grounding) {
  if (candidate.used_in_grounding) return "Sent to the assistant";
  if (candidate.score < grounding.min_score) return `Below relevance floor ${formatScore(grounding.min_score)}`;
  return "Not selected (rank or limits)";
}

export function formatScore(value) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
}

export function corpusKey(item) {
  return `${item.feature_key}:${item.corpus_id}`;
}

export function statusLabel(status) {
  return {
    ready: "Ready",
    empty: "Not ingested",
    unavailable: "Unavailable",
    disabled: "Retrieval disabled",
  }[status] || "Unknown";
}
