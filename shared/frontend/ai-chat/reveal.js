import { append, el } from "../browser/index.js";

/** Reveal validated overview and findings in reading order, never raw provider output. */
export function revealAnswer(article, { reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches } = {}) {
  if (reducedMotion) return () => {};
  let wordCount = 0;
  const paragraphs = [...article.querySelectorAll(".ps-ai-chat__answer-section--summary > p, .ps-ai-chat__findings > li > p:first-child")].map((paragraph) => {
    const complete = paragraph.textContent;
    const words = complete.match(/\S+\s*/g) || [];
    const offset = wordCount;
    wordCount += words.length;
    return { paragraph, complete, words, offset, height: paragraph.getBoundingClientRect().height };
  });
  if (wordCount < 4 || !paragraphs.length) return () => {};
  for (const item of paragraphs) {
    const accessible = el("span", "ps-ai-chat__sr-only", item.complete);
    item.paragraph.style.minHeight = `${item.height}px`;
    item.visible = el("span"); item.visible.setAttribute("aria-hidden", "true");
    item.paragraph.replaceChildren(); append(item.paragraph, accessible, item.visible);
  }
  const duration = Math.min(1800, Math.max(320, wordCount * 12));
  let frame = null;
  let started = null;
  const finish = () => {
    if (frame !== null) cancelAnimationFrame(frame);
    for (const { paragraph, complete } of paragraphs) { paragraph.textContent = complete; paragraph.style.minHeight = ""; }
  };
  const tick = (now) => {
    started ??= now;
    if (!article.isConnected || document.hidden || now - started >= duration) { finish(); return; }
    const revealed = Math.max(1, Math.ceil(wordCount * (now - started) / duration));
    for (const item of paragraphs) {
      item.visible.textContent = item.words.slice(0, Math.max(0, revealed - item.offset)).join("");
    }
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return finish;
}
