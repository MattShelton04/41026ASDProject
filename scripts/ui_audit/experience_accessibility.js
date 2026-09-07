/* Supplemental computed-style checks, not a screen-reader or WCAG certification. */
(() => {
  const context = document.createElement("canvas").getContext("2d", {willReadFrequently: true});
  const colors = new Map();
  function rgba(color) {
    if (!colors.has(color)) {
      context.clearRect(0, 0, 1, 1);
      context.fillStyle = color;
      context.fillRect(0, 0, 1, 1);
      colors.set(color, [...context.getImageData(0, 0, 1, 1).data]);
    }
    return colors.get(color);
  }
  function composite(fg, bg) {
    const alpha = fg[3] / 255;
    return fg.slice(0, 3).map((value, index) => value * alpha + bg[index] * (1 - alpha)).concat(255);
  }
  function luminance(color) {
    const linear = color.slice(0, 3).map(value => {
      const channel = value / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722;
  }
  function background(element) {
    const ancestors = [];
    for (let node = element; node; node = node.parentElement) ancestors.unshift(node);
    let color = [255, 255, 255, 255];
    for (const ancestor of ancestors) {
      const style = getComputedStyle(ancestor);
      if (style.backgroundImage !== "none" || Number(style.opacity) < 1) return null;
      color = composite(rgba(style.backgroundColor), color);
    }
    return color;
  }
  const visible = element => {
    const rect = element.getBoundingClientRect();
    return rect.width > 1 && rect.height > 1 && getComputedStyle(element).visibility !== "hidden"
      && !element.closest("[hidden],[inert],[aria-hidden=true],svg,canvas,option,button:disabled");
  };
  const failures = [];
  const checked = [];
  for (const element of document.querySelectorAll("body *")) {
    if (!visible(element)) continue;
    const text = [...element.childNodes].filter(node => node.nodeType === Node.TEXT_NODE)
      .map(node => node.textContent.trim()).join(" ").trim();
    if (!text) continue;
    const bg = background(element);
    if (!bg) continue;
    const style = getComputedStyle(element);
    const fg = composite(rgba(style.color), bg);
    const a = luminance(fg), b = luminance(bg);
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    const large = parseFloat(style.fontSize) >= 24
      || (parseFloat(style.fontSize) >= 18.66 && Number(style.fontWeight) >= 700);
    const record = {text: text.slice(0, 100), tag: element.tagName, id: element.id,
      color: style.color, background: bg.slice(0, 3), size: style.fontSize,
      ratio: Math.round(ratio * 100) / 100, required: large ? 3 : 4.5};
    checked.push(record);
    if (ratio + 0.01 < record.required) failures.push(record);
  }
  const headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].filter(visible)
    .map(element => ({level: Number(element.tagName[1]), text: element.textContent.trim()}));
  const skip = [...document.querySelectorAll("a")].find(element => /skip to/i.test(element.textContent));
  const animated = [...document.querySelectorAll("body *")].filter(visible).filter(element => {
    const style = getComputedStyle(element);
    return style.animationName !== "none" && style.animationDuration.split(",")
      .some(value => parseFloat(value) > 0.001);
  }).map(element => ({tag: element.tagName, id: element.id, class: element.className}));
  return {contrast: {checked: checked.length, failures}, headings,
    mainCount: document.querySelectorAll("main").length,
    skipTargetExists: !!(skip && document.querySelector(skip.getAttribute("href"))),
    reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches, animated};
})()
