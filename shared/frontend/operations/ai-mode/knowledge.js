import { requestJson } from "/operations/ai-mode/assets/polling.js";
import { activityAreaLabel } from "/operations/ai-mode/assets/contexts.js";
import { safeCitationHref } from "/operations/ai-mode/shared/ai-chat/grounding.js";
import {
  candidateNote,
  corpusKey,
  describeSearch,
  formatScore,
  groupDocuments,
  matchesFilter,
  statusLabel,
} from "/operations/ai-mode/assets/knowledge-model.js";

const API = "/api/v1/operations/knowledge";
const ui = Object.fromEntries([
  "connection-dot", "connection-state", "corpus-list", "corpus-detail", "corpus-area", "corpus-title",
  "corpus-facts", "search-form", "search-query", "search-results", "document-filter",
  "document-summary", "document-list",
].map((id) => [id, document.getElementById(id)]));
const state = { listing: null, selected: null, documents: [], searchToken: 0 };

function node(tag, className = "", text = "") {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text) element.textContent = text;
  return element;
}

function fact(list, term, value, mono = false) {
  const row = node("div");
  row.append(node("dt", "", term), node("dd", mono ? "mono" : "", value));
  list.append(row);
}

function localDate(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

function setConnection(ok, text) {
  ui["connection-dot"].className = `connection-dot ${ok ? "connected" : "disconnected"}`;
  ui["connection-state"].textContent = text;
}

function selectedFromUrl() {
  return new URLSearchParams(window.location.search).get("corpus");
}

function renderCorpusList() {
  const { corpora, enabled } = state.listing;
  ui["corpus-list"].replaceChildren();
  ui["corpus-list"].removeAttribute("aria-busy");
  if (!corpora.length) {
    ui["corpus-list"].append(node("p", "muted", "No research area has registered a corpus. Declare rag_corpus in a feature manifest to add one."));
    return;
  }
  if (!enabled) {
    ui["corpus-list"].append(node("p", "notice", "Document retrieval is disabled in this runtime, so corpora cannot be read. Start the stack with RAG enabled to inspect them."));
  }
  for (const item of corpora) {
    const key = corpusKey(item);
    const card = node("button", "corpus-card");
    card.type = "button";
    card.setAttribute("role", "listitem");
    card.setAttribute("aria-pressed", String(state.selected === key));
    card.disabled = item.status !== "ready";
    const top = node("span", "corpus-card__top");
    top.append(node("strong", "", activityAreaLabel(item.feature_key)), node("span", `corpus-status corpus-status--${item.status}`, statusLabel(item.status)));
    const facts = item.version
      ? `${item.version.document_count} documents · ${item.version.chunk_count} passages · indexed ${localDate(item.version.ingested_at)}`
      : "No active version";
    card.append(top, node("span", "mono corpus-card__id", item.corpus_id), node("span", "corpus-card__facts", facts));
    card.addEventListener("click", () => selectCorpus(key));
    ui["corpus-list"].append(card);
  }
}

async function selectCorpus(key) {
  const item = state.listing.corpora.find((corpus) => corpusKey(corpus) === key);
  if (!item || item.status !== "ready") return;
  state.selected = key;
  const url = new URL(window.location.href);
  url.searchParams.set("corpus", key);
  window.history.replaceState(null, "", url);
  renderCorpusList();
  ui["corpus-detail"].hidden = false;
  ui["corpus-area"].textContent = activityAreaLabel(item.feature_key);
  ui["corpus-title"].textContent = item.corpus_id;
  ui["corpus-facts"].replaceChildren();
  fact(ui["corpus-facts"], "Version", item.version.corpus_version.slice(0, 12), true);
  fact(ui["corpus-facts"], "Embedding model", item.version.embedding_model.split("@")[0], true);
  fact(ui["corpus-facts"], "Indexed", localDate(item.version.ingested_at));
  fact(ui["corpus-facts"], "Relevance floor", formatScore(state.listing.grounding.min_score));
  ui["search-results"].hidden = true;
  ui["document-list"].replaceChildren(node("li", "muted", "Loading documents…"));
  try {
    const { body } = await requestJson(fetch, `${API}/${encodeURIComponent(item.feature_key)}/${encodeURIComponent(item.corpus_id)}/chunks`, { timeoutMs: 10000 });
    state.documents = groupDocuments(body.chunks);
    renderDocuments();
  } catch (error) {
    ui["document-list"].replaceChildren(node("li", "notice", `Documents could not be loaded: ${error.message}`));
  }
}

function sourceLink(uri, label) {
  const href = safeCitationHref(uri);
  if (!href) return node("span", "muted", label);
  const link = node("a", "", label);
  link.href = href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}

function renderDocuments() {
  const filter = ui["document-filter"].value;
  const visible = state.documents.filter((document) => matchesFilter(document, filter));
  const passages = state.documents.reduce((total, document) => total + document.chunks.length, 0);
  ui["document-summary"].textContent = filter
    ? `${visible.length} of ${state.documents.length} documents match.`
    : `${state.documents.length} documents, ${passages} passages. Open a document to read each passage as it is stored and cited.`;
  ui["document-list"].replaceChildren();
  for (const document of visible) {
    const item = node("li", "document-item");
    const details = node("details");
    const summary = node("summary");
    summary.append(
      node("strong", "", document.title),
      node("span", "muted", `${document.chunks.length} passage${document.chunks.length === 1 ? "" : "s"} · ${document.characters.toLocaleString()} characters${document.sourceDate ? ` · reviewed ${document.sourceDate}` : ""}`),
    );
    const body = node("div", "document-item__body");
    const meta = node("p", "document-item__meta");
    meta.append(node("span", "mono", document.documentId), sourceLink(document.sourceUri, "Source file"));
    body.append(meta);
    for (const chunk of document.chunks) {
      const passage = node("article", "passage");
      passage.append(node("p", "passage__location", chunk.section ? `${chunk.section} · ${chunk.location.split("; ").pop()}` : chunk.location.split("; ").pop()));
      passage.append(node("pre", "passage__text", chunk.excerpt));
      body.append(passage);
    }
    details.append(summary, body);
    item.append(details);
    ui["document-list"].append(item);
  }
}

async function runSearch(event) {
  event.preventDefault();
  const item = state.listing.corpora.find((corpus) => corpusKey(corpus) === state.selected);
  const query = ui["search-query"].value.trim();
  if (!item || !query) return;
  const token = ++state.searchToken;
  ui["search-results"].hidden = false;
  ui["search-results"].replaceChildren(node("p", "muted", "Ranking passages…"));
  try {
    const params = new URLSearchParams({ q: query });
    const { body } = await requestJson(fetch, `${API}/${encodeURIComponent(item.feature_key)}/${encodeURIComponent(item.corpus_id)}/search?${params}`, { timeoutMs: 15000 });
    if (token === state.searchToken) renderSearch(body);
  } catch (error) {
    if (token === state.searchToken) ui["search-results"].replaceChildren(node("p", "notice", `The question could not be ranked: ${error.message}`));
  }
}

function renderSearch(result) {
  const summary = describeSearch(result);
  const header = node("div", `search-summary search-summary--${summary.tone}`);
  header.append(node("strong", "", summary.headline), node("p", "", summary.detail));
  const list = node("ol", "candidate-list");
  for (const candidate of result.candidates) {
    const item = node("li", `candidate${candidate.used_in_grounding ? " candidate--used" : ""}`);
    const top = node("div", "candidate__top");
    const score = node("span", "candidate__score mono", formatScore(candidate.score));
    const meter = node("span", "candidate__meter");
    meter.style.setProperty("--score", String(Math.max(0, Math.min(1, candidate.score))));
    top.append(score, meter, node("strong", "", candidate.title), node("span", "candidate__note", candidateNote(candidate, result.grounding)));
    const excerpt = node("details", "candidate__excerpt");
    excerpt.append(node("summary", "", candidate.location.split("; ").slice(1).join(" · ") || candidate.location), node("pre", "passage__text", candidate.excerpt));
    item.append(top, excerpt);
    list.append(item);
  }
  ui["search-results"].replaceChildren(header, list);
}

async function load() {
  try {
    const { body } = await requestJson(fetch, API, { timeoutMs: 10000 });
    state.listing = body;
    setConnection(true, body.enabled ? "Retrieval connected" : "Retrieval disabled");
    const requested = selectedFromUrl();
    const ready = body.corpora.filter((item) => item.status === "ready");
    const initial = ready.find((item) => corpusKey(item) === requested) || ready[0];
    state.selected = initial ? corpusKey(initial) : null;
    renderCorpusList();
    if (initial) await selectCorpus(state.selected);
  } catch (error) {
    setConnection(false, "Unavailable");
    ui["corpus-list"].removeAttribute("aria-busy");
    ui["corpus-list"].replaceChildren(node("p", "notice", `Registered corpora could not be loaded: ${error.message}`));
  }
}

ui["search-form"].addEventListener("submit", runSearch);
ui["document-filter"].addEventListener("input", renderDocuments);
load();
