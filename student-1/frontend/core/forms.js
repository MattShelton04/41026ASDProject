export class FieldValidationError extends Error {
  constructor(fieldName, message, validateValue = null) {
    super(message);
    this.name = "FieldValidationError";
    this.fieldName = fieldName;
    this.validateValue = validateValue;
  }
}

function validationError(fieldName, message, validateValue = null) {
  if (fieldName) throw new FieldValidationError(fieldName, message, validateValue);
  throw new Error(message);
}

function jsonObjectValue(value) {
  if (!String(value || "").trim()) return true;
  try {
    const result = JSON.parse(value);
    return result !== null && typeof result === "object" && !Array.isArray(result);
  } catch {
    return false;
  }
}

function jsonTextListValue(value, { maximum = null, unique = false } = {}) {
  try {
    const result = JSON.parse(String(value || "[]"));
    return Array.isArray(result)
      && result.length > 0
      && result.every((item) => typeof item === "string" && item.trim())
      && (maximum === null || result.length <= maximum)
      && (!unique || new Set(result).size === result.length);
  } catch {
    return false;
  }
}

function integerValue(value, { minimum = null, maximum = null } = {}) {
  const text = String(value ?? "").trim();
  const parsed = Number(text);
  return Boolean(text)
    && Number.isInteger(parsed)
    && (minimum === null || parsed >= minimum)
    && (maximum === null || parsed <= maximum);
}

export function parseJsonField(value, label, fieldName = "") {
  if (!String(value || "").trim()) return {};
  try {
    const result = JSON.parse(value);
    if (result === null || typeof result !== "object" || Array.isArray(result)) throw new Error();
    return result;
  } catch {
    return validationError(fieldName, `${label} must be a JSON object, for example {"profile":"full-data","all_records":true}.`, jsonObjectValue);
  }
}

export function parseJsonTextList(value, label, fieldName = "", { maximum = null, unique = false } = {}) {
  const validateValue = (candidate) => jsonTextListValue(candidate, { maximum, unique });
  let result;
  try {
    result = JSON.parse(String(value || "[]"));
  } catch {
    return validationError(fieldName, `${label} must be a non-empty JSON list of text values, for example ["feature-1"].`, validateValue);
  }
  if (!Array.isArray(result) || !result.length || result.some((item) => typeof item !== "string" || !item.trim())) {
    return validationError(fieldName, `${label} must be a non-empty JSON list of text values, for example ["feature-1"].`, validateValue);
  }
  if (maximum !== null && result.length > maximum) return validationError(fieldName, `${label} can contain at most ${maximum} values.`, validateValue);
  if (unique && new Set(result).size !== result.length) return validationError(fieldName, `${label} must not contain duplicate values.`, validateValue);
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
    return validationError(fieldName, `${label} must be a whole number${range}.`, (candidate) => integerValue(candidate, { minimum, maximum }));
  }
  return parsed;
}

export function propertySearchQuery(value, fieldName = "q") {
  const query = String(value || "").trim();
  if (query.length < 2 || query.length > 200) {
    return validationError(fieldName, "Property search must contain 2 to 200 characters. Include a street number and suburb or postcode for the clearest match.", (candidate) => {
      const length = String(candidate || "").trim().length;
      return length >= 2 && length <= 200;
    });
  }
  const commonTerms = new Set(["australia", "nsw", "street", "st", "road", "rd", "avenue", "ave", "drive", "dr", "lane", "ln", "court", "ct", "place", "pl", "highway", "hwy", "unit", "lot"]);
  const normalised = query.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const distinctive = normalised.split(" ").filter((token) => token && !commonTerms.has(token));
  if (!distinctive.length || (distinctive.length === 1 && /^[a-z]+$/.test(distinctive[0]) && distinctive[0].length < 8)) {
    return validationError(fieldName, "Property search must include a street number, postcode, distinctive locality, or a more complete address.", (candidate) => {
      try { propertySearchQuery(candidate, fieldName); return true; } catch { return false; }
    });
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

export function psiYearRange(startValue, endValue, { minimum = 1990, maximum = new Date().getFullYear() - 1 } = {}) {
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
    "schools-master": "Complete official Data.NSW schools dataset",
    "bocsar-sparse": "Complete official BOCSAR postcode + suburb datasets",
    "gnaf-nsw": "Complete official NSW G-NAF address registry",
    "psi-sales": "Complete NSW sales history + current weekly updates",
  };
  return labels[String(importProfile || "")] || "Live registered source";
}
