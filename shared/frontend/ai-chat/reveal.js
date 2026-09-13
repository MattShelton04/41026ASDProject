import { append, el } from "../browser/index.js";

/** Reveal an already validated summary. This is presentation, not provider streaming. */
export function revealAnswerSummary(article, { reducedMotion = globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches } = {}) {
  const paragraph = article.querySelector(".ps-ai-chat__answer-section--summary > p");
  if (!paragraph || reducedMotion) return () => {};
  const complete = paragraph.textContent;
  const words = complete.match(/\S+\s*/g) || [];
  if (words.length < 4) return () => {};
  const accessible = el("span", "ps-ai-chat__sr-only", complete);
  paragraph.style.minHeight = `${paragraph.getBoundingClientRect().height}px`;
  const visible = el("span"); visible.setAttribute("aria-hidden", "true");
  paragraph.replaceChildren(); append(paragraph, accessible, visible);
  const duration = Math.min(1100, Math.max(240, words.length * 14));
  let frame = null;
  let started = null;
  const finish = () => { if (frame !== null) cancelAnimationFrame(frame); paragraph.textContent = complete; paragraph.style.minHeight = ""; };
  const tick = (now) => {
    started ??= now;
    if (!article.isConnected || document.hidden || now - started >= duration) { finish(); return; }
    visible.textContent = words.slice(0, Math.max(1, Math.ceil(words.length * (now - started) / duration))).join("");
    frame = requestAnimationFrame(tick);
  };
  frame = requestAnimationFrame(tick);
  return finish;
}
