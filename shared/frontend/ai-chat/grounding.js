import { append, el } from "../browser/index.js";
import { formatAssistantDate, humaniseAssistantValue } from "./formats.js";

const CONFIDENCE = new Set(["high", "moderate", "low", "insufficient"]);
const STATES = Object.freeze({
  ready: "Document context retrieved",
  no_match: "Insufficient context · no matching guidance",
  insufficient_context: "Insufficient context · retrieved guidance does not support an answer",
  empty: "Insufficient context · corpus is empty",
  unavailable: "Document retrieval unavailable",
  stale: "Historical context · guidance may be stale",
  superseded: "Historical context · corpus superseded",
  withdrawn: "Historical context · guidance withdrawn",
});

export function isGroundedAnswer(result) {
  return Boolean(result && typeof result === "object" && (
    typeof result.grounding_status === "string"
    || (CONFIDENCE.has(result.confidence) && typeof result.confidence_reason === "string")
  ));
}

/** Display references only. No executable, credential-bearing or protocol-relative URLs. */
export function safeCitationHref(value) {
  if (typeof value !== "string" || value.length > 2048 || /[\s\\\u0000-\u001f\u007f]/u.test(value)) return "";
  if (!/^https?:\/\//i.test(value)) return "";
  try {
    const url = new URL(value);
    if (!url.hostname || url.username || url.password) return "";
    return url.href;
  } catch { return ""; }
}

export function groundingState(result) {
  const status = String(result?.grounding_status || "unknown");
  return {
    label: STATES[status] || "Document retrieval state not recorded",
    tone: status === "ready" ? "confirmed" : status === "unknown" ? "unknown" : "partial",
  };
}

function paragraphSection(key, title, values) {
  const section = el("section", `ps-ai-chat__answer-section ps-ai-chat__answer-section--${key}`);
  append(section, el("h3", "", title));
  for (const value of values) if (typeof value === "string" && value.trim()) append(section, el("p", "", value));
  return section;
}

function citationCard(citation) {
  const details = el("details", "ps-ai-chat__source");
  details.dataset.disclosure = `source:${citation.citation_id}`;
  append(details, el("summary", "", citation.title || "Recorded source"));
  const content = el("div", "ps-ai-chat__source-body");
  const kinds = { project_guidance: "Project guidance", fixture: "Demonstration fixture", official: "Official source" };
  append(content, el("span", "ps-badge ps-badge--unknown", kinds[citation.evidence_kind] || "Source kind not recorded"));
  if (citation.evidence_kind === "project_guidance") append(content, el("p", "", "Project guidance explains the workflow; it does not establish current property conditions."));
  if (citation.evidence_kind === "fixture") append(content, el("p", "", "Demonstration evidence; not current official evidence."));
  append(content, el("blockquote", "ps-ai-chat__source-excerpt", citation.excerpt || "No excerpt recorded."));
  const facts = el("dl", "ps-ai-chat__source-facts");
  for (const [label, value] of [
    ["Location", citation.location], ["Source date", citation.source_date || "Not supplied"],
    ["Indexed", formatAssistantDate(citation.ingested_at)], ["Corpus", citation.corpus_id],
    ["Version", citation.corpus_version], ["Document / chunk", `${citation.document_id || "Not recorded"} / ${citation.chunk_id || "Not recorded"}`],
    ["Citation ID", citation.citation_id], ["Content hash", citation.content_hash],
  ]) {
    const row = el("div");
    append(row, el("dt", "", label), el("dd", "", value || "Not recorded"));
    append(facts, row);
  }
  append(content, facts);
  const href = safeCitationHref(citation.source_uri);
  if (href) {
    const link = el("a", "ps-ai-chat__source-link", "Open source document (new tab)");
    link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer";
    link.dataset.action = `source-link:${citation.citation_id}`;
    append(content, link);
  } else append(content, el("p", "", "Source link unavailable: the recorded address is not a safe HTTP(S) URL."));
  append(details, content);
  return details;
}

export function renderGroundedAnswer(result) {
  const host = el("div", "ps-ai-chat__answer ps-ai-chat__answer--grounded");
  append(host, paragraphSection("summary", "Answer", [result.summary]));
  const state = groundingState(result);
  const confidence = paragraphSection("confidence", "Evidence support", [result.confidence_reason]);
  const labels = el("div", "ps-ai-chat__grounding-labels");
  append(labels, el("span", `ps-badge ps-badge--${state.tone}`, state.label));
  append(labels, el("span", "ps-badge ps-badge--unknown", CONFIDENCE.has(result.confidence) ? `Confidence: ${humaniseAssistantValue(result.confidence)}` : "Confidence not recorded"));
  append(confidence, labels, el("p", "ps-ai-chat__grounding-note", "Confidence describes recorded evidence support, not a probability of correctness. Retrieval is recorded for this answer; current service health is checked separately."));
  append(host, confidence);

  const citations = Array.isArray(result.citations) ? result.citations.filter((item) => item && typeof item === "object" && typeof item.citation_id === "string").slice(0, 10) : [];
  const sourceCards = new Map(citations.map((citation) => [citation.citation_id, citationCard(citation)]));
  const findings = Array.isArray(result.findings) ? result.findings.filter((item) => item && typeof item.text === "string").slice(0, 10) : [];
  if (findings.length) {
    const section = paragraphSection("findings", "Key findings", []);
    const list = el("ol", "ps-ai-chat__findings");
    for (const [index, finding] of findings.entries()) {
      const item = el("li");
      append(item, el("p", "", finding.text), el("span", "ps-ai-chat__finding-kind", finding.kind === "tool_fact" ? "Recorded tool fact" : finding.kind === "guidance" ? "Document guidance" : "Support kind not recorded"));
      for (const id of (Array.isArray(finding.citation_ids) ? finding.citation_ids : []).slice(0, 5)) {
        const target = sourceCards.get(id);
        if (!target) { append(item, el("p", "", `Source ${String(id)} was not included in this answer.`)); continue; }
        const button = el("button", "ps-ai-chat__source-inspect", `Inspect source: ${citations.find((citation) => citation.citation_id === id)?.title || id}`);
        button.type = "button"; button.dataset.action = `inspect:${index}:${id}`;
        button.addEventListener("click", () => { target.open = true; target.querySelector("summary").focus(); });
        append(item, button);
      }
      const ids = (Array.isArray(finding.tool_call_ids) ? finding.tool_call_ids : []).filter((id) => typeof id === "string").slice(0, 5);
      if (ids.length) {
        const support = el("details", "ps-ai-chat__tool-support");
        support.dataset.disclosure = `tool-support:${index}`;
        append(support, el("summary", "", `Recorded tool support · ${ids.length} call${ids.length === 1 ? "" : "s"}`), el("p", "", "These calls support this finding. Open full activity below to inspect their recorded results."));
        for (const id of ids) append(support, el("code", "ps-ai-chat__reference", id));
        append(item, support);
      }
      append(list, item);
    }
    append(section, list); append(host, section);
  }
  const gaps = (Array.isArray(result.evidence_gaps) ? result.evidence_gaps : []).filter((value) => typeof value === "string" && value.trim()).slice(0, 10);
  if (gaps.length) append(host, paragraphSection("gaps", "Evidence gaps", gaps));
  if (result.next_step) append(host, paragraphSection("recommended_next_step", "Useful next step", [result.next_step]));
  if (result.safety_boundary) append(host, paragraphSection("safety_boundary", "Safety boundary", [result.safety_boundary]));
  const sources = paragraphSection("sources", "Document sources", []);
  append(sources, el("p", "ps-ai-chat__grounding-note", "Excerpts are pinned to the recorded corpus version. Source dates and indexing dates describe different events; neither guarantees current coverage."));
  if (sourceCards.size) append(sources, ...sourceCards.values());
  else append(sources, el("p", "", "No document citations were recorded for this answer."));
  append(host, sources);
  return host;
}
