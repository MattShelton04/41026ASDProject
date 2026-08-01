# Shared testkit

Reusable deterministic assertions and fakes for service tests. This package is test
support only; production orchestration must remain in `agent-core` and `ai-mode`.

`ScriptedLLMProvider` returns a finite sequence of structured responses or exceptions,
records every provider request, exposes deterministic health, and fails on unexpected
extra invocations. It lets CI cover schema repair, provider failure, and exact invocation
counts without downloading or running an Ollama model.

The testkit also validates shared Problem Details responses. Add only genuinely reusable,
domain-neutral helpers here; feature fixtures stay in their owning student slice.
