export class FieldValidationError extends Error {
  constructor(fieldName, message) {
    super(message);
    this.name = "FieldValidationError";
    this.fieldName = fieldName;
  }
}

function validationError(fieldName, message) {
  if (fieldName) throw new FieldValidationError(fieldName, message);
  throw new Error(message);
}

export function parseJsonField(value, label, fieldName = "") {
  if (!String(value || "").trim()) return {};
  try {
    const result = JSON.parse(value);
    if (result === null || typeof result !== "object" || Array.isArray(result)) throw new Error();
    return result;
  } catch {
    return validationError(fieldName, `${label} must be a JSON object, for example {"profile":"showcase"}.`);
  }
}

export function parseJsonTextList(value, label, fieldName = "", { maximum = null, unique = false } = {}) {
  let result;
  try {
    result = JSON.parse(String(value || "[]"));
  } catch {
    return validationError(fieldName, `${label} must be a non-empty JSON list of text values, for example ["feature-1"].`);
  }
  if (!Array.isArray(result) || !result.length || result.some((item) => typeof item !== "string" || !item.trim())) {
    return validationError(fieldName, `${label} must be a non-empty JSON list of text values, for example ["feature-1"].`);
  }
  if (maximum !== null && result.length > maximum) return validationError(fieldName, `${label} can contain at most ${maximum} values.`);
  if (unique && new Set(result).size !== result.length) return validationError(fieldName, `${label} must not contain duplicate values.`);
  return result;
}

export function parseIntegerField(value, label, { fieldName = "", minimum = null, maximum = null } = {}) {
  const text = String(value ?? "").trim();
  const parsed = Number(text);
  const belowMinimum = minimum !== null && parsed < minimum;
  const aboveMaximum = maximum !== null && parsed > maximum;
  if (!text || !Number.isInteger(parsed) || belowMinimum || aboveMaximum) {
    const range = minimum !== null && maximum !== null
      ? ` from ${minimum} to ${maximum}`
      : minimum !== null ? ` of at least ${minimum}` : maximum !== null ? ` no greater than ${maximum}` : "";
    return validationError(fieldName, `${label} must be a whole number${range}.`);
  }
  return parsed;
}

export function propertySearchQuery(value, fieldName = "q") {
  const query = String(value || "").trim();
  if (query.length < 2 || query.length > 200) {
    return validationError(fieldName, "Property search must contain 2 to 200 characters. Include a street number and suburb or postcode for the clearest match.");
  }
  return query;
}

export function formState(form) {
  return Array.from(form.elements || [])
    .filter((field) => field.name && !field.disabled && !["button", "submit", "reset"].includes(field.type))
    .map((field) => [field.name, field.type === "checkbox" || field.type === "radio" ? Boolean(field.checked) : String(field.value ?? "")]);
}

export function formStateChanged(initial, current) {
  return JSON.stringify(initial) !== JSON.stringify(current);
}

export function createSubmissionGuard(operation, onPending = () => {}) {
  let pending = false;
  return {
    get pending() { return pending; },
    async submit(...args) {
      if (pending) return { duplicate: true, value: undefined };
      pending = true;
      onPending(true);
      try {
        return { duplicate: false, value: await operation(...args) };
      } finally {
        pending = false;
        onPending(false);
      }
    },
  };
}

export function psiYearRange(startValue, endValue, { minimum = 1990, maximum = new Date().getFullYear() + 1 } = {}) {
  const start = Number(startValue);
  const end = Number(endValue);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < minimum || end > maximum || start > end) {
    throw new Error(`PSI years must be a valid range from ${minimum} to ${maximum}; the first year cannot be later than the last year.`);
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
    "psi-sales": "Complete NSW sales history + current weekly updates",
  };
  return labels[String(importProfile || "")] || "Live registered source";
}
