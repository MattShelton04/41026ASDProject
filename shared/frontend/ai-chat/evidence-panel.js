import { append, el } from "../browser/index.js";

/** One inspection surface per chat, shared by sources and recorded activity. */
export function createEvidencePanel(shell) {
  const panel = el("aside", "ps-ai-chat__inspection");
  panel.setAttribute("aria-label", "Answer sources and activity");
  panel.hidden = true;
  const header = el("header", "ps-ai-chat__inspection-head");
  const title = el("h2", "", "Sources and activity");
  const close = el("button", "ps-ai-chat__context-clear", "Close details");
  close.type = "button";
  const body = el("div", "ps-ai-chat__inspection-body");
  append(header, title, close); append(panel, header, body);
  let key = null;
  let returnFocus = null;
  let returnFocusKey = null;
  const hide = () => {
    panel.hidden = true; key = null;
    shell.classList.remove("ps-ai-chat--inspecting");
    const current = returnFocus?.isConnected ? returnFocus : [...shell.querySelectorAll("[data-transcript-focus-key]")]
      .find((node) => node.dataset.transcriptFocusKey === returnFocusKey);
    (current || shell.querySelector("textarea"))?.focus({ preventScroll: true });
  };
  close.addEventListener("click", hide);
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); hide(); }
  });
  const replace = (content) => {
    const disclosures = new Map([...body.querySelectorAll("details[data-disclosure]")].map((node) => [node.dataset.disclosure, node.open]));
    const focused = body.contains(document.activeElement) ? document.activeElement.closest("details")?.dataset.disclosure : null;
    const scroll = panel.scrollTop;
    body.replaceChildren(content);
    for (const node of body.querySelectorAll("details[data-disclosure]")) {
      if (disclosures.has(node.dataset.disclosure)) node.open = disclosures.get(node.dataset.disclosure);
      if (focused === node.dataset.disclosure) node.querySelector("summary")?.focus({ preventScroll: true });
    }
    panel.scrollTop = scroll;
  };
  return {
    element: panel,
    prepare(turnKey) {
      const host = el("div", "ps-ai-chat__inspection-content");
      return {
        host,
        refresh() { if (key === turnKey) replace(host); },
        open(target = null) {
          returnFocus = document.activeElement;
          returnFocusKey = returnFocus?.dataset.transcriptFocusKey;
          if (key !== turnKey) body.replaceChildren();
          key = turnKey; panel.hidden = false;
          shell.classList.add("ps-ai-chat--inspecting");
          replace(host);
          if (target) { target.open = true; target.querySelector("summary")?.focus(); }
          else close.focus();
          if (panel.getBoundingClientRect().top > window.innerHeight) panel.scrollIntoView({ block: "nearest" });
        },
      };
    },
  };
}
