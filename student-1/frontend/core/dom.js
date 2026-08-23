export { append, el } from "../browser/index.js";
import { el } from "../browser/index.js";

export function link(label, hash, className = "text-button") {
  const node = el("a", className, label);
  node.href = hash;
  return node;
}

export function button(label, className = "button secondary", handler = null) {
  const node = el("button", className, label);
  node.type = "button";
  if (handler) node.addEventListener("click", handler);
  return node;
}
