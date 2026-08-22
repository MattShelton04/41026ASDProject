# ADR-019: Continue safely after one recoverable AI evidence failure

- Status: accepted
- Date: 2026-08-22
- Owners: shared platform team
- Scope: domain-neutral agent orchestration and Feature 1 diagnosis presentation

## Context

The Release 0 loop validated model and tool data strictly, but its failure boundary was too
coarse for a useful diagnosis workflow. A model-selected tool name or argument that missed the
registered schema failed planning immediately. A read-only tool returning one structured
non-retryable error failed the entire run before Observe or Adapt could see it. Replanning did not
receive prior failed-call context, and adaptation did not receive the original objective. These
behaviours were safe, but they made transient or correctable evidence problems look terminal and
could produce an incomplete final report.

Continuing every failure would be unsafe. Write outcomes can be uncertain, provider errors can
consume unbounded cost, and repeatedly issuing an identical rejected call cannot make progress.

## Decision

1. `default.v4` makes each explicit objective requirement an observable success criterion, passes
   the original objective to adaptation, and passes a bounded projection of prior tool attempts to
   replanning. The final result is a concise evidence-backed brief containing findings, a specific
   reviewed next step, a safety note, and exact evidence references.
2. Model JSON remains schema constrained. Agent-core may make zero, one, or two configured
   schema-informed repairs. The same repair loop also validates the selected allowlisted tool name
   and its argument schema before any effect executes. Feature 1 configures two repairs.
3. The first unsuccessful read-only tool result is persisted as a failed ACT step, then moves
   through Observe and Adapt. The adapter may continue another planned read, replan to a different
   allowlisted call, complete only when the objective is still fully supported, or fail when no
   safe evidence path remains.
4. A second failure with the same tool name, exact arguments, and error code terminates with
   `repeated_tool_failure`. Existing iteration, tool-call, and time budgets remain additional hard
   stops.
5. Write uncertainty, denied/protected actions, result identity mismatches, provider repair
   exhaustion, and hard limit failures retain their fail-closed or human-review behaviour.
6. One `model_response_incomplete` result is retried with an explicit request for the complete JSON
   inside the original deadline. A second incomplete response is terminal. The v4 adapter reserves
   a larger output budget for the structured recovery brief.

## Consequences

- One bad read no longer erases the value of the rest of a diagnosis plan.
- Failed attempts remain explicit in the durable trace; the UI may describe a later success as a
  recovery but never rewrites the failed step as successful.
- Replanning can avoid a known rejected call without receiving unbounded prior tool content.
- Corrective model calls add bounded latency and token cost. Feature 1's six-iteration,
  twelve-tool-call, five-minute limits cap that exposure.
- The policy is domain neutral. Feature-specific recovery language and presentation remain owned
  by Feature 1.

## Alternatives considered

- **Fail on the first tool error:** safe but prevents the existing Observe/Adapt loop from doing
  useful recovery work.
- **Retry every tool automatically:** rejected because deterministic retries cannot choose a
  semantically different evidence path and may repeat invalid requests.
- **Let the model retry without a duplicate guard:** rejected because it can loop and spend the
  entire run budget on one identical failure.
- **Continue write failures like reads:** rejected because an interrupted write can have an
  uncertain external effect and must remain review-controlled.
