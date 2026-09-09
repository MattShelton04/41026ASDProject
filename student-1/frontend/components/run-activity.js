import { append, button, el } from "../core/dom.js";
import { activityLine } from "../core/run-progress.js";

export function runActivity(events, runId, options) {
  const body = el("div", "stack");
  append(body, el("p", "", "Saved stage and progress events, refreshed while this page is open. The latest 1,000 events are retained per update. Raw container logs are not included."));
  const controls = el("div", "heading-actions");
  const output = el("pre", "run-activity-log");
  output.tabIndex = 0;
  output.setAttribute("aria-label", "Saved run activity");
  const filterLabel = el("label", "field");
  append(filterLabel, el("span", "", "Show events"));
  const filter = el("select");
  for (const [value, name] of [["all", "All stages"], ["problems", "Failures and interruptions"], ["acquire", "Acquisition"], ["import", "Database import"], ["build_release", "Release export"]]) {
    const option = el("option", "", name); option.value = value; option.selected = options.filter === value;
    append(filter, option);
  }
  const draw = () => {
    const visible = options.paused ? options.frozen : events;
    const selected = visible.filter((event) => options.filter === "all" || (options.filter === "problems"
      ? event.error_code || ["failed", "interrupted", "retry_wait", "cancelled"].includes(event.status)
      : event.stage === options.filter));
    output.textContent = selected.map(activityLine).join("\n") || "No matching events recorded yet.";
    if (options.autoscroll) output.scrollTop = output.scrollHeight;
    else output.scrollTop = options.scrollTop || 0;
  };
  filter.addEventListener("change", () => { options.filter = filter.value; draw(); });
  append(filterLabel, filter);
  const pause = button(options.paused ? "Resume live activity" : "Pause live activity", "button secondary small", () => {
    options.paused = !options.paused;
    if (options.paused) options.frozen = [...events];
    pause.textContent = options.paused ? "Resume live activity" : "Pause live activity";
    draw();
  });
  const followLabel = el("label", "run-log-follow");
  const follow = el("input"); follow.type = "checkbox"; follow.checked = options.autoscroll;
  follow.addEventListener("change", () => { options.autoscroll = follow.checked; draw(); });
  append(followLabel, follow, document.createTextNode("Follow latest"));
  output.addEventListener("scroll", () => { options.scrollTop = output.scrollTop; });
  const download = button("Download activity log", "button secondary small", () => {
    const blob = new Blob([events.map(activityLine).join("\n") + "\n"], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = el("a"); anchor.href = url; anchor.download = `update-${runId}-activity.txt`;
    anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  append(controls, filterLabel, pause, followLabel, download);
  append(body, controls, output);
  draw();
  requestAnimationFrame(draw);
  return body;
}
