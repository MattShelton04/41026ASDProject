# Where a value came from

Every published value can be traced to a dataset version, the data update that produced it, and the publisher's source.

## What to record when explaining provenance

- the dataset and its version (release) identifier,
- the source and the scope of the update that built it,
- the record schema version,
- the record count and SHA-256 checksum of the release file,
- when it was published.

Never present a candidate as published data.

## Release files

Each version has one release file: gzip-compressed, one JSON record per line. The SHA-256 checksum and byte count describe the compressed file exactly as downloaded; the record count is the number of records inside it. Published versions and their files are never changed; a correction is a new version that supersedes the old one.

## Dates mean different things

A source date is when the publisher released the data. A published date is when PropertyScope made the version current. A download is not proof that another research area imported it.
