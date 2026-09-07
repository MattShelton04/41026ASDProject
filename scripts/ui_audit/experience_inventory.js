/* Runtime route/control inventory. Contains no fixture data or product behaviour. */
() => {
  const visible = element => element.getClientRects().length
    && getComputedStyle(element).visibility !== "hidden" && !element.closest("[hidden],[inert]");
  const describe = element => {
    const labelled = element.getAttribute("aria-labelledby");
    const name = labelled?.split(/\s+/).map(id => document.getElementById(id)?.textContent || "").join(" ")
      || element.getAttribute("aria-label")
      || [...(element.labels || [])].map(label => label.textContent).join(" ")
      || element.innerText || element.getAttribute("title") || "";
    return {tag: element.tagName, id: element.id, text: name.trim().slice(0, 100)};
  };
  return {
    headings: [...document.querySelectorAll("h1,h2,h3")].filter(visible).map(describe),
    overflow: document.documentElement.scrollWidth > innerWidth + 1,
    overflowing: [...document.querySelectorAll("main *")].filter(element => visible(element)
      && element.getBoundingClientRect().right > innerWidth + 1
      && !element.closest(".ps-table-region,.table-wrap,.table-scroll,.maplibregl-map"))
      .slice(0, 15).map(describe),
    controls: [...document.querySelectorAll("button,input,select,textarea,a,summary")]
      .filter(visible).map(element => ({...describe(element), disabled: element.disabled || false,
        width: Math.round(element.getBoundingClientRect().width),
        height: Math.round(element.getBoundingClientRect().height)})),
    mainCount: document.querySelectorAll("main").length,
    reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches
  };
}
