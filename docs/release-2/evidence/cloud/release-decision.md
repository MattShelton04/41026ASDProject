# Release decision

Recorded with `uv run scripts/dev.py ai review decide`. The agentic loop's Cloud Deployment Report Review informed this decision; the named person made it.

| Field | Value |
|---|---|
| Decision | **RELEASE** |
| Decided by | Matthew Shelton |
| Decided at | 2026-10-18T09:37:49Z |
| Cloud review | [cloud-review.md](../reviews/cloud-review.md) |
| Review ID | `44929d5d-ed8d-4e0f-b7f7-2097d391e640` |
| Loop run ID | `22a7614b-f8b3-4a14-8e41-cedd265ce2cb` (deterministic) |
| Review verdict | pass |
| Prompt set | `review-cloud.v2` |
| Evidence bundle SHA-256 | `b0362e8900295843d474adccf5b1bcaabbbabf3f7207a47b0ffffa98f8ed67c0` |
| Overrode a failed review | no |

## Rationale

Cloud review passed 18 of 18 checks on run 39112162750 (main at 3c25c083): release gate passed, 21 of 21 containers running, public smoke test 37 of 37 with 0 skipped including create, read and delete for all five features, AI tier disabled (503 ai_disabled), and B5 and B6 validation with no failures. Known issues are non-blocking and recorded for their owners in evidence/cloud/README.md (Feature 1 suburb-qualified search read budget, Feature 3 published suburbs 503, Feature 2 fixture cases). Recorded by Claude Code at Matthew Shelton's request.

## Evidence reviewed

| Path | Status | SHA-256 |
|---|---|---|
| `cloud/cloud-deployment-report.md` | read | `218eed25554178b53b5af52872860e58e402a741dde1fea32673fc519223031a` |
| `cloud/cloud-smoke.json` | read | `9dc0fe945d002a900b24ffc713545f4b4daf8115c5f6aebd72292ecea32ccd88` |
| `cloud/image-build.json` | read | `613d35273fc4cd68ac85b4a1ac879508ce7cbaebb815fcac7f238f78095ff993` |
| `cloud/logs/build.log` | read | `f81f761fba4a0a86f03959016d28f6e3f8c2a04c951d998b5637f118cb38461a` |
| `cloud/logs/deploy.log` | read | `a05e03408e0c70e1de76819ba958ee4bd2596e8527eeeead46ee06f6a0c7159f` |
| `cloud/logs/push.log` | read | `e68023023bff019cf7d661ed21775b5ccd4f373229e9cf727ca18732578cf7f8` |
| `cloud/logs/smoke.log` | read | `48f673ad28e3697ed5371a0fc3858a4a5c12d3ecec847295bbf5a842ff51c10e` |
| `cloud/release-gate.json` | read | `7dec98b5cd75928350ff3e1635d5d845c1cc7ba10abcb515c036caffa5383d31` |
| `cloud/vm-deploy.log` | read | `c8ae47b562b1892587dd8dad5a94e1c10af4fa85a08bf1bf7e4e09bbe3b52beb` |
| `cloud/vm-status.log` | read | `f6e604d2d779b076ee36b8759ff7c5ecb865556f9c84b48bc1f5563dcf56112e` |
