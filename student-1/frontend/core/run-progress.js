import { durationMilliseconds, humanise } from "./formats.js";

export function taskProgress(task, now = Date.now()) {
  const active = ["claimed", "running"].includes(task.status);
  const waiting = ["pending", "retry_wait"].includes(task.status);
  const heartbeatAge = durationMilliseconds(task.heartbeat_at, now);
  const progressAge = durationMilliseconds(task.progress_changed_at || task.progress_updated_at, now);
  const stale = active && (heartbeatAge === null || heartbeatAge > 45_000);
  const rows = waiting ? 0 : Math.max(Number(task.progress_rows || 0), Number(task.rows_out || 0));
  const bytes = waiting ? 0 : Number(task.progress_bytes || 0);
  const totalRows = waiting ? null : Number(task.progress_total_rows);
  const totalBytes = waiting ? null : Number(task.progress_total_bytes);
  const usesRows = Number.isFinite(totalRows) && totalRows > 0;
  const total = usesRows ? totalRows : totalBytes;
  const processed = usesRows ? rows : bytes;
  const ratio = Number.isFinite(total) && total > 0 ? Math.min(1, Math.max(0, processed / total)) : null;
  return {
    active, waiting, stale, rows, bytes, total, usesRows, ratio, heartbeatAge, progressAge,
    stalled: active && !stale && progressAge !== null && progressAge > 120_000,
    elapsed: waiting ? null : durationMilliseconds(task.started_at, task.finished_at || now),
  };
}

export function activityLine(event) {
  const code = event.error_code ? ` · ${String(event.error_code).slice(0, 120)}` : "";
  return `${event.recorded_at} · ${humanise(event.stage)} · ${humanise(event.status)} · attempt ${event.attempt_number}`
    + `${event.phase ? ` · ${String(event.phase).slice(0, 100)}` : ""}`
    + ` · ${event.rows_processed || 0} rows · ${event.bytes_processed || 0} bytes${code}`
    + (event.event_kind === "snapshot" ? " · existing state at log activation" : "");
}

export function mergeActivity(existing, incoming, limit = 1000) {
  const entries = new Map(existing.map((event) => [String(event.id), event]));
  for (const event of incoming) entries.set(String(event.id), event);
  return [...entries.values()].sort((a, b) => Number(a.id) - Number(b.id)).slice(-limit);
}
