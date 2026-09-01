function stageLabel(value) {
  const words = String(value || "update").replaceAll("_", " ");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

export function runFailureSummary(run, tasks = []) {
  const failedTask = [...tasks].reverse().find((task) => task.status === "failed" && task.error_json);
  const error = failedTask?.error_json || run?.error_json;
  if (!error) return null;
  return {
    code: error.code || "run_failed",
    title: `${stageLabel(failedTask?.stage)} could not continue`,
    message: error.message || error.detail || "The update recorded a classified failure.",
    cachedReplayRecommended: error.code === "psi_postcode_placeholder",
  };
}

const TERMINAL_INTERRUPTION_STATES = new Set(["cancelled", "failed", "interrupted"]);
const ACTIVE_TASK_STATES = new Set(["claimed", "running", "retry_wait"]);

export function reconcileTimelineTask(run, task) {
  if (!TERMINAL_INTERRUPTION_STATES.has(run?.status) || !ACTIVE_TASK_STATES.has(task?.status)) {
    return task;
  }
  return {
    ...task,
    status: run.status,
    finished_at: task.finished_at
      || task.lease_expires_at
      || run.finished_at
      || run.last_activity_at
      || run.heartbeat_at
      || task.heartbeat_at
      || task.progress_updated_at
      || task.updated_at,
    error_json: task.error_json || run.error_json,
  };
}

export function failureExplanationDraft(run, tasks = []) {
  const failure = runFailureSummary(run, tasks);
  if (!failure) return "Explain this data update and recommend the safest next step.";
  return `Explain why this data update failed at the ${failure.title.toLowerCase()}. `
    + `Use the recorded ${failure.code} evidence to explain the cause in plain language and recommend `
    + "the safest next step. Do not retry, change, or publish data.";
}
