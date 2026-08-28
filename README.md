# Companies

Companies House public-data processing for Deploy Net Zero.

The repository retains reviewed acquisition and accounts-extraction code. The current recovery checkpoint, `202608281112`, builds a compact relationship-and-report candidate only; it does not publish or overwrite a stable dataset.

## Compact relationship candidate

GitHub Actions provides the transient compute, while the GitHub REST API verifies run and retained-artifact provenance. The planned Companies House bulk archive is downloaded once into temporary runner storage; the Companies House REST API is not used. The expected 294,904-company selected-union closure is a validation measure, not a durable company dataset; the aggregate report separately records the full number of Basic Company rows scanned. The checkpoint writes only:

- `company-repd-relationships-v1.parquet`, containing every candidate Company-to-REPD edge;
- `solar-company-repd-relationships-v1.parquet`, containing the Solar-to-Company-to-REPD subset;
- a compact aggregate report, bounded manifest, DuckDB audit and source evidence.

Parquet is written with DuckDB 1.3.2 and ZSTD compression, then read back against its declared schemas, row hashes and keys. Each file is hard-capped at 20 MB and the durable closure at 30 MB total. Relationship edges retain stable company, REPD and evidence references, including exact cross-repository commit and path provenance. No raw or selected Companies database, company-master Parquet, embedded relationship JSON, JSON cartridge or source archive is part of the durable closure.

Publication is restricted to an immutable candidate branch. `main`, `data/current/`, Pages and releases remain unchanged. Historical workflows remain in Git as recovery evidence but are superseded as publication paths by checkpoint `202608281112`.

## Historical annual workflow

The retained annual workflow documents the earlier rolling electronic-accounts process. It is audit history only and must not be dispatched as a publication route. Checkpoint `202608281112` is the sole authorised Companies recovery path.

## Boundaries

- Companies House is credited as the public-register source.
- Director names, individual PSC records, dates of birth and residential addresses are excluded.
- Total assets and net assets remain separate factual fields during transient selection only; neither is retained in the relationship tables.
- REPD name matches are candidates unless independently verified.
- Generic offices, estate agents and ordinary wholesalers do not qualify merely because they have assets.
- No director, individual PSC, date-of-birth or residential-address field is produced; no public credit or bankability score is produced.
- Raw Companies House archives are processed in temporary Actions storage and are not committed.

Source: Companies House. Public-register information retrieved and processed by Deploy Net Zero.
