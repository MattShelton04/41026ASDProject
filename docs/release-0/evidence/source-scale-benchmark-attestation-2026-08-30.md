# Source-scale benchmark attestation — 30 August 2026

This bounded attestation was derived from the six local suite summaries named below. It preserves
review-critical values without committing credentials, complete `pg_stat_io` snapshots or large
JSON plans. Raw folders remain under `.propertyscope-runtime/source-scale-benchmarks/<suite>/`; the
SHA-256 values make later copies detectably different. A plan-manifest hash is SHA-256 over sorted
UTF-8 lines of `<plan filename>=<plan SHA-256>`. Cancellation produced no completed plans, so those
empty manifests have the standard empty SHA-256.

## Environment and commands

- Image: `postgis/postgis:16-3.4`; otherwise-idle disposable `propertyscope_benchmark` database.
- Harness: `scripts/source_scale_benchmark.py`; three fresh-schema repetitions per variant.
- Safety: exact database-name/disposable confirmation, 30-minute server/client materialisation
  ceilings, exact-worker cancellation, rollback and schema-drop verification.
- Credentials and database URL are omitted. Executed argument shapes were:

```text
uv run python scripts/source_scale_benchmark.py run --dataset <psi|bocsar> --scale 100000 --repetitions 3 --database-url <redacted> --confirm-disposable --confirm-database propertyscope_benchmark
uv run python scripts/source_scale_benchmark.py run --dataset <psi|bocsar> --scale 100000 --repetitions 3 --force-cancel-after-seconds 2 --database-url <redacted> --confirm-disposable --confirm-database propertyscope_benchmark
uv run python scripts/source_scale_benchmark.py run --dataset <psi|bocsar> --scale 1000000 --repetitions 3 --gate-evidence <matching-100k-suite>/suite-summary.json --database-url <redacted> --confirm-disposable --confirm-database propertyscope_benchmark
```

## Suite integrity

| Local suite pointer | Mode | Runs | `suite-summary.json` SHA-256 | Plan-manifest SHA-256 |
| --- | --- | ---: | --- | --- |
| `psi-100000-20260830T094159Z` | forced cancellation | 6 | `2cadaf0b4bbe311a8d47cd4e73bccacba882f34736907c7b3a7264baedd83830` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `bocsar-100000-20260830T094305Z` | forced cancellation | 6 | `d9f16ba93aa7d37a548db9c37bd9f6637b5d6cd59363aec7acf5b182747a2c28` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `psi-100000-20260830T094349Z` | measurement | 6 | `f1512ad4939fe7fd3b9af47ae3bdbd5e3b5c246b528159c5db2a39e4151ba394` | `2cf72939b5f3c192c1afe07665b213e23cdf9a334178b3dd0d544d7f95e8bdeb` |
| `bocsar-100000-20260830T094421Z` | measurement | 6 | `8cbb86d4a16871f895f26294cfa1465d04881e9b45f922e8d7cde9b5b32f27d2` | `3592b0f56265a40795697b021be2dfa204497682a3c2306dbd04ffe8a61301af` |
| `psi-1000000-20260830T094455Z` | measurement | 6 | `f99c1b27a302a341bf69d582dc10b3f2409a912ffcdd20584eb7d86f31b10cd3` | `70c6130a7fe6b1c7cfcd240c0fe663aec67f364163294c8d7a90c4e099a3fd2a` |
| `bocsar-1000000-20260830T094758Z` | measurement | 6 | `1e76b074d5f066c7818cc5582d449d7902b0e75f9dd719e21092486f6a9e6503` | `a48c7cc1665dcee113ede91c6b155f9bcf3194d82f05e98dbcb3a27d0175a8f2` |

## Per-run measurement evidence

Temp and WAL are database/cluster counter deltas. Checkpoint is `requested/buffers`; I/O is
`reads/writes/extends/fsyncs` summed from bounded `pg_stat_io` deltas. Growth is `heap/index` bytes;
plan temp is `read/written` blocks. Every row ended with its schema dropped and `pg_ls_tmpdir` at
`0 files / 0 bytes`.

| Run | Seconds | Rows/s | Temp bytes | WAL bytes | Checkpoint | I/O | Growth bytes | Plan temp | Rows:fingerprint |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| `psi-100000-jsonb-wide-r1` | 2.687 | 37,216.226 | 240,774,701 | 102,092,098 | 0/0 | 62/0/11,564/0 | 21,848,064/2,113,536 | 224,054/251,696 | `66667:74b5177235448a35b297a359aaabd533` |
| `psi-100000-jsonb-wide-r2` | 2.156 | 46,382.189 | 240,774,701 | 102,080,445 | 0/0 | 57/0/11,564/0 | 21,848,064/2,113,536 | 224,054/251,696 | `66667:74b5177235448a35b297a359aaabd533` |
| `psi-100000-jsonb-wide-r3` | 2.078 | 48,123.195 | 240,774,701 | 102,552,857 | 0/0 | 167/0/11,563/0 | 21,848,064/2,113,536 | 224,054/251,696 | `66667:74b5177235448a35b297a359aaabd533` |
| `psi-100000-typed-phases-r1` | 1.375 | 72,727.273 | 8,027,328 | 80,475,018 | 0/0 | 3/0/8,290/251 | 28,663,808/3,612,672 | 4,045/4,055 | `66667:74b5177235448a35b297a359aaabd533` |
| `psi-100000-typed-phases-r2` | 1.219 | 82,034.454 | 8,027,328 | 50,279,509 | 1/253 | 3/253/5,183/0 | 28,663,808/3,612,672 | 4,045/4,055 | `66667:74b5177235448a35b297a359aaabd533` |
| `psi-100000-typed-phases-r3` | 1.250 | 80,000.000 | 8,027,328 | 80,505,968 | 0/0 | 4/0/8,294/0 | 28,663,808/3,612,672 | 4,045/4,055 | `66667:74b5177235448a35b297a359aaabd533` |
| `bocsar-100000-jsonb-ordered-r1` | 1.515 | 66,006.601 | 23,119,888 | 113,044,809 | 0/0 | 4/0/11,804/0 | 22,986,752/8,347,648 | 14,934/15,450 | `100000:f827d06a-9cbd-5488-b877-dcf9b1bb267d` |
| `bocsar-100000-jsonb-ordered-r2` | 1.578 | 63,371.356 | 23,119,888 | 113,021,262 | 0/0 | 3/0/11,803/0 | 22,986,752/8,347,648 | 14,934/15,450 | `100000:f827d06a-9cbd-5488-b877-dcf9b1bb267d` |
| `bocsar-100000-jsonb-ordered-r3` | 1.625 | 61,538.462 | 23,119,888 | 113,018,044 | 0/0 | 3/0/11,804/0 | 22,986,752/8,347,648 | 14,934/15,450 | `100000:f827d06a-9cbd-5488-b877-dcf9b1bb267d` |
| `bocsar-100000-typed-unordered-r1` | 1.437 | 69,589.422 | 6,424,592 | 79,210,700 | 1/183 | 4/183/7,328/129 | 22,986,752/8,347,648 | 2,583/5,526 | `100000:f827d06a-9cbd-5488-b877-dcf9b1bb267d` |
| `bocsar-100000-typed-unordered-r2` | 1.718 | 58,207.218 | 6,424,592 | 77,669,023 | 0/0 | 3/0/7,327/0 | 22,986,752/8,347,648 | 2,583/5,526 | `100000:f827d06a-9cbd-5488-b877-dcf9b1bb267d` |
| `bocsar-100000-typed-unordered-r3` | 1.579 | 63,331.222 | 6,424,592 | 77,521,584 | 0/0 | 3/0/7,328/0 | 22,986,752/8,347,648 | 2,583/5,526 | `100000:f827d06a-9cbd-5488-b877-dcf9b1bb267d` |
| `psi-1000000-jsonb-wide-r1` | 25.750 | 38,834.951 | 2,417,381,779 | 1,020,524,578 | 2/126 | 106,354/182,029/115,855/128 | 218,439,680/21,118,976 | 2,724,978/3,002,254 | `666667:b50c5d26f13aa33eaadeecc95790fef9` |
| `psi-1000000-jsonb-wide-r2` | 22.968 | 43,538.837 | 2,417,381,779 | 1,019,876,561 | 2/28 | 106,792/181,630/115,852/95 | 218,439,680/21,118,976 | 2,724,978/3,002,254 | `666667:b50c5d26f13aa33eaadeecc95790fef9` |
| `psi-1000000-jsonb-wide-r3` | 22.359 | 44,724.719 | 2,417,381,779 | 1,019,854,922 | 1/0 | 105,583/181,284/115,851/49 | 218,439,680/21,118,976 | 2,724,978/3,002,254 | `666667:b50c5d26f13aa33eaadeecc95790fef9` |
| `psi-1000000-typed-phases-r1` | 12.781 | 78,241.139 | 434,850,535 | 804,974,872 | 2/2,065 | 125,612/111,105/81,514/96 | 285,040,640/27,254,784 | 203,595/234,765 | `666667:b50c5d26f13aa33eaadeecc95790fef9` |
| `psi-1000000-typed-phases-r2` | 11.797 | 84,767.314 | 434,842,343 | 798,361,184 | 1/40 | 125,661/111,167/81,514/44 | 285,040,640/27,254,784 | 203,588/234,752 | `666667:b50c5d26f13aa33eaadeecc95790fef9` |
| `psi-1000000-typed-phases-r3` | 12.157 | 82,257.136 | 434,842,343 | 807,627,025 | 2/3,989 | 125,550/111,056/81,513/109 | 285,040,640/27,254,784 | 203,587/234,750 | `666667:b50c5d26f13aa33eaadeecc95790fef9` |
| `bocsar-1000000-jsonb-ordered-r1` | 17.657 | 56,634.762 | 244,355,232 | 1,142,905,613 | 2/44 | 180,957/181,403/117,110/76 | 229,834,752/76,619,776 | 308,280/313,515 | `1000000:f8efe63c-9dfb-5c8b-a95d-481b437fb820` |
| `bocsar-1000000-jsonb-ordered-r2` | 18.188 | 54,981.306 | 244,355,232 | 1,140,327,606 | 2/132 | 180,694/181,415/117,110/67 | 229,834,752/76,619,776 | 308,280/313,515 | `1000000:f8efe63c-9dfb-5c8b-a95d-481b437fb820` |
| `bocsar-1000000-jsonb-ordered-r3` | 17.719 | 56,436.593 | 244,355,232 | 1,138,445,162 | 2/142 | 180,612/181,283/117,110/80 | 229,834,752/76,619,776 | 308,280/313,515 | `1000000:f8efe63c-9dfb-5c8b-a95d-481b437fb820` |
| `bocsar-1000000-typed-unordered-r1` | 18.656 | 53,602.058 | 145,076,384 | 773,393,528 | 1/1,124 | 147,704/97,532/72,423/82 | 229,834,752/76,619,776 | 199,886/253,478 | `1000000:f8efe63c-9dfb-5c8b-a95d-481b437fb820` |
| `bocsar-1000000-typed-unordered-r2` | 18.563 | 53,870.603 | 145,076,384 | 786,711,413 | 2/1,727 | 148,218/97,914/72,424/54 | 229,834,752/76,619,776 | 199,886/253,478 | `1000000:f8efe63c-9dfb-5c8b-a95d-481b437fb820` |
| `bocsar-1000000-typed-unordered-r3` | 18.484 | 54,100.844 | 145,076,384 | 773,375,628 | 1/1,244 | 147,776/97,606/72,424/22 | 229,834,752/76,619,776 | 199,886/253,478 | `1000000:f8efe63c-9dfb-5c8b-a95d-481b437fb820` |

Identical fingerprints across each dataset/scale comparison are the bounded semantic-equivalence
signal. They do not claim that synthetic records establish official-source equivalence.

## Production capacity calibration

The harness inserts deterministic rows directly and therefore records no compressed artifact byte
count. Artifact expansion alone cannot be derived from this evidence. Production uses absolute
source-scale floors derived from the largest typed one-million-row counters above, projected to the
known source count with a 2.5 safety factor and rounded upward:

| Dataset | Planning count | Projected heap + index | Applied growth floor | Projected WAL | Applied WAL floor | Projected temp | Configured temp allowance |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| PSI | 7.4m | 5.38 GiB | 6 GiB | 13.91 GiB | 16 GiB | 7.49 GiB | 16 GiB |
| BOCSAR | 10.114565m | 7.22 GiB | 8 GiB | 18.53 GiB | 20 GiB | 3.42 GiB | 16 GiB |

The loader adds its 4 GiB reserve and requires both the fixed server-owned physical data/WAL
filesystem observation and the separately declared deployment ceiling to cover the applicable
growth, WAL and full temporary-file allowances before COPY. The configured artifact-derived value
can only raise the growth allowance; it cannot reduce these measured floors.

## Per-run cancellation evidence

Every row finished `cancelled` with cancel requested, rollback completed and schema dropped all
true. `pg_ls_tmpdir` was `0 files / 0 bytes` before and after; every server error was
`QueryCanceled`.

| Run | Seconds | Outcome |
| --- | ---: | --- |
| `psi-100000-jsonb-wide-r1` | 2.016 | cancelled; rollback; schema dropped; temp empty |
| `psi-100000-jsonb-wide-r2` | 2.015 | cancelled; rollback; schema dropped; temp empty |
| `psi-100000-jsonb-wide-r3` | 2.016 | cancelled; rollback; schema dropped; temp empty |
| `psi-100000-typed-phases-r1` | 2.015 | cancelled; rollback; schema dropped; temp empty |
| `psi-100000-typed-phases-r2` | 2.016 | cancelled; rollback; schema dropped; temp empty |
| `psi-100000-typed-phases-r3` | 2.000 | cancelled; rollback; schema dropped; temp empty |
| `bocsar-100000-jsonb-ordered-r1` | 2.015 | cancelled; rollback; schema dropped; temp empty |
| `bocsar-100000-jsonb-ordered-r2` | 2.015 | cancelled; rollback; schema dropped; temp empty |
| `bocsar-100000-jsonb-ordered-r3` | 2.015 | cancelled; rollback; schema dropped; temp empty |
| `bocsar-100000-typed-unordered-r1` | 2.015 | cancelled; rollback; schema dropped; temp empty |
| `bocsar-100000-typed-unordered-r2` | 2.016 | cancelled; rollback; schema dropped; temp empty |
| `bocsar-100000-typed-unordered-r3` | 2.016 | cancelled; rollback; schema dropped; temp empty |

## Limits

Counter deltas are capacity evidence from one otherwise-idle host, not isolated per-backend CPU or
I/O attribution. `cpu_or_running` in raw summaries means only active with no PostgreSQL wait event.
This attestation does not replace official-source count, checksum, review, publication, activation,
replay or predecessor-safety evidence and makes no portable runtime promise.
