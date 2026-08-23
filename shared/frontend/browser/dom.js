/** Domain-neutral DOM construction helpers shared by browser microfrontends. */

export function el(tag, className = "", text = undefined) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== "") node.textContent = String(text);
  return node;
}

export function append(target, ...children) {
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) target.append(child);
  }
  return target;
}
