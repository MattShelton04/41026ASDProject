// PropertyScope visual history: pull request reports, main history and a per-view timeline.
(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("report-data").textContent);
  const $ = (id) => document.getElementById(id);
  const IMAGE = /^[a-f0-9]{64}\.png$/;
  const image = (name) => (typeof name === "string" && IMAGE.test(name) ? `img/${name}` : "");
  const run = (entry) => `runs/${entry.id}/`;
  const labels = Object.fromEntries(data.sections.map((section) => [section.id, section.label]));
  const sectionOf = (id) => {
    const match = /^f([1-5])-/.exec(id);
    return match ? `feature-${match[1]}` : "shared";
  };
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = text;
    return node;
  };
  const link = (href, text, className) => {
    const anchor = el("a", className, text);
    anchor.href = href;
    return anchor;
  };
  const date = (value) => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.valueOf())
      ? "Unknown date"
      : parsed.toLocaleString("en-AU", { dateStyle: "medium", timeStyle: "short" });
  };
  const repo = typeof data.repo === "string" ? data.repo : null;
  const commitLink = (sha) =>
    repo ? link(`https://github.com/${repo}/commit/${sha}`, sha.slice(0, 8)) : el("code", "", sha.slice(0, 8));
  const entries = data.entries;
  const summaryText = (summary) =>
    summary ? `${summary.changed} changed · ${summary.subtle} subtle · ${summary.unchanged} identical · ${summary.incomplete + summary.baseUnavailable} limitations` : "No summary";

  function sectionChips(entry) {
    const chips = el("div", "section-chips");
    for (const section of data.sections) {
      const ids = Object.entries(entry.changes || {}).filter(([id, status]) => sectionOf(id) === section.id && status === "changed");
      const limited = Object.entries(entry.changes || {}).filter(([id, status]) => sectionOf(id) === section.id && ["incomplete", "base unavailable"].includes(status));
      if (!ids.length && !limited.length) continue;
      const chip = link(`${run(entry)}#section=${section.id}`, "", "chip");
      chip.append(section.label);
      if (ids.length) chip.append(el("b", "", `${ids.length} changed`));
      if (limited.length) chip.append(el("span", "", `${limited.length} limited`));
      chips.append(chip);
    }
    if (!chips.childElementCount) chips.append(el("span", "chip", "No review changes"));
    return chips;
  }

  function previews(entry) {
    const grid = el("div", "previews");
    const changed = Object.entries(entry.changes || {}).filter(([, status]) => status === "changed").map(([id]) => id);
    for (const id of changed.slice(0, 3)) {
      const anchor = link(`${run(entry)}#view=${encodeURIComponent(id)}&mode=difference`, "", "preview");
      const img = el("img");
      img.loading = "lazy";
      img.alt = `Changes in ${id}`;
      img.src = image((entry.previews || {})[id]) || image((entry.images || {})[id]);
      anchor.append(img, el("span", "", id));
      grid.append(anchor);
    }
    return grid;
  }

  function matches(entry, query) {
    if (!query) return true;
    const text = [entry.pr ? `#${entry.pr} pr ${entry.pr}` : "main", entry.sha, entry.prTitle, entry.title, ...(entry.views || [])]
      .join(" ")
      .toLowerCase();
    return text.includes(query);
  }

  function renderPullRequests(query) {
    const list = $("pr-list");
    list.replaceChildren();
    const groups = new Map();
    for (const entry of entries.filter((item) => item.pr && matches(item, query))) {
      if (!groups.has(entry.pr)) groups.set(entry.pr, []);
      groups.get(entry.pr).push(entry);
    }
    for (const [pr, runs] of groups) {
      const [latest, ...earlier] = runs;
      const card = el("article", "card");
      const heading = el("h3");
      heading.append(repo ? link(`https://github.com/${repo}/pull/${pr}`, `#${pr}`) : `#${pr}`, latest.prTitle ? ` ${latest.prTitle}` : "");
      const meta = el("p", "meta");
      meta.append(`${date(latest.created)} · head `, commitLink(latest.sha), ` · ${summaryText(latest.summary)}`);
      card.append(heading, meta, sectionChips(latest), previews(latest));
      const open = el("p");
      open.append(link(run(latest), "Open gallery →"));
      card.append(open);
      if (earlier.length) {
        const details = el("details");
        details.append(el("summary", "", `${earlier.length} earlier ${earlier.length === 1 ? "push" : "pushes"}`));
        const items = el("ul");
        for (const entry of earlier) {
          const item = el("li");
          item.append(link(run(entry), `${date(entry.created)} · ${entry.sha.slice(0, 8)}`), ` · ${summaryText(entry.summary)}`);
          items.append(item);
        }
        details.append(items);
        card.append(details);
      }
      list.append(card);
    }
    return groups.size;
  }

  function renderMain(query) {
    const list = $("main-list");
    list.replaceChildren();
    const mains = entries.filter((item) => !item.pr && matches(item, query));
    for (const entry of mains) {
      const row = el("li", "main-row");
      const commit = el("span");
      commit.append(commitLink(entry.sha));
      row.append(el("span", "", date(entry.created)), commit, sectionChips(entry), link(run(entry), "Open gallery →"));
      list.append(row);
    }
    return mains.length;
  }

  const allViews = [...new Set(entries.flatMap((entry) => entry.views || []))].sort(
    (a, b) => data.sections.findIndex((s) => s.id === sectionOf(a)) - data.sections.findIndex((s) => s.id === sectionOf(b)) || a.localeCompare(b),
  );
  function renderTimeline() {
    const select = $("timeline-view");
    if (!select.options.length) {
      for (const section of data.sections) {
        const group = el("optgroup");
        group.label = section.label;
        for (const id of allViews.filter((view) => sectionOf(view) === section.id)) {
          const option = el("option", "", id);
          option.value = id;
          group.append(option);
        }
        if (group.childElementCount) select.append(group);
      }
      const requested = new URLSearchParams(location.hash.slice(1)).get("view");
      if (requested && allViews.includes(requested)) select.value = requested;
    }
    const view = select.value;
    const scope = $("timeline-scope").value;
    const list = $("timeline-list");
    list.replaceChildren();
    const relevant = entries
      .filter((entry) => (scope === "all" || !entry.pr) && (entry.images || {})[view])
      .sort((a, b) => a.id - b.id);
    let previous = null;
    let skipped = 0;
    const shown = [];
    for (const entry of relevant) {
      const current = entry.images[view];
      if (current === previous) {
        skipped++;
        continue;
      }
      shown.push({ entry, skipped });
      skipped = 0;
      previous = current;
    }
    for (const { entry, skipped: hidden } of shown.reverse()) {
      if (hidden) list.append(el("p", "collapsed", `${hidden} ${hidden === 1 ? "run" : "runs"} with identical pixels`));
      const card = el("article", "card");
      const heading = el("h3", "", entry.pr ? `PR #${entry.pr}` : "Main");
      const meta = el("p", "meta");
      meta.append(`${date(entry.created)} · `, commitLink(entry.sha), ` · ${(entry.changes || {})[view] || "unchanged"} in this run`);
      const img = el("img");
      img.loading = "lazy";
      img.alt = `${view} at ${entry.sha.slice(0, 8)}`;
      img.src = image(entry.images[view]);
      const open = el("p");
      open.append(link(`${run(entry)}#view=${encodeURIComponent(view)}`, "Compare in gallery →"));
      card.append(heading, meta, img, open);
      list.append(card);
    }
    if (!shown.length) list.append(el("p", "history-note", "No retained run captured this view."));
    return shown.length;
  }

  let tab = new URLSearchParams(location.hash.slice(1)).get("tab") || (entries.some((e) => e.pr) ? "prs" : "main");
  function render() {
    const query = $("history-search").value.trim().toLowerCase();
    for (const button of document.querySelectorAll("[data-tab]")) {
      const active = button.dataset.tab === tab;
      button.setAttribute("aria-selected", String(active));
      button.setAttribute("aria-pressed", String(active));
      $(`panel-${button.dataset.tab}`).hidden = !active;
    }
    const count = tab === "prs" ? renderPullRequests(query) : tab === "main" ? renderMain(query) : renderTimeline();
    $("history-empty").hidden = count > 0;
  }
  for (const button of document.querySelectorAll("[data-tab]")) {
    button.addEventListener("click", () => {
      tab = button.dataset.tab;
      history.replaceState(null, "", `#tab=${tab}`);
      render();
    });
  }
  $("history-search").addEventListener("input", render);
  $("timeline-view").addEventListener("change", render);
  $("timeline-scope").addEventListener("change", render);
  if (!Object.keys(labels).length) return;
  render();
})();
