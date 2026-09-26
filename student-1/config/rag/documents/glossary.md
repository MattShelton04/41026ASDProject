# Property data terms

## Sources and updates

- Source: a registered publisher dataset, such as G-NAF or NSW sales.
- Data update (ingestion run): one download-and-build attempt for a source, shown in Update history.
- Scope: what an update loads. Complete source is the default; selected PSI archive years are partial.
- Coverage: which areas and periods a published dataset includes.
- Property reference: PropertyScope's stable identifier for an address record.

## Versions and publishing

- Candidate: a newly built version waiting for review. It is kept separate from published data and never appears in search.
- Data checks (quality results): the automated checks run on a candidate. Required checks must pass before publishing.
- Published version (accepted release): the version currently used by search, property pages and other research areas. Only one is current per dataset.
- Superseded: a previously published version replaced by a newer one. It is kept for history.
- Rejected: a candidate an operator declined, with the reason recorded.
- Release file (artifact): the compressed file of records built for a version, with its record count and SHA-256 checksum.
- Downstream import: another research area importing a published version into its own database. It runs after publishing and separately from it.
