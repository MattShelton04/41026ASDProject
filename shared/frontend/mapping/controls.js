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
