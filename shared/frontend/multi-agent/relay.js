/**
 * Mission relay renderers: agent lanes (wide columns), the relay strip (narrow columns), the
 * "now" line, the replay transport and the Reviewer's side of the decision card.
 * Positions are CSS custom properties in percent of the drawing; nothing measures layout.
 * Every untrusted value is set as text, never HTML.
 */
import { append, el } from "../browser/index.js";
import { DEFAULT_MULTI_AGENT_LABELS, humaniseValue } from "./definitions.js";
import { formatDuration, groupFindings } from "./projections.js";
import { LANES, checkName, decisionLabel, formatClock } from "./timeline.js";

const STATION_MARKS = Object.freeze({ planner: "P", worker: "W", reviewer: "R", human: "You" });
// Long enough for the arrival animations in styles.css to finish before the class is dropped.
const NEW_FOR_MS = 1600;
const REPLAY_SPEEDS = Object.freeze([1, 2, 4]);
const TOP_CHECKS = 3;

/** CSSOM custom properties; absent in test doubles without `style`. */
export function setVars(node, vars) {
  const style = node?.style;
  if (!style || typeof style.setProperty !== "function") return;
  for (const [name, value] of Object.entries(vars)) style.setProperty(name, String(value));
}

/**
 * Keyed children: existing nodes are updated in place so arrival animations play once.
 * A node created while `animate` is true gets `is-new` until NEW_FOR_MS has passed.
 */
function reconcile(parent, store, items, create, update, { animate = false, now = Date.now() } = {}) {
  const keep = new Set();
  for (const item of items) {
    let node = store.get(item.key);
    if (!node) {
      node = create(item);
      store.set(item.key, node);
      parent.append(node);
      if (animate) { node.classList.add("is-new"); node.dataset.born = String(now); }
    } else if (node.dataset.born && now - Number(node.dataset.born) > NEW_FOR_MS) {
      node.classList.remove("is-new");
      delete node.dataset.born;
    }
    update(node, item);
    keep.add(item.key);
  }
  for (const [key, node] of store) {
    if (keep.has(key)) continue;
    node.remove?.();
    store.delete(key);
  }
}

function laneStatusText(lane, { live, labels }) {
  if (lane.active) {
    const lead = lane.role === "human" ? (live ? "Your turn" : "Waiting") : "Working";
    return `${lead} · ${formatDuration(lane.elapsedMs)}`;
  }
  if (lane.status === "pending") return labels.stageStatuses?.pending || "Not started";
  if (lane.status === "failed" || lane.status === "cancelled") return labels.stageStatuses?.[lane.status] || humaniseValue(lane.status);
  if (lane.role === "human" && lane.detail) return decisionLabel(lane.detail, lane.round || 1, labels);
  return lane.durationMs !== null ? `Done · ${formatDuration(lane.durationMs)}` : "Done";
}

/** Four lanes on one time axis. The list carries the accessible stage summary. */
export function createLaneBoard(labels = DEFAULT_MULTI_AGENT_LABELS) {
  const node = el("div", "ps-multi-agent__board");
  const list = el("ol", "ps-multi-agent__lanes ps-multi-agent__timeline");
  list.setAttribute("aria-label", "Agent lanes");
  const overlay = el("div", "ps-multi-agent__overlay");
  overlay.setAttribute("aria-hidden", "true");
  const lanes = new Map();
  for (const role of LANES) {
    const row = el("li", `ps-multi-agent__lane ps-multi-agent__stage ps-multi-agent__lane--${role}`);
    row.dataset.stage = role;
    row.dataset.status = "pending";
    const label = el("div", "ps-multi-agent__lane-label");
    const name = el("span", "ps-multi-agent__lane-name");
    const dot = el("span", "ps-multi-agent__role-dot");
    dot.setAttribute("aria-hidden", "true");
    append(name, dot, el("span", "", labels.stages?.[role] || humaniseValue(role)));
    const status = el("span", "ps-multi-agent__lane-status ps-multi-agent__stage-status");
    append(label, name, status);
    const track = el("div", "ps-multi-agent__track");
    track.setAttribute("aria-hidden", "true");
    append(row, label, track);
    append(list, row);
    lanes.set(role, { row, status, track, nodes: new Map() });
  }
  const overlayNodes = new Map();
  append(node, list, overlay);

  function update(view, { animate = false, live = true, now = Date.now() } = {}) {
    for (const lane of view.lanes) {
      const ref = lanes.get(lane.role);
      ref.row.dataset.status = lane.status;
      ref.row.dataset.active = String(lane.active);
      ref.status.textContent = laneStatusText(lane, { live, labels });
      const items = [
        ...lane.segments.map((item) => ({ ...item, type: "segment" })),
        ...lane.models.map((item) => ({ ...item, type: "model" })),
        ...lane.tools.map((item) => ({ ...item, type: "tool" })),
      ];
      reconcile(ref.track, ref.nodes, items, (item) => {
        if (item.type === "tool") { const pin = el("span", "ps-multi-agent__pin"); append(pin, el("i")); return pin; }
        return el("span", item.type === "model" ? "ps-multi-agent__model" : "ps-multi-agent__segment");
      }, (target, item) => {
        setVars(target, { "--x": `${item.x}%`, "--w": `${item.width ?? 0}%` });
        if (item.type === "segment") {
          target.dataset.status = item.status;
          target.title = item.shortened ? `${formatDuration(item.durationMs)} of waiting, shortened on this axis` : `${labels.stages?.[lane.role] || lane.role}, round ${item.round}: ${formatDuration(item.durationMs)}`;
        } else if (item.type === "model") {
          target.classList[item.retry ? "add" : "remove"]("ps-multi-agent__model--retry");
          target.title = `${item.model || "Model"} · attempt ${item.attempt} · ${humaniseValue(item.outcome)} · ${formatDuration(item.durationMs)}`;
        } else {
          target.classList[item.failed ? "add" : "remove"]("ps-multi-agent__pin--failed");
          target.title = `${item.tool} · ${humaniseValue(item.outcome)} · ${formatDuration(item.durationMs)}`;
        }
      }, { animate, now });
    }
    const overlayItems = [
      ...view.batons.map((item) => ({ ...item, type: "baton" })),
      ...(view.roundMark ? [{ key: "round-mark", type: "round", ...view.roundMark }] : []),
      ...(view.playhead !== null ? [{ key: "playhead", type: "playhead", x: view.playhead }] : []),
    ];
    reconcile(overlay, overlayNodes, overlayItems, (item) => {
      if (item.type === "baton") {
        const baton = el("span", `ps-multi-agent__baton${item.correction ? " ps-multi-agent__baton--correction" : ""}`);
        append(baton, el("b"));
        return baton;
      }
      if (item.type === "round") { const mark = el("span", "ps-multi-agent__round-mark"); append(mark, el("span", "", `Round ${item.round}`)); return mark; }
      return el("span", "ps-multi-agent__playhead");
    }, (target, item) => {
      const vars = { "--x": `${item.x}%` };
      if (item.type === "baton") {
        const down = item.to > item.from;
        Object.assign(vars, {
          "--lane-top": Math.min(item.from, item.to), "--lane-span": Math.abs(item.to - item.from),
          "--dot-from": down ? "0%" : "100%", "--dot-to": down ? "100%" : "0%",
        });
      }
      setVars(target, vars);
    }, { animate, now });
  }
  return { node, update };
}

/** The narrow layout: four stations, a baton at the current holder and a loop for a correction. */
export function createRelayStrip(labels = DEFAULT_MULTI_AGENT_LABELS) {
  const node = el("div", "ps-multi-agent__relay");
  const decor = el("div", "ps-multi-agent__relay-track");
  decor.setAttribute("aria-hidden", "true");
  append(decor, el("span", "ps-multi-agent__relay-fill"));
  const loop = el("span", "ps-multi-agent__relay-loop");
  loop.setAttribute("aria-hidden", "true");
  append(loop, el("span", "", "sent back once"));
  const baton = el("span", "ps-multi-agent__relay-baton");
  baton.setAttribute("aria-hidden", "true");
  const list = el("ol", "ps-multi-agent__stations");
  list.setAttribute("aria-label", "Agent relay");
  const stations = new Map();
  for (const role of LANES) {
    const item = el("li", `ps-multi-agent__station ps-multi-agent__station--${role}`);
    item.dataset.role = role;
    item.dataset.status = "pending";
    const mark = el("span", "ps-multi-agent__station-mark", STATION_MARKS[role]);
    mark.setAttribute("aria-hidden", "true");
    const name = el("strong", "", labels.stages?.[role] || humaniseValue(role));
    const timing = el("small", "");
    append(item, mark, name, timing);
    append(list, item);
    stations.set(role, { item, timing });
  }
  append(node, decor, loop, list, baton);

  function update(view, { live = true } = {}) {
    for (const station of view.stations) {
      const ref = stations.get(station.role);
      ref.item.dataset.status = station.status;
      let text = "";
      if (station.elapsedMs !== null) text = station.role === "human" && live ? `Your turn · ${formatDuration(station.elapsedMs)}` : formatDuration(station.elapsedMs);
      else if (station.role === "human" && station.detail) text = decisionLabel(station.detail, 1, labels);
      else if (station.durationMs !== null) text = formatDuration(station.durationMs);
      else if (station.status !== "pending") text = humaniseValue(station.status);
      ref.timing.textContent = text;
    }
    node.dataset.loop = String(view.loop);
    setVars(node, { "--station": view.baton });
  }
  return { node, update };
}

/** One line: what is happening and how long it has taken. Waiting is striped, never a percentage. */
export function createNowLine() {
  const node = el("div", "ps-multi-agent__now");
  let key = "";
  let time = null;
  function update(view, { animate = false } = {}) {
    const next = JSON.stringify([view.tone, view.role, view.text, view.tools.map((tool) => tool.key)]);
    if (next !== key) {
      key = next;
      node.dataset.tone = view.tone;
      node.dataset.role = view.role || "";
      const lead = el("div", "ps-multi-agent__now-lead");
      const dot = el("span", "ps-multi-agent__now-dot");
      dot.setAttribute("aria-hidden", "true");
      append(lead, dot, el("p", "ps-multi-agent__now-text", view.text));
      const parts = [lead];
      if (view.waiting) { const stripe = el("span", "ps-multi-agent__wait"); stripe.setAttribute("aria-hidden", "true"); parts.push(stripe); }
      time = view.sinceMs !== null ? el("time", "ps-multi-agent__now-time") : null;
      if (time) parts.push(time);
      if (view.tools.length) {
        const pills = el("ul", "ps-multi-agent__pills");
        pills.setAttribute("aria-label", "Tool calls this round");
        for (const tool of view.tools) {
          const pill = el("li", `ps-multi-agent__pill${tool.ok ? "" : " ps-multi-agent__pill--failed"}`, `${tool.ok ? "✓" : "✕"} ${tool.tool}`);
          pill.title = humaniseValue(tool.outcome);
          if (animate && !node.dataset[`seen${tool.key.replaceAll(/[^a-z0-9]/gi, "")}`]) pill.classList.add("is-new");
          node.dataset[`seen${tool.key.replaceAll(/[^a-z0-9]/gi, "")}`] = "1";
          append(pills, pill);
        }
        parts.push(pills);
      }
      node.replaceChildren(...parts);
    }
    if (time) time.textContent = formatDuration(view.sinceMs);
  }
  return { node, update };
}

/** Transport for a recorded run. Commands go to `onCommand`; the panel owns the clock. */
export function createReplayBar({ model, labels = DEFAULT_MULTI_AGENT_LABELS, onCommand }) {
  const node = el("div", "ps-multi-agent__replay");
  node.setAttribute("role", "group");
  node.setAttribute("aria-label", "Replay controls");
  const button = (className, text, action, label) => {
    const control = el("button", `ps-multi-agent__replay-button ${className}`.trim(), text);
    control.type = "button";
    control.dataset.action = action;
    if (label) control.setAttribute("aria-label", label);
    return control;
  };
  const play = button("ps-multi-agent__replay-play", "▶", "replay", "Replay the run");
  const previous = button("", "‹", "replay-previous", "Previous recorded event");
  const next = button("", "›", "replay-next", "Next recorded event");
  const scrub = el("input", "ps-multi-agent__replay-range");
  scrub.type = "range";
  scrub.min = "0";
  scrub.max = String(Math.max(1, Math.round(model.axisEnd)));
  scrub.step = "10";
  scrub.dataset.action = "replay-seek";
  scrub.setAttribute("aria-label", "Replay position");
  const clock = el("span", "ps-multi-agent__replay-clock");
  clock.setAttribute("aria-hidden", "true");
  const speed = el("select", "ps-multi-agent__replay-speed");
  speed.setAttribute("aria-label", "Replay speed");
  for (const value of REPLAY_SPEEDS) {
    const option = el("option", "", `${value}×`);
    option.value = String(value);
    append(speed, option);
  }
  const jumps = el("div", "ps-multi-agent__replay-jumps");
  model.decisionPoints.forEach((point, index) => {
    const jump = button("ps-multi-agent__replay-chip", model.decisionPoints.length > 1 ? `Decision ${index + 1}` : "Decision", "replay-jump");
    jump.dataset.round = String(point.round);
    jump.addEventListener("click", () => onCommand({ type: "jump", round: point.round }));
    append(jumps, jump);
  });
  const outcome = button("ps-multi-agent__replay-chip", "Outcome", "replay-outcome");
  outcome.addEventListener("click", () => onCommand({ type: "end" }));
  append(jumps, outcome);
  const note = el("p", "ps-multi-agent__replay-note", "Replays the recorded timestamps. Waits for a person are shortened; nothing is sent.");
  append(node, play, previous, next, scrub, clock, speed, jumps, note);

  play.addEventListener("click", () => onCommand({ type: "toggle" }));
  previous.addEventListener("click", () => onCommand({ type: "step", direction: -1 }));
  next.addEventListener("click", () => onCommand({ type: "step", direction: 1 }));
  scrub.addEventListener("input", () => onCommand({ type: "seek", axis: Number(scrub.value), atEnd: Number(scrub.value) >= Number(scrub.max) - 10 }));
  speed.addEventListener("change", () => onCommand({ type: "speed", value: Number(speed.value) }));

  function update({ t, playing, speed: rate, description }) {
    const axis = model.toAxis(t);
    scrub.value = String(Math.round(axis));
    scrub.setAttribute("aria-valuetext", description);
    const squeeze = model.squeezes.find((item) => t > item.from && t < item.to);
    clock.textContent = squeeze
      ? `${formatClock(axis)} · waited ${formatDuration(t - squeeze.from)} of ${formatDuration(squeeze.real)}`
      : `${formatClock(axis)} / ${formatClock(model.axisEnd)}`;
    play.textContent = playing ? "❚❚" : "▶";
    play.setAttribute("aria-label", playing ? "Pause the replay" : t >= model.end ? "Replay the run from the start" : "Continue the replay");
    play.setAttribute("aria-pressed", String(playing));
    speed.value = String(rate);
    node.dataset.playing = String(playing);
  }
  return { node, update, focus: () => play.focus() };
}

/** The Reviewer's side of the decision card: the suggestion and failed checks, three at a time. */
export function renderReviewerSide(review, roundNumber, { labels = DEFAULT_MULTI_AGENT_LABELS, context = null, scope = "current" } = {}) {
  const host = el("div", "ps-multi-agent__found");
  const recommendation = el("p", "ps-multi-agent__suggest", review?.recommendation ? decisionLabel(review.recommendation, roundNumber, labels) : "No recommendation");
  recommendation.dataset.recommendation = review?.recommendation || "";
  append(host, el("h4", "ps-multi-agent__kicker", labels.reviewerSuggests), recommendation);
  const groups = groupFindings(review?.findings);
  const expanded = context?.disclosures;
  const allKey = `checks-all-${scope}`;
  if (groups.failed.length) {
    const list = el("ul", "ps-multi-agent__checks");
    list.setAttribute("aria-label", "Failed checks");
    groups.failed.forEach((finding, index) => {
      const item = el("li", "ps-multi-agent__check");
      item.dataset.findingId = finding.id || "";
      item.hidden = index >= TOP_CHECKS && !expanded?.get(allKey);
      const whyKey = `why-${scope}-${finding.id}`;
      const more = el("p", "ps-multi-agent__check-more", [finding.message, finding.recommendation].filter(Boolean).join(" "));
      more.id = `${scope}-why-${String(finding.id || index).replaceAll(/[^\w-]/g, "")}`;
      more.hidden = !expanded?.get(whyKey);
      const why = el("button", "ps-multi-agent__why", more.hidden ? "Why" : "Hide");
      why.type = "button";
      why.setAttribute("aria-expanded", String(!more.hidden));
      why.setAttribute("aria-controls", more.id);
      why.addEventListener("click", () => {
        more.hidden = !more.hidden;
        expanded?.set(whyKey, !more.hidden);
        why.textContent = more.hidden ? "Why" : "Hide";
        why.setAttribute("aria-expanded", String(!more.hidden));
      });
      const name = el("span", "ps-multi-agent__check-name", checkName(finding));
      name.title = finding.message || "";
      append(item, el("span", `ps-multi-agent__severity ps-multi-agent__severity--${finding.severity}`, humaniseValue(finding.severity)), name, why, more);
      append(list, item);
    });
    append(host, list);
    if (groups.failed.length > TOP_CHECKS) {
      const hiddenCount = groups.failed.length - TOP_CHECKS;
      const toggle = el("button", "ps-multi-agent__link", expanded?.get(allKey) ? "Show fewer" : `Show ${hiddenCount} more failed check${hiddenCount === 1 ? "" : "s"}`);
      toggle.type = "button";
      toggle.setAttribute("aria-expanded", String(Boolean(expanded?.get(allKey))));
      toggle.addEventListener("click", () => {
        const open = !expanded?.get(allKey);
        expanded?.set(allKey, open);
        for (const [index, child] of [...(list.children || [])].entries()) if (index >= TOP_CHECKS) child.hidden = !open;
        toggle.textContent = open ? "Show fewer" : `Show ${hiddenCount} more failed check${hiddenCount === 1 ? "" : "s"}`;
        toggle.setAttribute("aria-expanded", String(open));
      });
      append(host, toggle);
    }
  } else append(host, el("p", "ps-multi-agent__passed-count", groups.total ? "No check failed." : "The Reviewer recorded no checks."));
  if (groups.total) {
    append(host, el("p", "ps-multi-agent__passed-count", groups.passed.length
      ? `${groups.passed.length} ${groups.failed.length ? "other " : ""}check${groups.passed.length === 1 ? "" : "s"} passed.`
      : "No check passed."));
  }
  return host;
}
