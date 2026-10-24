## Release gate: required CI workflows

**PASSED** for `7b3fb43728582d21bb8c9722405c040e3c18cbf2` on `main` (checked 2026-10-24T00:00:43+00:00).

| Workflow | Result | Run | Commit | Relation | Detail |
|---|---|---|---|---|---|
| Integration CI | success | [#480](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938611) | `7b3fb4372858` | identical | run #480 at 7b3fb4372858 (identical) succeeded |
| Student 1 CI | success | [#415](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938540) | `7b3fb4372858` | identical | run #415 at 7b3fb4372858 (identical) succeeded |
| Student 2 CI | success | [#198](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938639) | `7b3fb4372858` | identical | run #198 at 7b3fb4372858 (identical) succeeded |
| Student 3 CI | success | [#192](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938393) | `7b3fb4372858` | identical | run #192 at 7b3fb4372858 (identical) succeeded |
| Student 4 CI | success | [#186](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938431) | `7b3fb4372858` | identical | run #186 at 7b3fb4372858 (identical) succeeded |
| Student 5 CI | success | [#195](https://github.com/MattShelton04/41026ASDProject/actions/runs/40041938534) | `7b3fb4372858` | identical | run #195 at 7b3fb4372858 (identical) succeeded |

Rule: Integration CI must have succeeded for the deploy commit itself. Each Student N CI workflow is path-filtered, so its most recently created push or manual run on the branch whose head is the deploy commit or an ancestor of it must have completed with success. Queued or running runs are waited for; any other conclusion fails the gate.
