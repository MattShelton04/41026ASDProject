// PropertyScope visual review viewer. Every pixel metric and heatmap is precomputed by the trusted
// reporter; this script only arranges images, so it works offline and never reads canvas pixels.
(() => {
  "use strict";
  const report = JSON.parse(document.getElementById("report-data").textContent);
  const $ = (id) => document.getElementById(id);
  const IMAGE = /^[a-f0-9]{64}\.png$/;
  const root = ["img/", "../../img/"].includes(report.metadata.imageRoot) ? report.metadata.imageRoot : "img/";
  const url = (name) => (typeof name === "string" && IMAGE.test(name) ? root + name : "");
  const WIDTH = 1440;
  const GAP = 48;
  const LABEL_SPACE = 30;
  const MODES = ["side", "toggle", "wipe", "overlay", "difference"];
  const THRESHOLDS = ["0", "8", "16", "32"];
  const ORDER = ["changed", "incomplete", "base unavailable", "subtle", "unchanged"];
  const LABELS = {
    changed: "Changed",
    incomplete: "Incomplete",
    "base unavailable": "No baseline",
    subtle: "Subtle",
    unchanged: "Identical",
  };
  const statusClass = (status) => String(status).replace(/ /g, "-");
  const number = (value) => Number(value || 0).toLocaleString("en-AU");
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };
  const pill = (status) => el("span", `pill ${statusClass(status)}`, LABELS[status] || status);

  const rows = report.rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => ORDER.indexOf(a.row.change) - ORDER.indexOf(b.row.change) || a.index - b.index)
    .map((item) => item.row);
  const byId = new Map(rows.map((row) => [row.id, row]));
  const sections = report.sections.filter((section) => rows.some((row) => row.section === section.id));
  const inSection = (id) => rows.filter((row) => row.section === id);
  const attention = (row) => !["unchanged", "subtle"].includes(row.change);
  const defaultSection = () =>
    (sections.find((section) => inSection(section.id).some((row) => row.change === "changed")) ||
      sections.find((section) => inSection(section.id).some(attention)) ||
      sections[0] || { id: "" }).id;

  const params = new URLSearchParams(location.hash.slice(1));
  const state = {
    section: sections.some((item) => item.id === params.get("section")) ? params.get("section") : defaultSection(),
    row: null,
    mode: MODES.includes(params.get("mode")) ? params.get("mode") : "side",
    zoom: params.get("zoom") === "100" ? 1 : "fit",
    threshold: THRESHOLDS.includes(params.get("threshold")) ? params.get("threshold") : "0",
    side: "head",
    wipe: 50,
    opacity: 50,
    region: -1,
    scale: 1,
  };
  state.row = byId.get(params.get("view")) || inSection(state.section)[0] || rows[0] || null;
  if (state.row) state.section = state.row.section;

  const viewport = $("viewport");
  const scaled = $("scaled-stage");
  const stage = $("image-stage");
  const buttons = new Map();

  function saveUrl(push) {
    if (!state.row) return;
    const query = new URLSearchParams({ section: state.section, view: state.row.id, mode: state.mode });
    if (state.zoom === 1) query.set("zoom", "100");
    if (state.threshold !== "0") query.set("threshold", state.threshold);
    history[push ? "pushState" : "replaceState"](null, "", `#${query}`);
  }

  // Sidebar: sections, filters and the grouped view list.
  function renderSections() {
    const container = $("sections");
    container.replaceChildren();
    for (const section of sections) {
      const members = inSection(section.id);
      const button = el("button", "section-button");
      button.type = "button";
      button.setAttribute("aria-pressed", String(section.id === state.section));
      const counts = el("span", "section-counts");
      const changed = members.filter((row) => row.change === "changed").length;
      const limited = members.filter((row) => ["incomplete", "base unavailable"].includes(row.change)).length;
      if (changed) counts.append(el("span", "c-changed", String(changed)));
      if (limited) counts.append(el("span", "c-limited", String(limited)));
      counts.append(el("span", "c-total", String(members.length)));
      button.append(el("span", "", section.label), counts);
      button.setAttribute(
        "aria-label",
        `${section.label}: ${changed} changed, ${limited} with limitations, ${members.length} views`,
      );
      button.addEventListener("click", () => {
        state.section = section.id;
        $("search").value = "";
        select(inSection(section.id)[0], true);
      });
      container.append(button);
    }
  }

  function renderList() {
    const list = $("view-list");
    list.replaceChildren();
    buttons.clear();
    const query = $("search").value.trim().toLowerCase();
    const onlyChanges = $("only-changes").checked;
    const visible = inSection(state.section).filter(
      (row) =>
        `${row.id} ${row.path} ${row.state}`.toLowerCase().includes(query) && (!onlyChanges || attention(row)),
    );
    for (const status of ORDER) {
      const group = visible.filter((row) => row.change === status);
      if (!group.length) continue;
      list.append(el("h3", "view-group", `${LABELS[status]} · ${group.length}`));
      for (const row of group) {
        const button = el("button", "view-link");
        button.type = "button";
        button.setAttribute("aria-current", String(row === state.row));
        const thumb = el("img", "view-thumb");
        thumb.alt = "";
        thumb.loading = "lazy";
        const preview = url(row.review && row.review.preview) || url(row.headImage) || url(row.baseImage);
        if (preview) thumb.src = preview;
        const label = el("span", "");
        label.append(el("span", "view-name", row.id), el("span", "view-sub", row.state), pill(row.change));
        button.append(thumb, label);
        button.addEventListener("click", () => select(row, true));
        buttons.set(row.id, button);
        list.append(button);
      }
    }
    if (!visible.length) list.append(el("p", "empty-filter", "No views match these filters."));
    const total = inSection(state.section).length;
    $("visible-count").textContent = `${visible.length} of ${total} views in this section`;
  }

  // Stage: arrange the precomputed images for the selected mode.
  const available = (row, side) => row && row[side] && row[side].status === "captured" && url(row[`${side}Image`]);
  function image(side) {
    const img = el("img");
    img.src = available(state.row, side);
    img.alt = `${side === "base" ? "Before" : "After"}: ${state.row.id}`;
    img.width = WIDTH;
    img.height = state.row[`${side}Height`] || 0;
    img.draggable = false;
    return img;
  }
  function layer(child, className) {
    const node = el("div", `layer ${className || ""}`);
    node.append(child);
    return node;
  }
  function missing(text, height) {
    const node = el("div", "missing", text);
    node.style.height = `${Math.max(400, Math.min(height || 600, 1000))}px`;
    return node;
  }

  function effectiveMode() {
    const row = state.row;
    return available(row, "base") && available(row, "head") ? state.mode : "single";
  }

  function renderStage() {
    const row = state.row;
    stage.replaceChildren();
    const mode = effectiveMode();
    const height = Math.max(row.baseHeight || 0, row.headHeight || 0, 400);
    let width = WIDTH;
    let top = 0;
    if (mode === "single") {
      const side = available(row, "head") ? "head" : available(row, "base") ? "base" : null;
      const panel = el("div", "panel shadowed");
      panel.append(side ? image(side) : missing("No usable screenshot was captured for this view.", height));
      stage.append(panel);
    } else if (mode === "side") {
      width = WIDTH * 2 + GAP;
      top = LABEL_SPACE;
      for (const [side, left] of [["base", 0], ["head", WIDTH + GAP]]) {
        const panel = el("div", "panel shadowed");
        panel.style.left = `${left}px`;
        panel.style.top = `${top}px`;
        panel.append(el("span", "panel-label", side === "base" ? "Before" : "After"), image(side));
        stage.append(panel);
      }
    } else if (mode === "toggle") {
      stage.append(layer(image(state.side), "shadowed"));
    } else if (mode === "wipe") {
      stage.append(layer(image("head"), "shadowed"));
      const before = layer(image("base"));
      before.style.clipPath = `inset(0 ${100 - state.wipe}% 0 0)`;
      stage.append(before);
      const divider = el("div", "wipe-divider");
      divider.style.left = `${(WIDTH * state.wipe) / 100}px`;
      divider.tabIndex = 0;
      divider.setAttribute("role", "slider");
      divider.setAttribute("aria-label", "Before and after split");
      divider.setAttribute("aria-valuemin", "0");
      divider.setAttribute("aria-valuemax", "100");
      divider.setAttribute("aria-valuenow", String(state.wipe));
      divider.append(el("span", "", "⇆"));
      divider.addEventListener("keydown", wipeKeys);
      divider.addEventListener("pointerdown", wipeDrag);
      stage.append(divider);
    } else if (mode === "overlay") {
      stage.append(layer(image("base"), "shadowed"));
      const after = layer(image("head"));
      after.style.opacity = String(state.opacity / 100);
      stage.append(after);
    } else {
      stage.append(layer(image("head"), "shadowed dimmed"));
      const analysis = (row.analyses || {})[state.threshold];
      if (analysis && analysis.heat) {
        const heat = el("img");
        heat.src = url(analysis.heat);
        heat.alt = "";
        heat.width = WIDTH;
        heat.height = height;
        stage.append(layer(heat));
      }
      for (const [index, region] of ((analysis && analysis.regions) || []).entries()) {
        const box = el("div", `region-box${index === state.region ? " active" : ""}`);
        Object.assign(box.style, {
          left: `${region.x - 3}px`,
          top: `${region.y - 3}px`,
          width: `${region.width + 6}px`,
          height: `${region.height + 6}px`,
        });
        stage.append(box);
      }
    }
    stage.dataset.width = String(width);
    stage.dataset.height = String(height + top);
    stage.dataset.top = String(top);
    resize();
  }

  function fitScale() {
    const width = Number(stage.dataset.width || WIDTH);
    return Math.max(0.1, Math.min(1, (viewport.clientWidth - 34) / width));
  }
  function resize() {
    const width = Number(stage.dataset.width || WIDTH);
    const height = Number(stage.dataset.height || 600);
    state.scale = state.zoom === "fit" ? fitScale() : state.zoom;
    stage.style.width = `${width}px`;
    stage.style.height = `${height}px`;
    stage.style.transform = `scale(${state.scale})`;
    scaled.style.width = `${width * state.scale}px`;
    scaled.style.height = `${height * state.scale}px`;
    viewport.classList.toggle("can-pan", width * state.scale > viewport.clientWidth - 34);
    $("zoom-value").textContent = `${Math.round(state.scale * 100)}%`;
    $("zoom-fit").setAttribute("aria-pressed", String(state.zoom === "fit"));
    $("zoom-actual").setAttribute("aria-pressed", String(state.zoom === 1));
  }
  function setZoom(value) {
    const centreX = (viewport.scrollLeft + viewport.clientWidth / 2) / state.scale;
    const centreY = (viewport.scrollTop + viewport.clientHeight / 2) / state.scale;
    state.zoom = value;
    resize();
    viewport.scrollLeft = centreX * state.scale - viewport.clientWidth / 2;
    viewport.scrollTop = centreY * state.scale - viewport.clientHeight / 2;
    saveUrl(false);
  }

  function wipeKeys(event) {
    const step = event.shiftKey ? 10 : 1;
    const next = { ArrowLeft: state.wipe - step, ArrowRight: state.wipe + step, Home: 0, End: 100 }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setWipe(next, true);
  }
  function wipeDrag(event) {
    event.preventDefault();
    event.stopPropagation();
    const move = (moveEvent) => {
      const box = stage.getBoundingClientRect();
      setWipe(((moveEvent.clientX - box.left) / (box.width || 1)) * 100, false);
    };
    const stop = () => {
      removeEventListener("pointermove", move);
      removeEventListener("pointerup", stop);
    };
    addEventListener("pointermove", move);
    addEventListener("pointerup", stop);
  }
  function setWipe(value, focus) {
    state.wipe = Math.round(Math.max(0, Math.min(100, value)));
    $("wipe-range").value = String(state.wipe);
    $("wipe-value").textContent = `${state.wipe}%`;
    renderStage();
    if (focus) stage.querySelector(".wipe-divider")?.focus();
  }

  // Details under the stage: metrics, regions, shared-change notes and capture limitations.
  function renderDetails() {
    const row = state.row;
    $("view-title").textContent = row.id;
    const description = $("view-description");
    description.replaceChildren(el("code", "", row.path), ` · ${row.state} · ${row.provider === "stack" ? "offline stack" : `${row.scenario || "populated"} fixture`}`);
    $("view-status").replaceChildren(pill(row.change));
    const analysis = (row.analyses || {})[state.threshold];
    const metrics = $("metrics");
    metrics.replaceChildren();
    if (analysis) {
      const summary = el("span");
      if (analysis.changed) {
        summary.append(el("strong", "", `${number(analysis.changed)} px changed`), ` (${analysis.percent}%) in ${analysis.regionCount} ${analysis.regionCount === 1 ? "region" : "regions"}`);
      } else {
        summary.textContent = state.threshold === "0" ? "Decoded pixels are identical." : `No differences above ${state.threshold}/255.`;
      }
      metrics.append(summary);
      if (analysis.bounds) {
        const b = analysis.bounds;
        metrics.append(el("span", "", `Bounds ${b.x}, ${b.y} · ${b.width} × ${b.height}`));
      }
    } else if (row.change === "base unavailable") {
      metrics.append(el("span", "", "There is no baseline for this view: it is new, or the base revision could not render it."));
    }
    if (row.baseHeight && row.headHeight && row.baseHeight !== row.headHeight) {
      metrics.append(el("span", "", `Page height ${number(row.baseHeight)} → ${number(row.headHeight)} px`));
    }
    const regions = $("regions");
    regions.replaceChildren();
    for (const [index, region] of ((analysis && analysis.regions) || []).entries()) {
      const button = el("button", "", `${region.width}×${region.height} at ${region.x},${region.y}`);
      button.type = "button";
      button.setAttribute("aria-pressed", String(index === state.region));
      button.addEventListener("click", () => focusRegion(index));
      regions.append(button);
    }
    const shared = $("shared");
    shared.replaceChildren();
    const review = row.review || {};
    const related = review.sameAs ? [review.sameAs] : review.sharedWith || [];
    shared.hidden = !related.length;
    if (related.length) {
      shared.append(el("h3", "", review.sameAs ? "Same change as" : "Same changed areas in"));
      const list = el("ul");
      for (const id of related) {
        const item = el("li");
        const link = el("a", "", id);
        link.href = `#view=${encodeURIComponent(id)}&mode=difference`;
        link.addEventListener("click", (event) => {
          event.preventDefault();
          select(byId.get(id), true);
        });
        item.append(link);
        list.append(item);
      }
      shared.append(list);
    }
    const problems = ["base", "head"].flatMap((side) =>
      ((row[side] && row[side].errors) || []).map((message) => `${side === "base" ? "Before" : "After"}: ${message}`),
    );
    const notes = ["base", "head"].flatMap((side) =>
      ((row[side] && row[side].notes) || []).map((message) => `${side === "base" ? "Before" : "After"}: ${message}`),
    );
    for (const [id, items, title] of [["problems", problems, "Capture problems"], ["notes", notes, "Capture notes"]]) {
      const box = $(id);
      box.replaceChildren(el("h3", "", title));
      const list = el("ul");
      for (const message of [...new Set(items)]) list.append(el("li", "", message));
      box.append(list);
      box.hidden = !items.length;
    }
  }

  function focusRegion(index) {
    const analysis = (state.row.analyses || {})[state.threshold];
    const region = analysis && analysis.regions[index];
    if (!region) return;
    state.region = index;
    if (state.mode !== "difference" && effectiveMode() !== "single") state.mode = "difference";
    if (state.zoom === "fit") state.zoom = 1;
    renderAll(false);
    const top = Number(stage.dataset.top || 0);
    viewport.scrollLeft = (region.x + region.width / 2) * state.scale - viewport.clientWidth / 2;
    viewport.scrollTop = (region.y + top + region.height / 2) * state.scale - viewport.clientHeight / 2;
  }

  function renderControls() {
    const both = effectiveMode() !== "single";
    for (const button of document.querySelectorAll("[data-mode]")) {
      button.setAttribute("aria-pressed", String(both && button.dataset.mode === state.mode));
      button.disabled = !both;
    }
    const mode = effectiveMode();
    $("toggle-control").hidden = mode !== "toggle";
    $("wipe-control").hidden = mode !== "wipe";
    $("opacity-control").hidden = mode !== "overlay";
    $("threshold-control").hidden = !state.row.analyses;
    for (const button of document.querySelectorAll("[data-side]"))
      button.setAttribute("aria-pressed", String(button.dataset.side === state.side));
    $("threshold").value = state.threshold;
    $("mode-hint").textContent = {
      single: "Only one side has a usable screenshot.",
      side: "Before on the left, after on the right.",
      toggle: "Press T to flip between before and after.",
      wipe: "Drag the divider, or focus it and use the arrow keys (Shift for 10%).",
      overlay: "Fade the after screenshot over the before screenshot.",
      difference: "After screenshot dimmed; changed pixels and regions highlighted.",
    }[mode];
  }

  function renderAll(push) {
    renderSections();
    renderList();
    renderControls();
    renderStage();
    renderDetails();
    saveUrl(push);
  }

  function select(row, push) {
    if (!row) return;
    state.row = row;
    state.section = row.section;
    state.region = -1;
    viewport.scrollTop = 0;
    viewport.scrollLeft = 0;
    renderAll(push);
    buttons.get(row.id)?.scrollIntoView({ block: "nearest" });
  }

  // Wire static controls.
  for (const button of document.querySelectorAll("[data-mode]")) {
    button.addEventListener("click", () => {
      state.mode = button.dataset.mode;
      renderAll(false);
    });
  }
  for (const button of document.querySelectorAll("[data-side]")) {
    button.addEventListener("click", () => {
      state.side = button.dataset.side;
      renderControls();
      renderStage();
    });
  }
  $("zoom-fit").addEventListener("click", () => setZoom("fit"));
  $("zoom-actual").addEventListener("click", () => setZoom(1));
  $("zoom-in").addEventListener("click", () => setZoom(Math.min(4, Math.round((state.scale + 0.25) * 4) / 4)));
  $("zoom-out").addEventListener("click", () => setZoom(Math.max(0.1, Math.round((state.scale - 0.25) * 4) / 4 || 0.1)));
  $("wipe-range").addEventListener("input", (event) => setWipe(Number(event.target.value), false));
  $("opacity").addEventListener("input", (event) => {
    state.opacity = Number(event.target.value);
    $("opacity-value").textContent = `${state.opacity}%`;
    renderStage();
  });
  $("threshold").addEventListener("change", (event) => {
    state.threshold = event.target.value;
    state.region = -1;
    renderStage();
    renderDetails();
    saveUrl(false);
  });
  $("search").addEventListener("input", renderList);
  $("only-changes").addEventListener("change", renderList);
  addEventListener("keydown", (event) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
    if (event.key.toLowerCase() === "t" && effectiveMode() === "toggle") {
      state.side = state.side === "head" ? "base" : "head";
      renderControls();
      renderStage();
    }
  });
  addEventListener("resize", () => state.zoom === "fit" && resize());
  addEventListener("popstate", () => {
    const next = new URLSearchParams(location.hash.slice(1));
    const row = byId.get(next.get("view"));
    if (MODES.includes(next.get("mode"))) state.mode = next.get("mode");
    if (row) select(row, false);
  });

  // Drag to pan when the image is larger than the viewport.
  let pan = null;
  viewport.addEventListener("pointerdown", (event) => {
    if (!viewport.classList.contains("can-pan") && viewport.scrollHeight <= viewport.clientHeight) return;
    pan = { x: event.clientX, y: event.clientY, left: viewport.scrollLeft, top: viewport.scrollTop };
    viewport.classList.add("panning");
  });
  addEventListener("pointermove", (event) => {
    if (!pan) return;
    viewport.scrollLeft = pan.left - (event.clientX - pan.x);
    viewport.scrollTop = pan.top - (event.clientY - pan.y);
  });
  addEventListener("pointerup", () => {
    pan = null;
    viewport.classList.remove("panning");
  });

  if (state.row) renderAll(false);
  else $("view-title").textContent = "No views were captured.";
})();
