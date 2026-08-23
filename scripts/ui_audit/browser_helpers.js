(() => {
  const root = document.documentElement;
  const viewport = { width: innerWidth, height: innerHeight };
  const interactiveSelector = [
    "a[href]", "button", "summary", "input:not([type=hidden])", "select", "textarea",
    "[contenteditable=true]", "[role=button]", "[role=link]", "[role=tab]",
    "[role=menuitem]", "[role=checkbox]", "[role=radio]", "[role=switch]",
    "[role=combobox]", "[role=textbox]", "[role=spinbutton]",
    "[tabindex]:not([tabindex='-1'])"
  ].join(",");

  function text(element) {
    return (element.innerText || element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 180);
  }
  function rect(element) {
    const value = element.getBoundingClientRect();
    return { x: value.x, y: value.y, width: value.width, height: value.height,
      right: value.right, bottom: value.bottom };
  }
  function descriptor(element) {
    return {
      tag: element.tagName.toLowerCase(), id: element.id || null,
      classes: [...element.classList].slice(0, 5), text: text(element), rect: rect(element),
      core: isCore(element)
    };
  }
  function accessibilityHidden(element) {
    return !!element.closest("[hidden],[inert],[aria-hidden='true']");
  }
  function painted(element) {
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    const visuallyHidden = (box.width <= 2 && box.height <= 2)
      && (style.clip !== "auto" || style.clipPath !== "none" || style.position === "absolute");
    if (accessibilityHidden(element) || !box.width || !box.height || style.display === "none"
        || style.visibility === "hidden" || Number(style.opacity) === 0 || visuallyHidden) return false;
    return box.bottom > 0 && box.right > 0 && box.top < innerHeight && box.left < innerWidth;
  }
  function scrollAncestor(element) {
    let current = element.parentElement;
    while (current && current !== document.body) {
      const style = getComputedStyle(current);
      if (["auto", "scroll"].includes(style.overflowX) && current.scrollWidth > current.clientWidth + 2) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }
  function clips(element) {
    let current = element.parentElement;
    const elementRect = element.getBoundingClientRect();
    while (current && current !== document.body) {
      const style = getComputedStyle(current);
      if (["hidden", "clip"].includes(style.overflowX) || ["hidden", "clip"].includes(style.overflowY)) {
        const ancestorRect = current.getBoundingClientRect();
        if (elementRect.left < ancestorRect.left - 2 || elementRect.right > ancestorRect.right + 2
            || elementRect.top < ancestorRect.top - 2 || elementRect.bottom > ancestorRect.bottom + 2) {
          return current;
        }
      }
      current = current.parentElement;
    }
    return null;
  }
  function isCore(element) {
    return !!element.closest("header,nav,[role=dialog],dialog,[data-audit-core]")
      || element.matches("[type=submit],[role=search] *,input[type=search],.button-primary,.button.primary,.ps-button--primary");
  }
  function accessibleName(element) {
    const labelledBy = element.getAttribute("aria-labelledby");
    if (labelledBy) {
      return labelledBy.split(/\s+/).map(id => document.getElementById(id)?.textContent || "").join(" ").trim();
    }
    const explicitLabels = [...(element.labels || [])].map(label => text(label)).join(" ").trim();
    return (element.getAttribute("aria-label") || explicitLabels || element.getAttribute("alt")
      || element.getAttribute("title") || text(element) || element.value || "").trim();
  }

  const visible = [...document.querySelectorAll("body *")].filter(painted);
  const outside = [];
  const containedScroll = [];
  const clipped = [];
  for (const element of visible) {
    const box = element.getBoundingClientRect();
    if (box.left < -2 || box.right > innerWidth + 2) {
      const scrolling = scrollAncestor(element);
      (scrolling ? containedScroll : outside).push(descriptor(element));
    }
    const contentBearing = element.matches(interactiveSelector + ",dialog,[role=dialog]")
      || (element.childElementCount === 0 && !!text(element));
    if (contentBearing
        && (element.scrollWidth > element.clientWidth + 4 || element.scrollHeight > element.clientHeight + 4)
        && (["hidden", "clip"].includes(getComputedStyle(element).overflowX)
          || ["hidden", "clip"].includes(getComputedStyle(element).overflowY))) {
      clipped.push(descriptor(element));
    } else if (contentBearing && clips(element)) {
      clipped.push(descriptor(element));
    }
  }
  const controls = [...document.querySelectorAll(interactiveSelector)].filter(painted);
  const tinyTargets = controls.filter(element => {
    const box = element.getBoundingClientRect();
    return box.width < 44 || box.height < 44;
  }).map(descriptor);
  const unlabeledControls = controls.filter(element => !accessibleName(element)).map(descriptor);
  const unlabeledFields = [...document.querySelectorAll("input:not([type=hidden]),select,textarea")]
    .filter(painted).filter(element => !element.labels?.length && !element.getAttribute("aria-label")
      && !element.getAttribute("aria-labelledby")).map(descriptor);
  const ids = [...document.querySelectorAll("[id]")].map(element => element.id);
  const duplicateIds = [...new Set(ids.filter((id, index) => ids.indexOf(id) !== index))];
  const dialogs = [...document.querySelectorAll("dialog[open],[role=dialog]")].filter(painted).map(descriptor);
  const focusables = controls.map(element => ({ ...descriptor(element), name: accessibleName(element) }));
  const landmarks = [...document.querySelectorAll("header,nav,main,footer,[role=dialog],dialog")]
    .filter(painted).map(descriptor);
  return {
    viewport,
    document: {
      scrollWidth: root.scrollWidth, scrollHeight: root.scrollHeight,
      horizontalOverflow: root.scrollWidth > innerWidth + 2
    },
    outside: outside.slice(0, 150), containedScroll: containedScroll.slice(0, 150),
    clipped: clipped.slice(0, 150), tinyTargets: tinyTargets.slice(0, 200),
    unlabeledControls: unlabeledControls.slice(0, 100), unlabeledFields: unlabeledFields.slice(0, 100),
    duplicateIds, dialogs, focusables: focusables.slice(0, 300), landmarks
  };
})()
