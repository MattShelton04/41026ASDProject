# Student 5 live workflow evidence

Captured on 22 October 2026 using the supported server export:

```text
uv run --all-packages multi-agent-server export e9600341-d1fd-4836-befb-5607f705f797 --out docs/release-2/evidence/multi-agent/student-5/e9600341-d1fd-4836-befb-5607f705f797 --server
```

[Run summary](e9600341-d1fd-4836-befb-5607f705f797/summary.md) and
[typed run](e9600341-d1fd-4836-befb-5607f705f797/run.json) retain the model-generated
Planner, Worker and Reviewer stages, MCP evidence references, correction round and
Derek Song's recorded human decisions: **correct**, then **approve**. The directory
also retains the template, workflow history and coordination audit. This is live
provider/MCP execution against the local demonstration cases, not deterministic
validator output or proof of Azure AI availability.

## Important qualification

The terminal workflow state is **approved**, but the final Reviewer recommendation
was **partial**, with **one high and two medium failed checks**. In particular,
the Worker did not produce the requested three to five proposed next actions,
including after correction. Human approval must not be presented as proof that
the action-plan deliverable or all quality checks passed. The export deliberately
retains these unresolved findings and the evidence limitations.

All five generated files were reviewed for credentials, tokens, private content
and machine-specific paths before retention. They contain the demonstration case
records and assessment actor identity, not production buyer records. No credential
or machine-specific path was found; raw IDs and evidence references are retained
for assessment traceability. Do not index this run export into the guidance corpus.

Commit IDs and GitHub CI evidence remain pending; no commit or push was performed.

## Version 2 action-plan regression

[Version 2 live summary](429fbe07-8dd8-48d0-b565-62d6536c4d9c/summary.md) and its
[typed run](429fbe07-8dd8-48d0-b565-62d6536c4d9c/run.json) were exported with:

```text
uv run --all-packages multi-agent-server export 429fbe07-8dd8-48d0-b565-62d6536c4d9c --out docs/release-2/evidence/multi-agent/student-5/429fbe07-8dd8-48d0-b565-62d6536c4d9c --server
```

The Student 5 template now names the supported Worker `summary` field as the
location for the proposed actions, while keeping per-step findings factual.
No shared agent prompt, schema, model profile or Reviewer rule was changed.

The live model run produced **five numbered imperative actions** containing
**14, 16, 19, 15 and 13 words**, respectively, with no raw UUIDs or tool telemetry.
All four evidence calls used MCP successfully. Planner, Worker and Reviewer used
the configured model provider without deterministic fallback. The Reviewer
explicitly recognised the five grounded actions and reported **no high/critical
failures**; its only failure was the existing medium partial-coverage check.
Its recommendation therefore remains **partial**, not full evidence completeness.

At the first export the run was **awaiting_human**. The retained export was then
refreshed after the user's real terminal decision: **partial**, accepting `case`,
`notes` and `tasks`, leaving `evidence` unaccepted. The state is now
**partially_accepted**. The self-entered actor is literally **Yes**; this is retained
unchanged, not silently relabelled as Derek or treated as authenticated identity.
The note records that research evidence is incomplete and requires verification.
No agent submitted or altered this decision. This is a live model/MCP and human
review trace, not full approval, proof of complete source coverage or Azure verification. Its five files
were reviewed separately before retention: no credentials, credential fields or
machine-specific paths were found; the records are the same demonstration case
used in the earlier run. Retain the v1 export as historical evidence rather than
rewriting it to imply that its missing actions were present.
