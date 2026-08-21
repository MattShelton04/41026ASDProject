export const properties = [
  {
    ref: "PS-NSW-00021489",
    address: "12 Example Street, Parramatta NSW 2150",
    short: "12 Example Street",
    locality: "Parramatta",
    type: "Detached house",
    match: "Verified address",
    coordinates: "-33.8151, 151.0011",
    sources: 8,
    freshness: "Updated 12 Aug 2026",
    askingPrice: "$1,250,000",
    lat: 44,
    top: 43,
  },
  {
    ref: "PS-NSW-00021490",
    address: "18 Example Street, Parramatta NSW 2150",
    short: "18 Example Street",
    locality: "Parramatta",
    type: "Detached house",
    match: "Verified address",
    coordinates: "-33.8142, 151.0024",
    sources: 7,
    freshness: "Updated 12 Aug 2026",
    askingPrice: "$1,180,000",
    lat: 60,
    top: 34,
  },
  {
    ref: "PS-NSW-00021712",
    address: "Unit 3, 9 Sample Avenue, Parramatta NSW 2150",
    short: "Unit 3, 9 Sample Avenue",
    locality: "Parramatta",
    type: "Apartment",
    match: "High-confidence match",
    coordinates: "-33.8176, 151.0040",
    sources: 6,
    freshness: "Updated 9 Aug 2026",
    askingPrice: "$790,000",
    lat: 70,
    top: 60,
  },
  {
    ref: "PS-NSW-00031182",
    address: "24 Park Road, North Parramatta NSW 2151",
    short: "24 Park Road",
    locality: "North Parramatta",
    type: "Townhouse",
    match: "Verified address",
    coordinates: "-33.7998, 151.0051",
    sources: 7,
    freshness: "Updated 11 Aug 2026",
    askingPrice: "$1,040,000",
    lat: 30,
    top: 21,
  },
];

export const sources = [
  { id: "SRC-GNAF", name: "G-NAF Open NSW", publisher: "Geoscape Australia", domain: "Address registry", cadence: "Quarterly", status: "active", freshness: "Current · May 2026", licence: "Licence controlled", adapter: "gnaf-nsw", records: "4.18m", initials: "GA" },
  { id: "SRC-PSI", name: "NSW property sales information", publisher: "NSW Valuer General", domain: "Recorded sales", cadence: "Weekly / annual", status: "active", freshness: "Current · 8 Aug 2026", licence: "Bounded derived release", adapter: "psi-sales", records: "18.6m", initials: "VG" },
  { id: "SRC-BOCSAR", name: "BOCSAR recorded crime data", publisher: "NSW BOCSAR", domain: "Crime series", cadence: "Source release", status: "active", freshness: "Candidate · Jun 2026", licence: "NSW open data", adapter: "bocsar-bulk", records: "1.26m", initials: "BC" },
  { id: "SRC-SCHOOLS", name: "NSW government schools", publisher: "NSW Department of Education", domain: "School locations", cadence: "Source release", status: "active", freshness: "Current · Jul 2026", licence: "NSW open data", adapter: "schools-master", records: "2,210", initials: "ED" },
  { id: "SRC-PLAN", name: "Planning controls — showcase", publisher: "Selected NSW councils", domain: "Planning", cadence: "Manual snapshot", status: "draft", freshness: "Partial · May 2026", licence: "Metadata only", adapter: "arcgis-planning", records: "420", initials: "PL" },
  { id: "SRC-FLOOD", name: "Flood study coverage", publisher: "Selected NSW councils", domain: "Environmental", cadence: "Manual snapshot", status: "active", freshness: "Current · Feb 2026", licence: "Metadata only", adapter: "spatial-evidence", records: "84", initials: "FL" },
  { id: "SRC-BUSH", name: "Bush fire prone land", publisher: "NSW Rural Fire Service", domain: "Environmental", cadence: "Source release", status: "active", freshness: "Current · Mar 2026", licence: "Metadata only", adapter: "spatial-evidence", records: "128", initials: "RF" },
  { id: "SRC-STRATA", name: "Strata scheme sample", publisher: "NSW Fair Trading", domain: "Building", cadence: "Manual snapshot", status: "draft", freshness: "Partial · Jan 2026", licence: "Metadata only", adapter: "manual-versioned", records: "36", initials: "ST" },
];

export const jobs = [
  { id: "JOB-GNAF-NSW", name: "G-NAF NSW full snapshot", dataset: "property-registry", source: "G-NAF Open NSW", strategy: "Full snapshot", mode: "Full refresh", target: "Feature 1", status: "active", next: "On demand", last: "Succeeded 12 Aug", limits: "1.8 GB · 5m rows" },
  { id: "JOB-PSI-2026", name: "PSI 2026 yearly partition", dataset: "sale-observations", source: "NSW property sales information", strategy: "Partition replacement", mode: "Full refresh", target: "Feature 2", status: "active", next: "Weekly", last: "Succeeded 10 Aug", limits: "850 MB · 1m rows" },
  { id: "JOB-CRIME", name: "BOCSAR suburb monthly series", dataset: "crime-series", source: "BOCSAR recorded crime data", strategy: "Full snapshot", mode: "Reprocess cached", target: "Feature 3", status: "active", next: "After review", last: "Failed 12 Aug", limits: "200 MB · 2m rows" },
  { id: "JOB-SCHOOLS", name: "Government school master", dataset: "government-school-point", source: "NSW government schools", strategy: "Full snapshot", mode: "Full refresh", target: "Feature 3", status: "active", next: "On source release", last: "Succeeded 9 Aug", limits: "20 MB · 5k rows" },
  { id: "JOB-FLOOD", name: "Parramatta flood evidence", dataset: "flood-observations", source: "Flood study coverage", strategy: "Versioned manual import", mode: "Reprocess cached", target: "Feature 4", status: "draft", next: "Not scheduled", last: "Validated 7 Aug", limits: "60 MB · 20k rows" },
];

export const runs = [
  { id: "RUN-0826-1042", job: "BOCSAR suburb monthly series", mode: "Reprocess cached", status: "failed", stage: "Quality validation", started: "12 Aug · 10:42", elapsed: "1m 48s", rows: "96,840", request: "req_b7c24f", detail: "Required month continuity check failed" },
  { id: "RUN-0826-0925", job: "G-NAF NSW full snapshot", mode: "Full refresh", status: "success", stage: "Complete", started: "12 Aug · 09:25", elapsed: "14m 12s", rows: "4,184,293", request: "req_123a89", detail: "Accepted release 2026.08.12" },
  { id: "RUN-0826-0811", job: "Government school master", mode: "Full refresh", status: "success", stage: "Complete", started: "9 Aug · 08:11", elapsed: "38s", rows: "2,210", request: "req_89f110", detail: "Accepted release 2026.08.09" },
  { id: "RUN-0826-0714", job: "PSI 2026 yearly partition", mode: "Full refresh", status: "success", stage: "Complete", started: "8 Aug · 07:14", elapsed: "6m 03s", rows: "318,420", request: "req_35f911", detail: "Published to Feature 2" },
  { id: "RUN-0826-0617", job: "Parramatta flood evidence", mode: "Reprocess cached", status: "warning", stage: "Awaiting review", started: "7 Aug · 06:17", elapsed: "1m 09s", rows: "420", request: "req_15a9f2", detail: "Two coverage warnings require acknowledgement" },
  { id: "RUN-0826-0532", job: "G-NAF NSW full snapshot", mode: "Full refresh", status: "failed", stage: "Acquire", started: "5 Aug · 05:32", elapsed: "3m 24s", rows: "0", request: "req_89c288", detail: "Source archive checksum changed during transfer" },
];

export const releases = [
  { id: "REL-CRIME-2026-06-C", dataset: "crime-series", version: "2026.06-candidate.2", target: "Feature 3", status: "review", records: "96,840", coverage: "11 / 12 months", checksum: "8ae1…c410", created: "12 Aug 2026", note: "Missing November 2025 month" },
  { id: "REL-CRIME-2026-05", dataset: "crime-series", version: "2026.05.1", target: "Feature 3", status: "accepted", records: "94,170", coverage: "12 / 12 months", checksum: "410c…f6a2", created: "22 Jul 2026", note: "Current accepted release" },
  { id: "REL-GNAF-2026-08", dataset: "property-registry", version: "2026.08.12", target: "Feature 1", status: "accepted", records: "4,184,293", coverage: "NSW statewide", checksum: "90de…6c19", created: "12 Aug 2026", note: "Current accepted release" },
  { id: "REL-SCHOOLS-2026-07", dataset: "government-school-point", version: "2026.07.1", target: "Feature 3", status: "accepted", records: "2,210", coverage: "NSW statewide", checksum: "278a…091e", created: "9 Aug 2026", note: "Current accepted release" },
  { id: "REL-PSI-2026", dataset: "sale-observations", version: "2026.08.08", target: "Feature 2", status: "accepted", records: "318,420", coverage: "2026 partition", checksum: "115f…8d82", created: "8 Aug 2026", note: "Published to Feature 2" },
  { id: "REL-FLOOD-PARRA", dataset: "flood-observations", version: "2026.02.1", target: "Feature 4", status: "draft", records: "420", coverage: "Parramatta LGA partial", checksum: "c098…12d0", created: "7 Aug 2026", note: "Two coverage warnings" },
];

export const qualityRules = [
  { rule: "crime.month_continuity", dimension: "Completeness", severity: "Blocking", status: "failed", observed: "11 months", expected: "12 months", sample: "2025-11 missing", release: "2026.06-candidate.2" },
  { rule: "crime.category_coverage", dimension: "Coverage", severity: "Warning", status: "warning", observed: "18 categories", expected: "≥ 18", sample: "No change", release: "2026.06-candidate.2" },
  { rule: "crime.locality_coverage", dimension: "Coverage", severity: "Info", status: "success", observed: "34 suburbs", expected: "34 suburbs", sample: "Complete", release: "2026.06-candidate.2" },
  { rule: "crime.zero_missing_semantics", dimension: "Validity", severity: "Blocking", status: "success", observed: "0 invalid", expected: "0 invalid", sample: "Pass", release: "2026.06-candidate.2" },
  { rule: "crime.row_drift", dimension: "Drift", severity: "Warning", status: "warning", observed: "+2.8%", expected: "± 8%", sample: "Within band", release: "2026.06-candidate.2" },
  { rule: "release.checksum", dimension: "Reproducibility", severity: "Blocking", status: "success", observed: "Verified", expected: "Verified", sample: "8ae1…c410", release: "2026.06-candidate.2" },
];

export const artifacts = [
  { key: "bocsar/2026-06/source.zip", kind: "Source archive", size: "82.4 MB", hash: "746a…9a10", retention: "Candidate · 30 days", run: "RUN-0826-1042", status: "accepted" },
  { key: "bocsar/2026-06/combined.csv", kind: "Staged extract", size: "41.8 MB", hash: "b921…84ca", retention: "Candidate · 30 days", run: "RUN-0826-1042", status: "accepted" },
  { key: "bocsar/2026-06/normalised.parquet", kind: "Normalised data", size: "15.2 MB", hash: "9ee2…c181", retention: "Candidate · 30 days", run: "RUN-0826-1042", status: "accepted" },
  { key: "bocsar/2026-06/feature-3-release.jsonl", kind: "Release export", size: "9.8 MB", hash: "8ae1…c410", retention: "Release evidence", run: "RUN-0826-1042", status: "warning" },
  { key: "gnaf/2026-05/property-registry.parquet", kind: "Accepted release", size: "1.34 GB", hash: "90de…6c19", retention: "Accepted release", run: "RUN-0826-0925", status: "accepted" },
];

export const coverage = [
  { dataset: "Property identity", parramatta: "confirmed", newtown: "confirmed", mosman: "confirmed", wollongong: "confirmed", owner: "Feature 1", fresh: "12 Aug" },
  { dataset: "Recorded sales", parramatta: "confirmed", newtown: "confirmed", mosman: "confirmed", wollongong: "partial", owner: "Feature 2", fresh: "8 Aug" },
  { dataset: "Crime series", parramatta: "confirmed", newtown: "confirmed", mosman: "confirmed", wollongong: "partial", owner: "Feature 3", fresh: "22 Jul" },
  { dataset: "Government schools", parramatta: "confirmed", newtown: "confirmed", mosman: "confirmed", wollongong: "confirmed", owner: "Feature 3", fresh: "9 Aug" },
  { dataset: "Planning controls", parramatta: "partial", newtown: "partial", mosman: "unknown", wollongong: "unknown", owner: "Feature 4", fresh: "May" },
  { dataset: "Flood evidence", parramatta: "partial", newtown: "unknown", mosman: "unknown", wollongong: "partial", owner: "Feature 4", fresh: "Feb" },
  { dataset: "Bush fire prone land", parramatta: "confirmed", newtown: "confirmed", mosman: "confirmed", wollongong: "confirmed", owner: "Feature 4", fresh: "Mar" },
  { dataset: "Strata / building", parramatta: "partial", newtown: "partial", mosman: "partial", wollongong: "unknown", owner: "Feature 4", fresh: "Jan" },
];

export const saleHistory = [
  { date: "May 2026", price: "$1,210,000", class: "Contract sale", match: "Exact address", source: "PSI 2026" },
  { date: "Sep 2018", price: "$845,000", class: "Contract sale", match: "Exact address", source: "PSI 2018" },
  { date: "Nov 2011", price: "$592,000", class: "Contract sale", match: "High confidence", source: "PSI 2011" },
  { date: "Mar 2004", price: "$372,500", class: "Contract sale", match: "High confidence", source: "PSI 2004" },
];

export const comparables = [
  { address: "18 Example Street", distance: "140 m", sold: "Jul 2026", price: "$1,180,000", land: "518 m²", beds: "3", inclusion: "Included", reason: "Same street and property type" },
  { address: "32 River Road", distance: "420 m", sold: "Jun 2026", price: "$1,265,000", land: "556 m²", beds: "4", inclusion: "Included", reason: "Nearby detached house" },
  { address: "6 Park Avenue", distance: "780 m", sold: "Apr 2026", price: "$1,095,000", land: "446 m²", beds: "3", inclusion: "Included", reason: "Same suburb; smaller site" },
  { address: "Unit 8, 4 Sample Road", distance: "310 m", sold: "Jul 2026", price: "$780,000", land: "—", beds: "2", inclusion: "Excluded", reason: "Different property class" },
  { address: "44 Example Street", distance: "240 m", sold: "Oct 2024", price: "$950,000", land: "501 m²", beds: "3", inclusion: "Excluded", reason: "Outside selected 12-month window" },
];

export const crimeCategories = [
  { name: "Steal from motor vehicle", parramatta: 188, peer: 146, change: "+4.2%", status: "Rate available" },
  { name: "Malicious damage", parramatta: 154, peer: 171, change: "−3.8%", status: "Rate available" },
  { name: "Non-domestic assault", parramatta: 91, peer: 72, change: "+1.1%", status: "Count only" },
  { name: "Break and enter dwelling", parramatta: 54, peer: 61, change: "−8.4%", status: "Rate available" },
];

export const planningFacts = [
  { label: "Land zoning", value: "R2 — Low Density Residential", source: "Parramatta LEP showcase", state: "confirmed" },
  { label: "Heritage", value: "No mapped item at property point", source: "Heritage layer · May 2026", state: "confirmed" },
  { label: "Floor space ratio", value: "0.5:1", source: "Parramatta LEP showcase", state: "confirmed" },
  { label: "Height of buildings", value: "9 m", source: "Parramatta LEP showcase", state: "confirmed" },
  { label: "Flood evidence", value: "Mapped study coverage; property point outside modelled extent", source: "Council flood study · Feb 2026", state: "partial" },
  { label: "Bush fire prone land", value: "No intersection at property point", source: "NSW RFS · Mar 2026", state: "confirmed" },
  { label: "Strata scheme", value: "Not applicable to matched detached-house identity", source: "Property registry", state: "confirmed" },
  { label: "Building / tribunal records", value: "No supported match in current bounded corpus", source: "Feature 4 corpus", state: "unknown" },
];

export const buyerPriorities = [
  { label: "Primary schools", weight: "High", evidence: "3 nearby government schools", state: "confirmed" },
  { label: "Commute to Sydney CBD", weight: "High", evidence: "User-supplied requirement; journey time not assessed", state: "partial" },
  { label: "Flood evidence", weight: "High", evidence: "Partial study coverage; verify with council / inspector", state: "partial" },
  { label: "Quiet residential setting", weight: "Medium", evidence: "Not objectively assessed", state: "unknown" },
  { label: "Budget under $1.30m", weight: "High", evidence: "Asking price entered as $1.25m", state: "confirmed" },
];

export const followups = [
  { id: "TASK-01", title: "Confirm flood-study interpretation", stakeholder: "Council / conveyancer", due: "Before contract review", status: "To verify", evidence: "Flood evidence · partial" },
  { id: "TASK-02", title: "Request building and pest inspection", stakeholder: "Inspector", due: "Within 5 days", status: "Planned", evidence: "User checklist" },
  { id: "TASK-03", title: "Ask whether recent works were approved", stakeholder: "Selling agent", due: "Next inspection", status: "Draft", evidence: "No supported building records" },
  { id: "TASK-04", title: "Confirm school enrolment eligibility", stakeholder: "School authority", due: "Before offer", status: "To verify", evidence: "Nearby only; no catchment claim" },
  { id: "TASK-05", title: "Review contract and title documents", stakeholder: "Conveyancer", due: "Before exchange", status: "In progress", evidence: "Outside PropertyScope corpus" },
  { id: "TASK-06", title: "Record finance approval conditions", stakeholder: "Lender / broker", due: "This week", status: "Complete", evidence: "User supplied" },
];

export const agentRuns = [
  { id: "AGT-2041", feature: "Feature 1", objective: "Diagnose failed crime release and propose the safest recovery", status: "review", phase: "Human review", tools: 5, model: "Qwen 2.5 3B", started: "12 Aug · 10:47", elapsed: "38s" },
  { id: "AGT-2038", feature: "Feature 5", objective: "Build a purchase dossier for 12 Example Street", status: "success", phase: "Complete", tools: 11, model: "Qwen 2.5 3B", started: "12 Aug · 09:52", elapsed: "54s" },
  { id: "AGT-2034", feature: "Feature 3", objective: "Explain selected crime trends for Parramatta and Newtown", status: "success", phase: "Complete", tools: 4, model: "Qwen 2.5 3B", started: "11 Aug · 15:17", elapsed: "21s" },
  { id: "AGT-2029", feature: "Feature 4", objective: "Draft a bounded due-diligence question pack", status: "failed", phase: "Observe", tools: 3, model: "Qwen 2.5 3B", started: "11 Aug · 11:07", elapsed: "29s" },
];

export const groundedCitations = [
  { id: "EVD-REL-CRIME-61", type: "Structured evidence", title: "crime.month_continuity quality result", detail: "Observed 11 months; expected 12; November 2025 missing", source: "Feature 1 MCP tool" },
  { id: "DOC-RUNBOOK-4#p3", type: "Document passage", title: "BOCSAR release recovery runbook", detail: "A blocking continuity failure must retain the prior accepted release and use cached reprocess after source verification.", source: "Feature 1 RAG corpus" },
  { id: "EVD-REL-CRIME-55", type: "Structured evidence", title: "Accepted predecessor 2026.05.1", detail: "12 months, 94,170 records, currently imported by Feature 3", source: "Feature 1 MCP tool" },
];

export const roadmap = [
  { release: "Release 0", label: "Foundations", status: "Current build", date: "30 Aug 2026", capabilities: ["Five microservice slices", "AI-mode + OpenAI", "Plan → Act → Observe → Adapt", "Shared shell and design system", "Docker Compose + student CI"] },
  { release: "Release 1", label: "Grounded intelligence", status: "Designed", date: "27 Sep 2026", capabilities: ["MCP resources and tools", "RAG document corpus", "Cited grounded answers", "Prompt-injection controls", "MCP/RAG failure states"] },
  { release: "Release 2", label: "Multi-agent + cloud", status: "Designed", date: "18 Oct 2026", capabilities: ["Planner / Worker / Reviewer", "Human review queue", "Pre/post AI-assisted tests", "Azure Container Apps", "Cloud mode with MCP/RAG/multi-agent disabled"] },
];
