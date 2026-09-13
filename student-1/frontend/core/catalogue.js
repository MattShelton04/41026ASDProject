const FALLBACK_GROUP = {
  key: "other-datasets",
  label: "Other datasets",
  description: "Additional dataset definitions managed in this environment.",
};

export function catalogueIndex(payload) {
  const datasets = Array.isArray(payload?.datasets) ? payload.datasets : [];
  return new Map(datasets.map((item) => [item.source_key, item]));
}

export function presentationFor(index, key) {
  return index.get(String(key || "")) || null;
}

export function presentationForJob(payload, job) {
  const datasets = Array.isArray(payload?.datasets) ? payload.datasets : [];
  return datasets.find((item) => item.job_profile === job?.profile_key)
    || datasets.find((item) => item.source_key === job?.dataset_id)
    || null;
}

export function presentedName(presentation, savedName) {
  const name = String(savedName || "").trim();
  const defaults = Array.isArray(presentation?.default_names) ? presentation.default_names : [];
  if (presentation && (!name || name === presentation.display_name || defaults.includes(name))) {
    return presentation.display_name;
  }
  return name || presentation?.display_name || "Unnamed dataset";
}

export function groupCatalogueItems(items, payload, keyForItem) {
  const groups = Array.isArray(payload?.groups) ? payload.groups : [];
  const index = catalogueIndex(payload);
  const buckets = new Map(groups.map((group) => [group.key, []]));
  const other = [];
  for (const item of items) {
    const presentation = presentationFor(index, keyForItem(item));
    const bucket = presentation && buckets.get(presentation.group_key);
    (bucket || other).push({ item, presentation });
  }
  const result = groups
    .filter((group) => buckets.get(group.key)?.length)
    .map((group) => ({ ...group, items: buckets.get(group.key) }));
  if (other.length) result.push({ ...FALLBACK_GROUP, items: other });
  return result;
}

export function groupJobItems(items, payload) {
  const groups = Array.isArray(payload?.groups) ? payload.groups : [];
  const buckets = new Map(groups.map((group) => [group.key, []]));
  const other = [];
  for (const item of items) {
    const presentation = presentationForJob(payload, item);
    const bucket = presentation && buckets.get(presentation.group_key);
    (bucket || other).push({ item, presentation });
  }
  const result = groups
    .filter((group) => buckets.get(group.key)?.length)
    .map((group) => ({ ...group, items: buckets.get(group.key) }));
  if (other.length) result.push({ ...FALLBACK_GROUP, items: other });
  return result;
}
