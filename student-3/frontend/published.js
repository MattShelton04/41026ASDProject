import { requestJsonResponse } from "./browser/index.js";
const API = "/api/suburb-analytics/v1";

export function crimeValue(series, month) {
  const observed = series.observations.find((item) => item.month === month);
  if (observed) return observed.count;
  return series.observed_months.includes(month) && series.blank_means_observed_zero ? 0 : null;
}

export function populationLabel(items) {
  if (!items.length) return "Population unavailable — no matching imported ABS record.";
  if (items.length !== 1) return "Population match is ambiguous — boundary reconciliation is needed.";
  return `${items[0].usual_resident_population.toLocaleString("en-AU")} usual residents (${items[0].reference_year} Census; SAL ${items[0].sal_code}). Based on Australian Bureau of Statistics data.`;
}

async function request(path, method = "GET") {
  return (await requestJsonResponse(fetch, API + path, { method })).body;
}

function element(tag, text) {
  const node = document.createElement(tag);
  node.textContent = text;
  return node;
}

export function mountPublished(root = document) {
  const select = (id) => root.querySelector(`#published-${id}`);
  let nextOffset = null;
  let searchGeneration = 0;
  let detailGeneration = 0;
  let query = "";
  let activeReleaseKey = null;
  const message = (text) => { select("message").textContent = text; };
  async function sources() {
    const body = await request("/published/sources");
    const active = body.items.filter((item) => item.active);
    select("availability").textContent = active.length
      ? `${active.length} imported datasets available. Updates are checked automatically.`
      : "Published suburb evidence is not available yet. It will appear automatically when approved releases can be imported.";
    const releaseKey = active.map((item) => item.release_id).sort().join(",");
    if (activeReleaseKey !== null && activeReleaseKey !== releaseKey) await search();
    activeReleaseKey = releaseKey;
    const list = element("ul", "");
    for (const item of body.items) {
      const row = element("li", `${item.dataset_id}: ${item.status}${item.active ? " — active in this feature" : ""}; ${item.record_count.toLocaleString("en-AU")} records. ${item.manifest.source_release || ""}. ${(item.manifest.known_limitations || []).join(" ")}`);
      if (item.status === "failed") {
        row.append(element("p", item.error?.message || "Import failed; previous evidence is unchanged."));
        const retry = element("button", "Retry failed import");
        retry.className = "ps-button";
        retry.type = "button";
        retry.onclick = async () => {
          retry.disabled = true;
          try { await request(`/data-imports/${encodeURIComponent(item.consumer_operation_id)}/retry`, "POST"); await sources(); }
          catch (error) { message(error.message); retry.disabled = false; }
        };
        row.append(retry);
      }
      list.append(row);
    }
    select("sources").replaceChildren(body.items.length ? list : element("p", "No releases imported yet. The background worker checks accepted releases every 15 minutes."));
  }
  async function detail(locality) {
    const generation = ++detailGeneration;
    select("context").replaceChildren(element("p", "Loading evidence…"));
    const body = await request(`/published/context?locality=${encodeURIComponent(locality)}`);
    if (generation !== detailGeneration) return;
    const section = element("section", "");
    section.append(element("h3", locality), element("p", populationLabel(body.population)));
    section.append(element("h4", "Government schools"));
    const schools = element("ul", "");
    body.schools.forEach((school) => schools.append(element("li", `${school.school_name} — ${school.school_type}; ${school.operational_status}. ${school.latitude}, ${school.longitude}.`)));
    section.append(body.schools.length ? schools : element("p", "School evidence unavailable for this locality."));
    section.append(element("h4", "Recorded crime — latest 12 source months by category"));
    if (!body.crime.length) section.append(element("p", "Suburb crime evidence unavailable. Postcode records are not translated into suburbs."));
    for (const series of body.crime) {
      const disclosure = element("details", "");
      disclosure.append(element("summary", `${series.offence_label || series.source_category_key}${series.subcategory_label ? ` / ${series.subcategory_label}` : ""} — ${series.first_month} to ${series.last_month}`));
      const table = element("table", "");
      table.append(element("caption", "Recorded counts; missing is not zero. No crime rates or safety ranking."));
      const header = element("tr", "");
      header.append(element("th", "Month"), element("th", "Recorded count"));
      table.append(header);
      for (const month of series.observed_months.slice(-12)) {
        const value = crimeValue(series, month);
        const row = element("tr", "");
        row.append(element("td", month.slice(0, 7)), element("td", value === null ? "Unavailable" : value === 0 ? "0 — recorded zero" : String(value)));
        table.append(row);
      }
      disclosure.append(table);
      section.append(disclosure);
    }
    section.append(element("h4", "Sources and limitations"));
    body.sources.forEach((source) => section.append(element("p", `${source.publisher || source.source}: ${source.source_release}. Release ${source.release_id}. Retrieved ${source.source_retrieved_at || "date unavailable"}. Licence: ${source.source_licence || "see producer"}. ${(source.known_limitations || []).join(" ")}`)));
    body.limitations.forEach((text) => section.append(element("p", text)));
    select("context").replaceChildren(section);
  }
  async function search(append = false) {
    const generation = ++searchGeneration;
    const body = await request(`/published/suburbs?q=${encodeURIComponent(query)}&offset=${append ? nextOffset : 0}`);
    if (generation !== searchGeneration) return;
    if (!append) select("localities").replaceChildren();
    for (const locality of body.items) {
      const button = element("button", locality);
      button.className = "ps-button";
      button.type = "button";
      button.onclick = () => detail(locality).catch((error) => message(error.message));
      select("localities").append(button);
    }
    if (!append && !body.items.length) select("localities").append(element("p", "No matching imported localities."));
    nextOffset = body.next_offset;
    select("more").hidden = nextOffset === null;
  }
  select("search").onsubmit = (event) => { event.preventDefault(); query = select("query").value; search().catch((error) => message(error.message)); };
  select("more").onclick = () => search(true).catch((error) => message(error.message));
  select("refresh").onclick = () => Promise.all([sources(), search()]).catch((error) => message(error.message));
  root.querySelectorAll("[data-sync]").forEach((button) => {
    button.onclick = async () => {
      button.disabled = true;
      try {
        const operation = await request(`/data-imports/${button.dataset.sync}/sync`, "POST");
        message(`Import ${operation.consumer_operation_id}: ${operation.status}. Refresh status to check progress; large crime releases can take several minutes.`);
        await sources();
      } catch (error) { message(error.message); }
      finally { button.disabled = false; }
    };
  });
  Promise.all([sources(), search()]).catch((error) => message(error.message));
  const refreshTimer = setInterval(() => {
    if (!document.hidden) sources().catch((error) => message(error.message));
  }, 30000);
  addEventListener("pagehide", () => clearInterval(refreshTimer), {once: true});
}

if (typeof document !== "undefined" && document.querySelector("#published-sources")) mountPublished();
