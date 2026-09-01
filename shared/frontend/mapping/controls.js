let helpIdSequence = 0;

export function mountLayerControls(controller, container, { title = "Map layers" } = {}) {
  if (!controller || !container) throw new TypeError("Layer controls need a map controller and container.");
  const documentRef = container.ownerDocument;
  const fieldset = documentRef.createElement("fieldset");
  fieldset.className = "ps-map-layers";
  const legend = documentRef.createElement("legend");
  legend.textContent = title;
  fieldset.append(legend);
  for (const id of controller.layerIds) {
    const state = controller.layerState(id);
    const label = documentRef.createElement("label");
    const input = documentRef.createElement("input");
    input.type = "checkbox";
    input.checked = state.visible;
    input.addEventListener("change", () => controller.setLayerVisible(id, input.checked));
    const text = documentRef.createElement("span");
    text.textContent = `${state.label} (${state.featureCount.toLocaleString()})`;
    label.append(input, text);
    fieldset.append(label);
  }
  container.replaceChildren(fieldset);
  return Object.freeze({
    destroy() { fieldset.remove(); },
  });
}

/**
 * Add compact, text-only map guidance without permanently covering the data viewport.
 * Hover and focus reveal the guidance transiently; click/tap pins it open until toggled.
 */
export function mountMapHelp(container, {
  label = "Map information",
  text = "Drag to pan. Scroll or use the controls to zoom.",
} = {}) {
  if (!container?.ownerDocument) throw new TypeError("Map help needs a container with a document.");
  const documentRef = container.ownerDocument;
  const root = documentRef.createElement("div");
  root.className = "ps-map-help";
  const button = documentRef.createElement("button");
  button.className = "ps-map-help__button";
  button.type = "button";
  button.setAttribute("aria-label", label);
  button.setAttribute("aria-expanded", "false");
  const panel = documentRef.createElement("div");
  panel.className = "ps-map-help__panel";
  panel.id = `ps-map-help-${++helpIdSequence}`;
  panel.setAttribute("role", "tooltip");
  panel.textContent = String(text);
  panel.hidden = true;
  button.setAttribute("aria-controls", panel.id);
  button.setAttribute("aria-describedby", panel.id);
  const icon = documentRef.createElement("span");
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "i";
  button.append(icon);
  root.append(button, panel);
  container.append(root);

  let pinned = false;
  let hovering = false;
  let focused = false;
  let dismissed = false;
  const render = () => {
    const visible = pinned || (!dismissed && (hovering || focused));
    panel.hidden = !visible;
    root.dataset.open = String(visible);
    button.setAttribute("aria-expanded", String(visible));
  };
  const enter = () => {
    hovering = true;
    dismissed = false;
    render();
  };
  const leave = () => {
    hovering = false;
    if (!focused) dismissed = false;
    render();
  };
  const focusIn = () => {
    focused = true;
    dismissed = false;
    render();
  };
  const focusOut = (event) => {
    if (root.contains(event.relatedTarget)) return;
    focused = false;
    if (!hovering) dismissed = false;
    render();
  };
  const toggle = () => {
    if (pinned) {
      pinned = false;
      dismissed = true;
    } else {
      pinned = true;
      dismissed = false;
    }
    render();
  };
  const keyDown = (event) => {
    if (event.key !== "Escape") return;
    pinned = false;
    dismissed = true;
    render();
  };
  root.addEventListener("mouseenter", enter);
  root.addEventListener("mouseleave", leave);
  root.addEventListener("focusin", focusIn);
  root.addEventListener("focusout", focusOut);
  root.addEventListener("keydown", keyDown);
  button.addEventListener("click", toggle);

  return Object.freeze({
    element: root,
    button,
    panel,
    destroy() {
      root.removeEventListener("mouseenter", enter);
      root.removeEventListener("mouseleave", leave);
      root.removeEventListener("focusin", focusIn);
      root.removeEventListener("focusout", focusOut);
      root.removeEventListener("keydown", keyDown);
      button.removeEventListener("click", toggle);
      root.remove();
    },
  });
}
