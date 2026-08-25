# ADR-022: Connect official sources in the default local runtime

- Status: Accepted
- Date: 25 August 2026
- Owner: PropertyScope Feature 1
- Supersedes: the isolated full-data deployment portion of ADR-016 and ADR-021

## Context

PropertyScope originally used two local Compose projects: a deterministic showcase stack and an
opt-in source-scale stack selected with `--full-data`. The separation prevented accidental large
downloads, but it also created two durable databases and made real data appear to be a different
application mode. Operators had to understand an infrastructure flag before the interface could
offer official data, which worked against the product goal of showcasing statewide property
discovery with real accepted data.

Data volume is already an explicit, validated job decision. Registered `test` and `showcase`
profiles are small, while `full-data` means a complete official source snapshot. Starting services
does not start acquisition, so a second deployment boundary is not required to prevent an
unprompted G-NAF download.

## Decision

- The normal reloadable `ps-dev` stack connects every implemented official source transport and
  mounts the optional host source cache read-only.
- Remove the `--full-data` stack option, the `ps-full` Compose project and its overlay. One
  PostgreSQL/artifact generation history is used for example and official jobs.
- Keep `test`, `showcase` and `full-data` as registered acquisition scopes. They use the same
  validation, candidate generation, human review and atomic acceptance path.
- New official-source jobs default to the complete scope in the browser and data CLI. Operators can
  explicitly choose example or test data for a faster run. The synthetic fixture job continues to
  default to its showcase scope because it has no official source.
- Stack startup never initiates acquisition. A browser or CLI action is still required before any
  source is contacted or downloaded.
- Capacity and corruption ceilings remain fail-closed safeguards. Portable consumer-product bounds
  remain separate from complete warehouse acquisition as decided by ADR-021.

## Consequences

The ordinary showcase can be populated with accepted real data without switching databases or
restarting into a special runtime. Property search continues to read only the accepted generation,
so loading a candidate does not change user-visible results until human approval.

Developers must explicitly choose a small job profile when they want the faster path, and a complete
job can consume significant network, disk and processing resources. The UI previews that work before
queueing it, cached archives remain optional, and long CLI jobs support `--no-wait`.

Existing historical `ps-full` volumes are not migrated automatically. They remain Docker-owned data
until deliberately removed; the application now writes new work only to `ps-dev`.

## Alternatives considered

- **Keep the stack flag but select it automatically:** rejected because it retains duplicate project
  identity and databases while continuing to expose infrastructure concepts to the operator.
- **Automatically download every source during startup:** rejected because service lifecycle and
  data lifecycle have different failure, review and resource characteristics.
- **Remove small profiles:** rejected because deterministic CI, fast demonstrations and targeted
  reprocessing remain legitimate needs.
