export function parseJsonField(value, label) {
  if (!String(value || "").trim()) return {};
  try {
    const result = JSON.parse(value);
    if (result === null || typeof result !== "object" || Array.isArray(result)) throw new Error();
    return result;
  } catch {
    throw new Error(`${label} must be a JSON object.`);
  }
}

export function psiYearRange(startValue, endValue, { minimum = 1990, maximum = new Date().getFullYear() + 1 } = {}) {
  const start = Number(startValue);
  const end = Number(endValue);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < minimum || end > maximum || start > end) {
    throw new Error(`PSI years must be a valid range from ${minimum} to ${maximum}.`);
  }
  return Array.from({ length: end - start + 1 }, (_unused, index) => start + index);
}

function jobIdentity(job) {
  return [job?.profile_key, job?.adapter_key, job?.import_profile_key, job?.dataset_id]
    .map((value) => String(value || "").toLowerCase())
    .join(" ");
}

export function isPsiJob(job) { return jobIdentity(job).includes("psi"); }
export function isSchoolsJob(job) { return jobIdentity(job).includes("school"); }

export function liveProfileLabel(importProfile) {
  const labels = {
    "schools-master": "Live official Data.NSW schools CSV",
    "bocsar-sparse": "Live official BOCSAR archive",
    "gnaf-nsw": "Live official Geoscape G-NAF bulk archive",
    "psi-sales": "Live NSW Valuer-General yearly archive",
  };
  return labels[String(importProfile || "")] || "Live registered source";
}
