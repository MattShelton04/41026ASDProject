/** An in-page assistant using the same lifecycle and renderer as the full page. */
import { append, el } from "../browser/index.js";
import { createAiChat } from "./controller.js";

let sidecarInstance = 0;

export function createAssistantSidecar({ root, trigger, ...options }) {
  if (!root || !trigger) throw new TypeError("A sidecar requires root and trigger");
  const panel = el("aside", "ps-ai-sidecar");
  panel.id = `ps-ai-sidecar-${++sidecarInstance}`;
  panel.setAttribute("aria-label", "Ask about this record");
  panel.hidden = true;
  trigger.setAttribute("aria-controls", panel.id);
  trigger.setAttribute("aria-expanded", "false");
  const toolbar = el("div", "ps-ai-sidecar__toolbar");
  const close = el("button", "ps-ai-chat__context-clear", "Close assistant");
  close.type = "button";
  append(toolbar, el("span", "ps-eyebrow", "On this page"), close);
  const host = el("div", "ps-ai-sidecar__body");
  append(panel, toolbar, host);
  append(root, panel);
  let controller = null;
  const show = () => {
    panel.hidden = false;
    trigger.setAttribute("aria-expanded", "true");
    root.classList.add("ps-ai-context-layout--open");
    controller ||= createAiChat({ ...options, root: host, layout: "embedded" });
    if (host.querySelector(".ps-ai-chat--inspecting")) host.querySelector(".ps-ai-chat__inspection-head button")?.focus();
    else controller.focusComposer();
  };
  const hide = () => {
    panel.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    root.classList.remove("ps-ai-context-layout--open");
    trigger.focus({ preventScroll: true });
  };
  const toggle = () => panel.hidden ? show() : hide();
  const escape = (event) => {
    if (event.key === "Escape" && !panel.hidden) { event.preventDefault(); hide(); }
  };
  trigger.addEventListener("click", toggle);
  close.addEventListener("click", hide);
  panel.addEventListener("keydown", escape);
  return Object.freeze({
    show, hide,
    destroy() {
      controller?.destroy();
      if (!controller) options.client?.destroy?.();
      trigger.removeEventListener("click", toggle);
      close.removeEventListener("click", hide);
      panel.removeEventListener("keydown", escape);
      root.classList.remove("ps-ai-context-layout--open");
      panel.remove();
    },
  });
}
