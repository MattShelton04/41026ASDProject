const ICONS = {
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.8V21h14V9.8"/><path d="M9 21v-7h6v7"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.8-3.8"/>',
  building: '<path d="M4 21V4h11v17"/><path d="M15 8h5v13"/><path d="M8 8h3M8 12h3M8 16h3M18 12h.01M18 16h.01"/><path d="M2 21h20"/>',
  map: '<path d="m3 6 6-3 6 3 6-3v15l-6 3-6-3-6 3Z"/><path d="M9 3v15M15 6v15"/>',
  layers: '<path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5"/><path d="m3 17 9 5 9-5"/>',
  database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  activity: '<path d="M3 12h4l2-7 4 14 2-7h6"/>',
  heartbeat: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z"/><path d="M4.7 12h3l1.2-3 2.1 6 1.7-4 1 1h5.5"/>',
  bot: '<rect x="4" y="7" width="16" height="13" rx="3"/><path d="M12 3v4M8 12h.01M16 12h.01M8 16h8"/>',
  sparkles: '<path d="m12 3-1.1 3.1L8 7.2l2.9 1.1L12 11.5l1.1-3.2L16 7.2l-2.9-1.1Z"/><path d="m5.5 12-.8 2.2-2.2.8 2.2.8.8 2.2.8-2.2 2.2-.8-2.2-.8Z"/><path d="m18.5 13-1 2.6-2.5.9 2.5 1 1 2.5.9-2.5 2.6-1-2.6-.9Z"/>',
  robot: '<rect x="3" y="8" width="18" height="12" rx="3"/><path d="M12 4v4M8 13h.01M16 13h.01M8 17h8M9 4h6"/>',
  workflow: '<rect x="3" y="3" width="7" height="6" rx="1"/><rect x="14" y="15" width="7" height="6" rx="1"/><path d="M10 6h4a3 3 0 0 1 3 3v6M14 18h-4a3 3 0 0 1-3-3V9"/>',
  link: '<path d="M10 13a5 5 0 0 0 7.1.1l2-2a5 5 0 0 0-7.1-7.1l-1.1 1.1"/><path d="M14 11a5 5 0 0 0-7.1-.1l-2 2A5 5 0 0 0 12 20l1.1-1.1"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-5"/>',
  check: '<path d="m5 12 4 4L19 6"/>',
  circleCheck: '<circle cx="12" cy="12" r="9"/><path d="m8 12 2.6 2.6L16.5 9"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
  alert: '<path d="M10.3 3.7 2.2 18a2 2 0 0 0 1.7 3h16.2a2 2 0 0 0 1.7-3L13.7 3.7a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7h.01"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.7 9a2.4 2.4 0 1 1 3.8 1.9c-.9.6-1.5 1.1-1.5 2.1M12 17h.01"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/>',
  arrowRight: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  arrowLeft: '<path d="M19 12H5M11 18l-6-6 6-6"/>',
  chevronDown: '<path d="m6 9 6 6 6-6"/>',
  chevronRight: '<path d="m9 18 6-6-6-6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M19 6l-1 15H6L5 6M10 11v6M14 11v6"/>',
  more: '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
  filter: '<path d="M4 5h16M7 12h10M10 19h4"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M5 21h14"/>',
  upload: '<path d="M12 21V9M7 14l5-5 5 5"/><path d="M5 3h14"/>',
  play: '<path d="m8 5 11 7-11 7Z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  refresh: '<path d="M20 6v5h-5"/><path d="M4 18v-5h5"/><path d="M6.1 9a7 7 0 0 1 11.3-2.6L20 9M4 15l2.6 2.6A7 7 0 0 0 17.9 15"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1a1.7 1.7 0 0 0 1.9.3A1.7 1.7 0 0 0 10 3V2.8h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9A1.7 1.7 0 0 0 21 10h.2v4H21a1.7 1.7 0 0 0-1.6 1Z"/>',
  file: '<path d="M6 2h8l4 4v16H6Z"/><path d="M14 2v5h5M9 13h6M9 17h6"/>',
  files: '<path d="M4 4h10v14H4Z"/><path d="M8 8h12v14H8"/>',
  clipboard: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V2h6v2M8 9h8M8 13h8M8 17h5"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/>',
  table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M9 4v16M15 4v16"/>',
  chart: '<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>',
  trend: '<path d="m3 17 6-6 4 4 8-9"/><path d="M15 6h6v6"/>',
  gauge: '<path d="M4.9 19a9 9 0 1 1 14.2 0"/><path d="m12 13 4-4M12 18h.01"/>',
  eye: '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z"/><circle cx="12" cy="12" r="2.5"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  unlock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 7.5-2"/>',
  key: '<circle cx="8" cy="15" r="4"/><path d="m11 12 9-9M16 7l3 3M14 9l3 3"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8"/>',
  bookmark: '<path d="M6 3h12v18l-6-4-6 4Z"/>',
  heart: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8l1.1 1.1L12 21l7.8-7.5 1.1-1.1a5.5 5.5 0 0 0-.1-7.8Z"/>',
  briefcase: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V4h8v3M3 12h18M10 12v2h4v-2"/>',
  house: '<path d="m3 11 9-8 9 8"/><path d="M5 10v11h14V10M9 21v-6h6v6"/>',
  pin: '<path d="M20 10c0 5-8 12-8 12S4 15 4 10a8 8 0 1 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/>',
  school: '<path d="m3 10 9-6 9 6-9 6Z"/><path d="M7 13v5h10v-5M5 20h14"/>',
  tree: '<path d="M12 22v-7"/><path d="M12 3 6 12h4l-3 5h10l-3-5h4Z"/>',
  car: '<path d="m5 11 1.5-5h11L19 11"/><rect x="3" y="10" width="18" height="8" rx="2"/><path d="M6 18v2M18 18v2M7 14h.01M17 14h.01"/>',
  scales: '<path d="M12 3v18M5 6h14M5 6l-3 6h6L5 6ZM19 6l-3 6h6l-3-6Z"/><path d="M8 21h8"/>',
  book: '<path d="M4 4h12a3 3 0 0 1 3 3v13H7a3 3 0 0 0-3 1Z"/><path d="M4 4v17M8 8h7"/>',
  message: '<path d="M21 15a4 4 0 0 1-4 4H8l-5 3V7a4 4 0 0 1 4-4h10a4 4 0 0 1 4 4Z"/><path d="M8 9h8M8 13h5"/>',
  quote: '<path d="M7 17H3v-5a6 6 0 0 1 6-6v3a3 3 0 0 0-3 3h1ZM18 17h-4v-5a6 6 0 0 1 6-6v3a3 3 0 0 0-3 3h1Z"/>',
  cloud: '<path d="M17.5 19H7a5 5 0 1 1 1-9.9A7 7 0 0 1 21 12a4 4 0 0 1-3.5 7Z"/>',
  server: '<rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01M11 7h7M11 17h7"/>',
  cpu: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M9 1v4M15 1v4M9 19v4M15 19v4M1 9h4M1 15h4M19 9h4M19 15h4"/>',
  terminal: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M13 15h4"/>',
  git: '<circle cx="6" cy="5" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="6" cy="19" r="2"/><path d="M6 7v10M8 6c5 0 3 7 8 7h2"/>',
  box: '<path d="m21 8-9 5-9-5 9-5 9 5Z"/><path d="m3 8 9 5v9l-9-5ZM21 8l-9 5v9l9-5Z"/>',
  history: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5M12 7v5l3 2"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
  wand: '<path d="m15 4 5 5L8 21l-5-5Z"/><path d="m6 14 4 4M14 2v3M22 10h-3M19.8 4.2l-2.1 2.1"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V4H4v12h4"/>',
  external: '<path d="M14 3h7v7M10 14 21 3"/><path d="M21 14v7H3V3h7"/>',
  menu: '<path d="M4 7h16M4 12h16M4 17h16"/>',
  bell: '<path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"/>',
  command: '<path d="M9 6V5a3 3 0 1 0-3 3h12a3 3 0 1 0-3-3v14a3 3 0 1 0 3-3H6a3 3 0 1 0 3 3Z"/>',
  print: '<path d="M6 9V3h12v6M6 18h12v3H6Z"/><rect x="3" y="9" width="18" height="9" rx="2"/><path d="M17 13h.01"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  phone: '<path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7 12.8 12.8 0 0 0 .7 2.8 2 2 0 0 1-.4 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4 12.8 12.8 0 0 0 2.8.7 2 2 0 0 1 1.7 2Z"/>',
};

export function icon(name, className = "") {
  const paths = ICONS[name] || ICONS.help;
  return `<svg class="${escapeAttr(className)}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}

export function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

export function escapeAttr(value = "") {
  return escapeHtml(value).replaceAll("`", "&#096;");
}

export function route(path, label, options = {}) {
  const { className = "", iconName = "", attrs = "" } = options;
  return `<a class="${escapeAttr(className)}" href="#/${escapeAttr(path)}" data-route="${escapeAttr(path)}" ${attrs}>${iconName ? icon(iconName) : ""}${escapeHtml(label)}</a>`;
}

export function button(label, options = {}) {
  const {
    kind = "secondary",
    iconName = "",
    route: routeName = "",
    size = "",
    className = "",
    attrs = "",
    type = "button",
  } = options;
  const classes = ["button", kind, size, className].filter(Boolean).join(" ");
  const iconMarkup = iconName ? icon(iconName) : "";
  if (routeName) {
    return `<a class="${escapeAttr(classes)}" href="#/${escapeAttr(routeName)}" data-route="${escapeAttr(routeName)}" ${attrs}>${iconMarkup}${escapeHtml(label)}</a>`;
  }
  return `<button class="${escapeAttr(classes)}" type="${escapeAttr(type)}" ${attrs}>${iconMarkup}${escapeHtml(label)}</button>`;
}

export function iconButton(label, iconName, options = {}) {
  const { kind = "secondary", route: routeName = "", attrs = "" } = options;
  const common = `class="button ${escapeAttr(kind)} icon-only" aria-label="${escapeAttr(label)}" title="${escapeAttr(label)}" ${attrs}`;
  if (routeName) return `<a ${common} href="#/${escapeAttr(routeName)}" data-route="${escapeAttr(routeName)}">${icon(iconName)}</a>`;
  return `<button ${common} type="button">${icon(iconName)}</button>`;
}

export function badge(label, state = "unknown", extra = "") {
  return `<span class="badge ${escapeAttr(state)} ${escapeAttr(extra)}">${escapeHtml(label)}</span>`;
}

export function tag(label) {
  return `<span class="tag">${escapeHtml(label)}</span>`;
}

export function releaseChip(release = "R0", label = "") {
  return `<span class="release-chip"><strong>${escapeHtml(release)}</strong>${label ? `<span>${escapeHtml(label)}</span>` : ""}</span>`;
}

export function screenHeader({ eyebrow = "", title, description = "", actions = "", meta = "" }) {
  return `<header class="screen-header">
    <div class="screen-copy">
      ${eyebrow ? `<p class="eyebrow">${escapeHtml(eyebrow)}</p>` : ""}
      <h1>${escapeHtml(title)}</h1>
      ${description ? `<p class="lede">${escapeHtml(description)}</p>` : ""}
      ${meta ? `<div class="screen-meta">${meta}</div>` : ""}
    </div>
    ${actions ? `<div class="screen-actions">${actions}</div>` : ""}
  </header>`;
}

export function panel({ title = "", description = "", actions = "", body = "", footer = "", className = "" }) {
  return `<section class="panel ${escapeAttr(className)}">
    ${(title || description || actions) ? `<div class="panel-header"><div>${title ? `<h2>${escapeHtml(title)}</h2>` : ""}${description ? `<p>${escapeHtml(description)}</p>` : ""}</div>${actions ? `<div class="cluster">${actions}</div>` : ""}</div>` : ""}
    <div class="panel-body">${body}</div>
    ${footer ? `<div class="panel-footer">${footer}</div>` : ""}
  </section>`;
}

export function card(body, className = "") {
  return `<section class="card ${escapeAttr(className)}">${body}</section>`;
}

export function metricCard({ label, value, foot = "", footState = "", iconName = "chart", spark = "" }) {
  return `<article class="metric-card">
    <div class="metric-top"><span class="metric-label">${escapeHtml(label)}</span><span class="metric-icon">${icon(iconName)}</span></div>
    <div class="metric-value">${escapeHtml(value)}</div>
    <div class="metric-foot ${escapeAttr(footState)}">${foot ? escapeHtml(foot) : "&nbsp;"}${spark}</div>
  </article>`;
}

export function notice({ state = "info", title = "", body = "", iconName = "info", actions = "" }) {
  return `<div class="notice ${escapeAttr(state)}">${icon(iconName)}<div><strong>${escapeHtml(title)}</strong>${body ? `<div>${escapeHtml(body)}</div>` : ""}${actions ? `<div class="cluster" style="margin-top:.55rem">${actions}</div>` : ""}</div></div>`;
}

export function evidenceState(state, title, detail) {
  const iconName = state === "confirmed" ? "check" : state === "partial" ? "alert" : state === "conflicting" ? "x" : "help";
  return `<div class="evidence-state ${escapeAttr(state)}"><span class="state-icon">${icon(iconName)}</span><div><strong>${escapeHtml(title)}</strong><small>${escapeHtml(detail)}</small></div></div>`;
}

export function field({ label, value = "", type = "text", placeholder = "", options = [], className = "", help = "", attrs = "" }) {
  let control = "";
  if (type === "select") {
    control = `<select class="input" ${attrs}>${options.map((opt) => {
      const item = typeof opt === "string" ? { value: opt, label: opt } : opt;
      return `<option value="${escapeAttr(item.value)}" ${item.value === value ? "selected" : ""}>${escapeHtml(item.label)}</option>`;
    }).join("")}</select>`;
  } else if (type === "textarea") {
    control = `<textarea class="input" placeholder="${escapeAttr(placeholder)}" ${attrs}>${escapeHtml(value)}</textarea>`;
  } else {
    control = `<input class="input" type="${escapeAttr(type)}" value="${escapeAttr(value)}" placeholder="${escapeAttr(placeholder)}" ${attrs}>`;
  }
  return `<label class="field ${escapeAttr(className)}"><span>${escapeHtml(label)}</span>${control}${help ? `<small>${escapeHtml(help)}</small>` : ""}</label>`;
}

export function table({ columns, rows, rowClass = "", empty = "No records found", attrs = "" }) {
  if (!rows.length) return `<div class="empty-state"><div><span class="empty-state-icon">${icon("search")}</span><h2>${escapeHtml(empty)}</h2></div></div>`;
  const heads = columns.map((col) => `<th scope="col" ${col.width ? `style="width:${escapeAttr(col.width)}"` : ""}>${escapeHtml(col.label)}</th>`).join("");
  const body = rows.map((row, index) => {
    const cells = columns.map((col) => `<td>${col.render ? col.render(row, index) : escapeHtml(row[col.key] ?? "")}</td>`).join("");
    return `<tr class="${escapeAttr(typeof rowClass === "function" ? rowClass(row, index) : rowClass)}">${cells}</tr>`;
  }).join("");
  return `<div class="table-wrap"><table ${attrs}><thead><tr>${heads}</tr></thead><tbody>${body}</tbody></table></div>`;
}

export function propertyIdentity(property) {
  return `<div class="property-identity"><dl>
    <div><dt>Property reference</dt><dd class="mono">${escapeHtml(property.ref)}</dd></div>
    <div><dt>Identity</dt><dd>${badge(property.match, "confirmed", "no-dot")}</dd></div>
    <div><dt>Sources</dt><dd>${escapeHtml(property.sources)}</dd></div>
    <div><dt>Refreshed</dt><dd>${escapeHtml(property.freshness.replace("Updated ", ""))}</dd></div>
  </dl></div>`;
}

export function propertyHero(property, actions = "") {
  return `<section class="property-hero">
    <div class="property-address">
      <p class="eyebrow">Verified NSW property identity</p>
      <h1>${escapeHtml(property.address)}</h1>
      <p class="subaddress">${escapeHtml(property.type)} · ${escapeHtml(property.coordinates)} · ${escapeHtml(property.freshness)}</p>
      <div class="screen-meta">${badge(property.match, "confirmed")}${tag(property.type)}${tag(`${property.sources} evidence sources`)}</div>
      ${actions ? `<div class="cluster" style="margin-top:.9rem">${actions}</div>` : ""}
    </div>
    ${propertyIdentity(property)}
  </section>`;
}

export function mapFrame({ properties = [], selected = "", compact = false, overlays = [], popup = true, legend = "" }) {
  const markers = properties.map((property, index) => {
    const isSelected = property.ref === selected;
    const style = `left:${property.lat}%;top:${property.top}%`;
    return `<button class="map-marker ${isSelected ? "selected" : index % 2 ? "secondary" : ""}" style="${style}" aria-label="${escapeAttr(property.address)}" title="${escapeAttr(property.address)}">${icon("house")}</button>`;
  }).join("");
  const selectedProperty = properties.find((p) => p.ref === selected) || properties[0];
  const overlayMarkup = overlays.map((o) => `<div class="map-overlay ${escapeAttr(o)}"></div>`).join("");
  return `<div class="map-frame ${compact ? "compact" : ""}">
    <div class="map-surface">
      <div class="map-water"></div><div class="map-park one"></div><div class="map-park two"></div>
      <svg class="map-roads" viewBox="0 0 900 520" preserveAspectRatio="none" aria-hidden="true">
        <path class="major" d="M-20 385 C160 310,220 390,410 295 S710 220,930 105"/>
        <path class="major" d="M125 -20 C215 120,250 230,310 560"/>
        <path class="minor" d="M-10 150 C190 190,330 120,500 190 S720 330,920 275"/>
        <path class="minor" d="M410 -20 C425 145,565 215,535 540"/>
        <path class="minor" d="M640 -20 C590 110,650 220,760 535"/>
        <path class="rail" d="M40 485 C240 390,430 420,870 40"/>
      </svg>
      <span class="map-label city" style="left:42%;top:34%">Parramatta</span>
      <span class="map-label" style="left:20%;top:58%">Westmead</span>
      <span class="map-label" style="left:65%;top:63%">Rosehill</span>
      ${overlayMarkup}${markers}
      ${popup && selectedProperty ? `<div class="map-popup" style="left:${Math.min(selectedProperty.lat + 4, 70)}%;top:${Math.max(selectedProperty.top - 12, 6)}%"><strong>${escapeHtml(selectedProperty.short)}</strong><span>${escapeHtml(selectedProperty.askingPrice)} · ${escapeHtml(selectedProperty.type)}</span></div>` : ""}
      <div class="map-controls"><button class="map-control" type="button" aria-label="Zoom in">${icon("plus")}</button><button class="map-control" type="button" aria-label="Zoom out">−</button><button class="map-control" type="button" aria-label="Map layers">${icon("layers")}</button></div>
      ${legend ? `<div class="map-legend">${legend}</div>` : ""}
    </div>
  </div>`;
}

export function barChart(items, { max = null, labelKey = "label", valueKey = "value", secondaryKey = "", suffix = "" } = {}) {
  const peak = max || Math.max(...items.map((item) => Number(item[valueKey]) || 0), 1);
  return `<div class="chart" role="img" aria-label="Bar chart"><div class="bar-chart">${items.map((item) => {
    const val = Number(item[valueKey]) || 0;
    const pct = Math.max(3, Math.round((val / peak) * 100));
    const secondary = secondaryKey ? `<span class="bar-secondary" style="width:${Math.max(2, Math.round(((Number(item[secondaryKey]) || 0) / peak) * 100))}%"></span>` : "";
    return `<div class="bar-row"><span class="bar-label">${escapeHtml(item[labelKey])}</span><span class="bar-track"><span class="bar-fill" style="width:${pct}%"></span>${secondary}</span><strong>${escapeHtml(`${val}${suffix}`)}</strong></div>`;
  }).join("")}</div></div>`;
}

export function lineChart(series, { width = 640, height = 190, labels = [], ariaLabel = "Line chart" } = {}) {
  const allValues = series.flatMap((s) => s.values);
  const min = Math.min(...allValues);
  const max = Math.max(...allValues);
  const range = Math.max(max - min, 1);
  const padding = 18;
  const usableW = width - padding * 2;
  const usableH = height - padding * 2;
  const polylines = series.map((s, seriesIndex) => {
    const points = s.values.map((v, i) => {
      const x = padding + (i / Math.max(s.values.length - 1, 1)) * usableW;
      const y = padding + usableH - ((v - min) / range) * usableH;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(" ");
    return `<polyline class="chart-series series-${seriesIndex + 1}" points="${points}"/>`;
  }).join("");
  const dots = series.map((s, seriesIndex) => s.values.map((v, i) => {
    const x = padding + (i / Math.max(s.values.length - 1, 1)) * usableW;
    const y = padding + usableH - ((v - min) / range) * usableH;
    return `<circle class="chart-dot series-${seriesIndex + 1}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3"/>`;
  }).join("")).join("");
  const gridLines = [0, .25, .5, .75, 1].map((ratio) => `<line x1="${padding}" y1="${padding + usableH * ratio}" x2="${width - padding}" y2="${padding + usableH * ratio}"/>`).join("");
  const axisLabels = labels.map((label, i) => `<span style="left:${(i / Math.max(labels.length - 1, 1)) * 100}%">${escapeHtml(label)}</span>`).join("");
  return `<div class="chart" role="img" aria-label="${escapeAttr(ariaLabel)}"><svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none"><g class="chart-grid">${gridLines}</g>${polylines}${dots}</svg>${labels.length ? `<div class="chart-axis-labels">${axisLabels}</div>` : ""}</div>`;
}

export function sparkline(values, width = 94, height = 24) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(max - min, 1);
  const points = values.map((v, i) => `${(i / Math.max(values.length - 1, 1) * width).toFixed(1)},${(height - ((v - min) / range) * height).toFixed(1)}`).join(" ");
  return `<svg class="sparkline" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true"><polyline points="${points}"/></svg>`;
}

export function timeline(items) {
  return `<ol class="timeline">${items.map((item) => `<li class="timeline-item"><span class="timeline-marker ${escapeAttr(item.state || "")}">${icon(item.icon || (item.state === "success" ? "check" : item.state === "failed" ? "x" : "clock"))}</span><div class="timeline-copy"><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.detail || "")}</p></div><time class="timeline-time">${escapeHtml(item.time || "")}</time></li>`).join("")}</ol>`;
}

export function agentLoop(active = "observe", detail = {}) {
  const phases = [
    { id: "plan", label: "Plan", icon: "clipboard", copy: detail.plan || "Clarify objective and select bounded tools." },
    { id: "act", label: "Act", icon: "play", copy: detail.act || "Invoke approved data and reasoning operations." },
    { id: "observe", label: "Observe", icon: "eye", copy: detail.observe || "Inspect results, failures, and evidence." },
    { id: "adapt", label: "Adapt", icon: "refresh", copy: detail.adapt || "Revise the plan or request human review." },
  ];
  const activeIndex = phases.findIndex((p) => p.id === active);
  return `<div class="agent-loop">${phases.map((phase, index) => `<div class="agent-phase ${index < activeIndex ? "complete" : index === activeIndex ? "active" : ""}"><span class="agent-phase-icon">${icon(phase.icon)}</span><h3>${phase.label}</h3><p>${escapeHtml(phase.copy)}</p></div>`).join("")}</div>`;
}

export function toolCall({ name, detail, state = "success", meta = "" }) {
  return `<div class="tool-call"><span class="tool-icon">${icon(state === "failed" ? "x" : "terminal")}</span><div><strong>${escapeHtml(name)}</strong><span>${escapeHtml(detail)}</span></div><div>${badge(meta || state, state, "no-dot")}</div></div>`;
}

export function lineage(nodes) {
  return `<div class="lineage">${nodes.map((node) => `<div class="lineage-node">${icon(node.icon || "box")}<strong>${escapeHtml(node.title)}</strong><span>${escapeHtml(node.detail || "")}</span></div>`).join("")}</div>`;
}

export function featureCard({ number, title, description, route: routeName, iconName, status = "Planned", release = "R0", owner = "Student" }) {
  const statusState = status.toLowerCase().includes("live") || status.toLowerCase().includes("implemented") ? "live" : status.toLowerCase().includes("prototype") ? "review" : "planned";
  return `<a class="feature-card" href="#/${escapeAttr(routeName)}" data-route="${escapeAttr(routeName)}">
    <div class="feature-card-head"><span class="feature-number">${icon(iconName)}</span>${badge(status, statusState, "no-dot")}</div>
    <h2><span class="subtle">${escapeHtml(`0${number}`)}</span> ${escapeHtml(title)}</h2>
    <p>${escapeHtml(description)}</p>
    <div class="feature-card-foot"><span>${escapeHtml(`${owner} · ${release}`)}</span>${icon("arrowRight")}</div>
  </a>`;
}

export function quickAction({ title, description, route: routeName, iconName }) {
  return `<a class="quick-action" href="#/${escapeAttr(routeName)}" data-route="${escapeAttr(routeName)}"><span class="quick-action-icon">${icon(iconName)}</span><span><strong>${escapeHtml(title)}</strong><span>${escapeHtml(description)}</span></span>${icon("chevronRight")}</a>`;
}

export function coverageState(value) {
  const labels = { confirmed: "Confirmed", partial: "Partial", conflicting: "Conflicting", unknown: "Unknown" };
  return badge(labels[value] || value, value, "no-dot");
}

export function emptyState({ title, body, iconName = "search", action = "" }) {
  return `<div class="empty-state"><div><span class="empty-state-icon">${icon(iconName)}</span><h2>${escapeHtml(title)}</h2><p>${escapeHtml(body)}</p>${action ? `<div class="cluster" style="justify-content:center">${action}</div>` : ""}</div></div>`;
}
