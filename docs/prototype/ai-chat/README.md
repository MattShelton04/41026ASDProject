# AI chat interface prototypes

These dependency-free HTML prototypes support review of the conversational-assistant proposal.
They are simulated interfaces and do not call Feature 1 or AI-mode.

## View

Open either HTML file directly, or serve this directory:

```text
uv run python -m http.server 5400 --bind 127.0.0.1 --directory docs/prototype/ai-chat
```

Then visit:

- <http://127.0.0.1:5400/feature-1-contextual-chat.html>
- <http://127.0.0.1:5400/shared-assistant.html>

## What each prototype tests

### Feature 1 contextual assistant

This is the recommended first product increment. It keeps PropertyScope navigation, makes the
current release/property context explicit, maps every user message to one AI-mode run, and reuses
the existing expandable evidence/activity pattern.

Use the three example buttons to review:

- a successful candidate-readiness answer;
- an ingestion-failure explanation with a recovery recommendation; and
- property search followed by exact property inspection.

### Shared assistant

This is a later feasibility concept, not the recommended first build. It makes the selected feature
scope and available tool groups visible. The examples distinguish platform capability/help answers
from Feature 1 data questions and show how unavailable features should fail safely.

## Audit checklist

- Is the difference between implemented **Data review** and proposed **Assistant** clear?
- Is the current context obvious before sending a message?
- Does each answer clearly identify its durable run and sources?
- Is phase/tool evidence useful without exposing private model reasoning?
- Can a user distinguish complete, failed, unavailable and review-required outcomes?
- Are protected actions visibly separate from informational answers?
- Is the shared-assistant scope understandable, or does it add avoidable complexity?
- At narrow viewport widths, can the user still read messages and reach the composer?
- Can all example controls, disclosures and the composer be used with a keyboard?

The associated architecture and audit record is
[`../../architecture/feature-1-conversational-assistant-plan.md`](../../architecture/feature-1-conversational-assistant-plan.md).
