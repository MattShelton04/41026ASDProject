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
