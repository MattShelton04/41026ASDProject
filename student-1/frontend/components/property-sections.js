import { append, button, el } from "../core/dom.js";
import { readHistoryState, replaceHistoryState, routeQuery } from "../core/router.js";

/** Local record sections retain loaded evidence and the search-return history state. */
export function propertySections(sections) {
  const root = el("section", "property-sections");
  const navigation = el("div", "property-section-tabs");
  navigation.setAttribute("role", "tablist");
  navigation.setAttribute("aria-label", "Property record sections");
  const requested = routeQuery(location.hash).get("section");
  let selected = sections.some(({ key }) => key === requested) ? requested : sections[0].key;
  const tabs = sections.map(({ key, label, content }) => {
    const tab = button(label, "property-section-tab");
    tab.id = `property-tab-${key}`;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-controls", `property-section-${key}`);
    content.id = `property-section-${key}`;
    content.setAttribute("role", "tabpanel");
    content.setAttribute("aria-labelledby", tab.id);
    content.tabIndex = 0;
    content.classList.add("property-section-content");
    tab.addEventListener("click", () => activate(key));
    append(navigation, tab);
    return tab;
  });
  function activate(key, { focus = false, remember = true } = {}) {
    selected = key;
    sections.forEach((section, index) => {
      const active = section.key === selected;
      section.content.hidden = !active;
      tabs[index].setAttribute("aria-selected", String(active));
      tabs[index].tabIndex = active ? 0 : -1;
      if (active && focus) tabs[index].focus();
    });
    if (remember) {
      const query = routeQuery(location.hash);
      query.set("section", key);
      replaceHistoryState(readHistoryState(), `${location.hash.split("?")[0]}?${query}`);
    }
  }
  navigation.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = sections.findIndex(({ key }) => key === selected);
    const next = event.key === "Home" ? 0 : event.key === "End" ? sections.length - 1
      : (index + (event.key === "ArrowRight" ? 1 : -1) + sections.length) % sections.length;
    activate(sections[next].key, { focus: true });
  });
  append(root, navigation, ...sections.map(({ content }) => content));
  activate(selected, { remember: false });
  return root;
}
