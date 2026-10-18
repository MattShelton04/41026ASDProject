## Release gate: required CI workflows

**PASSED** for `3c25c083e09e5f170767e63655593c0e5b9f1e27` on `main` (checked 2026-10-18T08:41:45+00:00).

| Workflow | Result | Run | Commit | Relation | Detail |
|---|---|---|---|---|---|
| Integration CI | success | [#424](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106471900) | `3c25c083e09e` | identical | run #424 at 3c25c083e09e (identical) succeeded |
| Student 1 CI | success | [#383](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106472018) | `3c25c083e09e` | identical | run #383 at 3c25c083e09e (identical) succeeded |
| Student 2 CI | success | [#165](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106471994) | `3c25c083e09e` | identical | run #165 at 3c25c083e09e (identical) succeeded |
| Student 3 CI | success | [#156](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106472108) | `3c25c083e09e` | identical | run #156 at 3c25c083e09e (identical) succeeded |
| Student 4 CI | success | [#152](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106471969) | `3c25c083e09e` | identical | run #152 at 3c25c083e09e (identical) succeeded |
| Student 5 CI | success | [#162](https://github.com/MattShelton04/41026ASDProject/actions/runs/39106471984) | `3c25c083e09e` | identical | run #162 at 3c25c083e09e (identical) succeeded |

Rule: Integration CI must have succeeded for the deploy commit itself. Each Student N CI workflow is path-filtered, so its most recently created push or manual run on the branch whose head is the deploy commit or an ancestor of it must have completed with success. Queued or running runs are waited for; any other conclusion fails the gate.
