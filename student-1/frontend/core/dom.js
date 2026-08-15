export function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = String(text);
  return node;
}

export function append(parent, ...children) {
  for (const child of children.flat()) if (child !== null && child !== undefined) parent.append(child);
  return parent;
}

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
