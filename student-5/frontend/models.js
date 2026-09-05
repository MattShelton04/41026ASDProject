import {
  ApiProblem,
  MAX_PREFERENCE_ITEMS,
  MAX_PREFERENCE_TEXT_LENGTH,
  JOURNEY_STAGES,
  PROPERTY_PRIORITIES,
} from "./api.js";

export function statusLabel(status) {
  return { active: "Active", paused: "Paused", closed: "Closed" }[status] || "Unknown";
}

export function statusClass(status) {
  return {
    active: "ps-badge--confirmed",
    paused: "ps-badge--partial",
    closed: "ps-badge--planned",
  }[status] || "";
}

export function formatBudget(minimum, maximum) {
  const currency = new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    maximumFractionDigits: 0,
  });
  if (minimum == null && maximum == null) return "Not set";
  if (minimum == null) return `Up to ${currency.format(maximum)}`;
  if (maximum == null) return `From ${currency.format(minimum)}`;
  return `${currency.format(minimum)} – ${currency.format(maximum)}`;
}

export function formatUpdated(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-AU", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Australia/Sydney",
  }).format(date);
}

export function targetSuburbsFromText(value) {
  const seen = new Set();
  return String(value || "")
    .split(/\r?\n|,/)
    .map((locality) => locality.trim().toUpperCase())
    .filter((locality) => {
      if (!locality || seen.has(locality)) return false;
      seen.add(locality);
      return true;
    })
    .map((locality) => ({ state: "NSW", locality }));
}

export function preferenceStringsFromText(value) {
  const seen = new Set();
  return String(value || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter((item) => {
      const key = item.toLocaleLowerCase("en-AU");
      if (!item || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

export function projectPreferenceLists(preferences) {
  const value = preferences && typeof preferences === "object" && !Array.isArray(preferences)
    ? preferences
    : {};
  return {
    dwellingTypes: Array.isArray(value.dwelling_types)
      ? value.dwelling_types.filter((item) => typeof item === "string")
      : [],
    priorities: Array.isArray(value.priorities)
      ? value.priorities.filter((item) => typeof item === "string")
      : [],
  };
}

export function mergePreferences(existing, dwellingTypes, priorities) {
  const retained = existing && typeof existing === "object" && !Array.isArray(existing)
    ? { ...existing }
    : {};
  return {
    ...retained,
    dwelling_types: [...dwellingTypes],
    priorities: [...priorities],
  };
}

export function validateCaseInput(values) {
  const errors = {};
  const name = String(values.name || "").trim();
  const minimum = values.budgetMin === "" ? null : Number(values.budgetMin);
  const maximum = values.budgetMax === "" ? null : Number(values.budgetMax);
  const suburbs = targetSuburbsFromText(values.suburbs);
  const dwellingTypes = preferenceStringsFromText(values.dwellingTypes);
  const priorities = preferenceStringsFromText(values.priorities);
  if (!name) errors.name = "Enter a case name.";
  if (name.length > 120) errors.name = "Case name must contain at most 120 characters.";
  if (minimum !== null && (!Number.isInteger(minimum) || minimum < 0)) {
    errors.budget = "Minimum budget must be a whole non-negative amount.";
  }
  if (maximum !== null && (!Number.isInteger(maximum) || maximum < 0)) {
    errors.budget = "Maximum budget must be a whole non-negative amount.";
  }
  if (minimum !== null && maximum !== null && maximum < minimum) {
    errors.budget = "Maximum budget cannot be less than minimum budget.";
  }
  if (suburbs.some((item) => item.locality.length > 100)) {
    errors.suburbs = "Each locality must contain at most 100 characters.";
  }
  if (dwellingTypes.length > MAX_PREFERENCE_ITEMS || priorities.length > MAX_PREFERENCE_ITEMS) {
    errors.preferences = `Use at most ${MAX_PREFERENCE_ITEMS} items in each preference list.`;
  }
  if (
    dwellingTypes.some((item) => item.length > MAX_PREFERENCE_TEXT_LENGTH)
    || priorities.some((item) => item.length > MAX_PREFERENCE_TEXT_LENGTH)
  ) {
    errors.preferences = `Each preference must contain at most ${MAX_PREFERENCE_TEXT_LENGTH} characters.`;
  }
  if (!["active", "paused", "closed"].includes(values.status || "active")) {
    errors.status = "Choose a supported status.";
  }
  return { errors, name, minimum, maximum, suburbs, dwellingTypes, priorities };
}

export function buildCasePayload(values, version = null, existingPreferences = {}) {
  const validated = validateCaseInput(values);
  if (Object.keys(validated.errors).length) return { errors: validated.errors, payload: null };
  const payload = {
    name: validated.name,
    budget_min_aud: validated.minimum,
    budget_max_aud: validated.maximum,
    target_suburbs: validated.suburbs,
    preferences: mergePreferences(
      existingPreferences,
      validated.dwellingTypes,
      validated.priorities,
    ),
    status: values.status || "active",
  };
  if (version !== null) payload.version = version;
  return { errors: {}, payload };
}

function optionalInteger(value) {
  return value === "" || value == null ? null : Number(value);
}

export function buildPropertyPayload(values, version = null) {
  const errors = {};
  const propertyRef = String(values.propertyRef || "").trim();
  const label = String(values.propertyLabel || "").trim();
  const rating = optionalInteger(values.rating);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(propertyRef)) {
    errors.propertyRef = "Enter a valid property reference UUID.";
  }
  if (label.length > 500) errors.propertyLabel = "Property label must contain at most 500 characters.";
  if (!JOURNEY_STAGES.includes(values.journeyStage || "Shortlisted")) errors.journeyStage = "Choose a supported journey stage.";
  if (rating !== null && (!Number.isInteger(rating) || rating < 1 || rating > 5)) errors.rating = "Rating must be empty or from 1 to 5.";
  if (!PROPERTY_PRIORITIES.includes(values.priority || "medium")) errors.priority = "Choose a supported priority.";
  if (Object.keys(errors).length) return { errors, payload: null };
  const payload = {
    property_label: label || null,
    journey_stage: values.journeyStage || "Shortlisted",
    rating,
    priority: values.priority || "medium",
  };
  if (version === null) payload.property_ref = propertyRef;
  else payload.version = version;
  return { errors: {}, payload };
}

export function buildNotePayload(values, version = null) {
  const content = String(values.content || "").trim();
  const errors = {};
  if (!content) errors.note = "Enter note content.";
  if (content.length > 4000) errors.note = "Note content must contain at most 4000 characters.";
  const payload = { case_property_id: values.propertyId || null, content };
  if (version !== null) payload.version = version;
  return { errors, payload: Object.keys(errors).length ? null : payload };
}

export function buildTaskPayload(values, version = null) {
  const title = String(values.title || "").trim();
  const dueDate = String(values.dueDate || "").trim();
  const errors = {};
  if (!title) errors.title = "Enter a task title.";
  if (title.length > 300) errors.title = "Task title must contain at most 300 characters.";
  const parsedDate = new Date(`${dueDate}T00:00:00Z`);
  if (dueDate && (!/^\d{4}-\d{2}-\d{2}$/.test(dueDate) || Number.isNaN(parsedDate.getTime()) || parsedDate.toISOString().slice(0, 10) !== dueDate)) errors.dueDate = "Enter a valid due date.";
  const payload = {
    case_property_id: values.propertyId || null,
    title,
    due_date: dueDate || null,
    completed: Boolean(values.completed),
  };
  if (version !== null) payload.version = version;
  return { errors, payload: Object.keys(errors).length ? null : payload };
}

export function parseRoute(hash) {
  const match = /^#buyer-cases\/([^/]+)$/.exec(hash || "");
  if (!match) return { name: "list" };
  try {
    return { name: "detail", id: decodeURIComponent(match[1]) };
  } catch (error) {
    return { name: "list" };
  }
}

export async function navigateForFollowUp(targetHash, currentHash, setHash, reload) {
  if (targetHash === currentHash) {
    await reload();
    return "reloaded";
  }
  setHash(targetHash);
  return "navigated";
}

export function uiStateForError(error) {
  if (error instanceof ApiProblem && error.status === 409) return "conflict";
  if (error instanceof ApiProblem && error.status === 422) return "invalid";
  return "unavailable";
}

export { escapeHtml } from "./browser/index.js";
