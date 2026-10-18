# Cloud AI bonus-tier probe

- Site: https://propertyscope-nsw-g20.newzealandnorth.cloudapp.azure.com
- Commit: 817ef779771637629bbfe928c975d640b35aa797
- Started: 2026-10-18T10:53:59.136904+00:00; finished: 2026-10-18T10:54:45.859019+00:00
- Result: **PASS** (4/4 tiers)

| Tier | What was demonstrated | Result | Detail |
|---|---|---|---|
| B1 | AI-mode interaction through the app | PASS | run 387591f0-be44-4e88-8808-404f32cde8b9 succeeded |
| B2 | MCP tool call (data.releases.v1) | PASS | run 387591f0-be44-4e88-8808-404f32cde8b9 called data.releases.v1 over MCP |
| B3 | grounded RAG answer (operator-guidance) | PASS | run 56c85266-6cc9-4421-9f49-61794f55e7b3: 2 citation(s), grounding ready, confidence moderate |
| B4 | Planner -> Worker -> Reviewer workflow (Feature 1 release review) | PASS | run 2058658b-8c85-44ee-bebc-cfc0cd8ab8b8 awaiting_human on nsw-suburb-boundaries release; recommendation correct |

## Preflight

```json
{
  "ai_tier_marker": 204,
  "ai_mode_health": 200,
  "services": {
    "mcp": {
      "enabled": true,
      "status": "ready"
    },
    "rag": {
      "enabled": true,
      "status": "ready"
    },
    "multi-agent": {
      "enabled": true,
      "status": "ready"
    }
  },
  "grounding_feature": true
}
```

## B1 evidence

```json
{
  "answer_characters": 196,
  "model_profile": "remote-standard.v1",
  "models": [
    {
      "model": "gpt-5.6-luna",
      "provider": "openai"
    },
    {
      "model": "gpt-5.6-terra",
      "provider": "openai"
    }
  ],
  "route": "/api/data-platform/v1/assistant/turns",
  "run_id": "387591f0-be44-4e88-8808-404f32cde8b9",
  "shared_run_matches": true,
  "status": "succeeded"
}
```

## B2 evidence

```json
{
  "citation_count": 1,
  "citations": [
    {
      "chunk_id": "40add3c8a7c1f5dde38044384535d30998432fcd038e0429b549887d584ab8e6",
      "citation_id": "cite-26e8b9f08731733a430548ecdd8e907faf891acc0bc8dccb0de49e774b58ce20",
      "content_hash": "90da9bb67a52f82ed11a005bc668f11aed8f980f613175af1a4153bec3231b54",
      "document_id": "publication",
      "score": 0.6500993092118776,
      "source_date": "2026-09-26",
      "source_uri": "https://github.com/MattShelton04/41026ASDProject/blob/main/student-1/config/rag/documents/publication.md",
      "title": "Publishing a version"
    }
  ],
  "confidence": "high",
  "corpus_id": "operator-guidance",
  "corpus_version": "ecfa5da3cb24a80e563a915d99ef6a1c64bd94b952b8380b83239dc506f7025c",
  "evidence_gap_count": 0,
  "feature_key": "student-1-propertyscope-data-platform",
  "grounding_status": "ready",
  "model_profile": "remote-standard.v1",
  "models": [
    {
      "model": "gpt-5.6-luna",
      "prompt_hash": "0d02bd5272b177692439375abf92caef415a710e48c218dea2c609869e466596",
      "prompt_id": "planner",
      "prompt_version": "v8",
      "provider": "openai"
    },
    {
      "model": "gpt-5.6-terra",
      "prompt_hash": "658d2e02d26cf7e3b5524ee4663f9109c3d16d2bf90b67b83428d5797fbdaa71",
      "prompt_id": "adapter",
      "prompt_version": "v9",
      "provider": "openai"
    }
  ],
  "prompt_set": "default.v9",
  "request_id": "df2b8ab9-0c80-46fc-9e1c-efff17cc635f",
  "retrieval_status": "ready",
  "run_created_at": "2026-10-18T10:54:04.888447Z",
  "run_id": "387591f0-be44-4e88-8808-404f32cde8b9",
  "status": "succeeded",
  "tools": [
    {
      "call_id": "d2f426fa-a7ea-41d7-bf0e-af413b79ef13",
      "outcome": "succeeded",
      "tool_name": "context.retrieve.v1",
      "tool_version": "v1",
      "transport": "rag"
    },
    {
      "call_id": "e1d4c3bf-7be7-45f9-aec8-36d2fe9be2e1",
      "outcome": "succeeded",
      "tool_name": "data.releases.v1",
      "tool_version": "v1",
      "transport": "mcp"
    }
  ]
}
```

## B3 evidence

```json
{
  "citation_count": 2,
  "citations": [
    {
      "chunk_id": "314ac51b545f054de3370a284397d237513cd50947e6323c3e0f1a0217c80018",
      "citation_id": "cite-9615b8f4b51b393ec4eb991a6aa7c689d0efc09abdc3170e691474a0fdbc3e39",
      "content_hash": "a2a23bd56b60ca531cd994565d677166838979584ec34c474d74106bff31d7ef",
      "document_id": "sales-history",
      "score": 0.7313887938852918,
      "source_date": "2026-09-26",
      "source_uri": "https://github.com/MattShelton04/41026ASDProject/blob/main/student-1/config/rag/documents/sales-history.md",
      "title": "NSW property sales (PSI)"
    },
    {
      "chunk_id": "0d8298a4d4353f3a8faa8555ff125c5389ef0fcfc9e8e834812774c7ac0ee4a4",
      "citation_id": "cite-ac7e52260c09f23a2369c068538950b78d7e8f988a31cef1e8c68f0400ac02be",
      "content_hash": "5aee9e316bcd9821c84faa4f6d657b42f42d154cf9779a95758a7ce36f4a5cd1",
      "document_id": "sales-history",
      "score": 0.7227402521659653,
      "source_date": "2026-09-26",
      "source_uri": "https://github.com/MattShelton04/41026ASDProject/blob/main/student-1/config/rag/documents/sales-history.md",
      "title": "NSW property sales (PSI)"
    }
  ],
  "confidence": "moderate",
  "corpus_id": "operator-guidance",
  "corpus_version": "ecfa5da3cb24a80e563a915d99ef6a1c64bd94b952b8380b83239dc506f7025c",
  "evidence_gap_count": 1,
  "feature_key": "student-1-propertyscope-data-platform",
  "grounding_status": "ready",
  "model_profile": "remote-standard.v1",
  "models": [
    {
      "model": "gpt-5.6-luna",
      "prompt_hash": "0d02bd5272b177692439375abf92caef415a710e48c218dea2c609869e466596",
      "prompt_id": "planner",
      "prompt_version": "v8",
      "provider": "openai"
    },
    {
      "model": "gpt-5.6-terra",
      "prompt_hash": "658d2e02d26cf7e3b5524ee4663f9109c3d16d2bf90b67b83428d5797fbdaa71",
      "prompt_id": "adapter",
      "prompt_version": "v9",
      "provider": "openai"
    }
  ],
  "prompt_set": "default.v9",
  "request_id": "fe56922d-4756-4687-98d1-cdc254959e81",
  "retrieval_status": "ready",
  "run_created_at": "2026-10-18T10:54:16.671472Z",
  "run_id": "56c85266-6cc9-4421-9f49-61794f55e7b3",
  "status": "succeeded",
  "tools": [
    {
      "call_id": "e21b3275-24b7-45e2-be9f-06c4efea3af8",
      "outcome": "succeeded",
      "tool_name": "context.retrieve.v1",
      "tool_version": "v1",
      "transport": "rag"
    },
    {
      "call_id": "e9692639-41ed-4ac7-86ea-9e52ee42de05",
      "outcome": "succeeded",
      "tool_name": "platform.capabilities.v1",
      "tool_version": "v1",
      "transport": "mcp"
    }
  ]
}
```

## B4 evidence

```json
{
  "completed_roles": [
    "planner",
    "reviewer",
    "worker"
  ],
  "dataset_id": "nsw-suburb-boundaries",
  "models": [
    {
      "model": "gpt-5.6-luna",
      "provider": "openai",
      "role": "planner"
    },
    {
      "model": "gpt-5.6-terra",
      "provider": "openai",
      "role": "worker"
    },
    {
      "model": "gpt-5.6-terra",
      "provider": "openai",
      "role": "reviewer"
    }
  ],
  "plan_steps": 2,
  "provider_mode": "model",
  "release_id": "37b0a3eb-68ae-4314-bcc9-98e22415736e",
  "release_status": "accepted",
  "review_findings": 14,
  "review_recommendation": "correct",
  "route": "/api/data-platform/v1/release-reviews",
  "run_id": "2058658b-8c85-44ee-bebc-cfc0cd8ab8b8",
  "stages": [
    {
      "round": 1,
      "stage": "planner",
      "status": "completed"
    },
    {
      "round": 1,
      "stage": "worker",
      "status": "completed"
    },
    {
      "round": 1,
      "stage": "reviewer",
      "status": "completed"
    },
    {
      "round": 1,
      "stage": "human",
      "status": "running"
    }
  ],
  "state": "awaiting_human",
  "template_id": "f1-release-readiness-review",
  "worker_evidence_transports": {
    "mcp": 2
  }
}
```
