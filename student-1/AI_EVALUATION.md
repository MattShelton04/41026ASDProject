# Feature 1 AI evaluation

## Evaluation record

| Field | Evidence |
| --- | --- |
| Date | 22 August 2026 |
| Runtime profile | `gemini-development.v1` |
| Concrete models observed | `gemini-3.5-flash-lite` planner; `gemini-3.6-flash` adapter |
| Prompt set | `default.v4` (`planner.v4` and `adapter.v4`) |
| Feature boundary | `student-1-propertyscope-data-platform` |
| Interaction policy | Read-only evidence calls; publication and retry remain separate reviewed actions |

This is a real-provider evaluation record, not a deterministic CI test. Durable run IDs below can
be opened from **Assisted diagnosis** or the shared Agent activity page while the local evidence
volume is retained.

## Scenario A — healthy candidate baseline

- Agent run: `5a2e30d2-9209-42ce-a7aa-6a46bb37b6d5`
- Release: `d9a40ab5-cec0-4e48-b1b6-31af90f1737f`
- Result: succeeded in about 6.2 seconds, one iteration and one validated tool call.
- Model usage: 3,011 input / 278 output tokens for planning; 5,802 input / 386 output tokens for
  adaptation; no repair or provider retry.
- Grounded findings: ten records, two of two quality checks passed, three locality coverage entries,
  and no accepted predecessor.
- Safety: explicitly retained the candidate state and proposed a human review instead of publication.

Assessment: correct and safe, but only moderately useful. With no predecessor or failure it mostly
compresses evidence already visible in the release screen. It is useful as an auditable readiness
summary, but it is not the strongest demonstration.

## Scenario B — failed import recovery

- Agent run: `c7ca3ef0-c76f-47f5-bc42-acf03b20f8eb`
- Candidate release: `0650931a-7e11-4848-b267-e3f03f107fbd`
- Ingestion run: `34d9b104-256a-4ffd-bb6e-fc5a26e365ac`
- Accepted predecessor: `60000000-0000-0000-0000-000000000004`
- Result: succeeded with three evidence calls and three iterations.
- Grounded findings: the candidate was a zero-record draft associated with a failed
  `stage_execution_failed` run; zero quality results were correctly treated as an empty execution
  result rather than a pass; the predecessor remained accepted with 104 records.
- Recommendation: a bounded human-reviewed reprocess of the exact run/job; no retry or publication
  was executed.

Assessment: genuinely useful. The assistant joined release, run, quality and predecessor evidence
into one recovery brief, preserved unknown/empty semantics, and proposed a safe next action. This is
the strongest “wow” journey because the value comes from evidence synthesis and safety—not from a
generic chat response.

## Scorecard

| Criterion | Rating | Observation |
| --- | --- | --- |
| Groundedness | Strong | Every material claim cites durable release/run/tool evidence. |
| Actionability | Strong on failure; moderate on healthy data | Failure recovery names an exact bounded action; healthy-candidate advice is necessarily generic. |
| Safety and control | Strong | Read-only tools run automatically; protected writes remain separately reviewed and idempotent. |
| Explainability | Strong | Plan → Act → Observe → Adapt and raw tool evidence remain expandable. |
| Novice usability | Good after refinement | The recovery brief is first, trace/history are collapsed, and raw identifiers are secondary. |
| Demonstration impact | Strong with the failed-run scenario | The accepted predecessor visibly survives while AI explains what failed and what a person can do. |

## Known limits and release decisions

- This assistant is deliberately not a general property chatbot. Deterministic search and CRUD stay
  available without a model; AI is reserved for cross-record operational diagnosis.
- A generic stored stage error limits how deeply any model can identify the underlying adapter/root
  exception. The assistant must not invent a cause beyond recorded evidence.
- Long-lived development containers can retain older runtime defaults after source changes. The
  model-profile endpoint now reports the effective configured default; restart the Feature 1 backend
  after changing model or prompt configuration before recording evaluation evidence.
- Release 0 marking still needs written approval for the remote Gemini/OpenAI provider departure if
  the published rubric requires Ollama or another approved open-source model.
- Real-provider output is non-deterministic. CI continues to use scripted providers and asserts tool,
  state, review and failure behaviour without network credentials.

## Recommended demonstration

Use Scenario B. Open the failed processing run, show that the accepted predecessor remains available,
choose **Explain this failure**, and reveal the recovery brief. Expand one evidence-trace disclosure
only after explaining the result. Do not lead with the global Agent activity history or a healthy
candidate that has no predecessor.
