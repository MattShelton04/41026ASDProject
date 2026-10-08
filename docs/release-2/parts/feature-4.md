# Feature 4: Site, Planning and Building Due Diligence (Release 2 plan)

Owner: Michael. Do everything in the [common feature checklist](README.md#common-feature-checklist).
This file covers only what is specific to Feature 4.

## Multi-agent workflow (suggestion)

**Professional question set**: given a site review:

- **Planner** chooses the constraints and evidence to examine.
- **Worker** drafts questions for qualified professionals, using `duediligence.review.inspect.v1`
  and `duediligence.evidence.summary.v1`.
- **Reviewer** checks that every question is grounded in recorded evidence and that the draft
  gives no legal, safety or compliance certification.
- **Human** accepts, corrects or partially accepts the questions.

Optionally, accepted questions can be saved to the site review. If so, the Feature 4 backend
does the save, not the Multi-Agent Server.

## Endpoint tests (suggestion)

| Endpoint function | Happy path | Failure case |
|---|---|---|
| `POST /api/due-diligence/v1/site-reviews` | Valid property creates a review (201) | Invalid payload returns 422 and nothing is persisted |
| `GET /api/due-diligence/v1/site-reviews/{id}/evidence` | Seeded review returns evidence and its state | Unknown ID returns 404 |

## Carry-over from Release 1

- The native generated-question renderer must accept grounded finding objects and `next_step`.
  It should show follow-up questions instead of dropping the structured findings.

## Cloud

- The PostGIS container and the map layers must work behind the Azure edge. Check that the
  bounded GeoJSON `/map` responses load over HTTPS.

## Steps

1. 9 Oct: endpoint tests and a green `student-4.yml` with JUnit artifact.
2. 13 Oct: workflow manifest, proxy routes and panel. A local UI workflow is captured.
3. 16 Oct: production config; cloud CRUD smoke case passes; map checked on Azure.
4. 18 Oct: with cloud AI on, the feature checked on Azure. Contribution log and video segment by
   21 Oct.
