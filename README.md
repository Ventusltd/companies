# Companies

Companies House public-data processing for Deploy Net Zero.

The repository retains reviewed acquisition and accounts-extraction code. The current recovery checkpoint, `202608281337`, builds a key-only relationship-and-report candidate; it does not publish or overwrite a stable dataset.

## Compact relationship candidate

GitHub Actions provides the transient compute, while the GitHub REST API verifies run and retained-artifact provenance. The planned Companies House bulk archive is downloaded once into temporary runner storage; the Companies House REST API is not used. The expected 294,904-company selected-union closure is a validation measure, not a durable company dataset; the aggregate report separately records the full number of Basic Company rows scanned. The checkpoint writes only:

- `company-repd-relationships-v1.parquet`, containing only the Company number, REPD reference and evidence type for every candidate edge;
- `solar-company-repd-relationships-v1.parquet`, containing the exact three-key Solar-to-Company-to-REPD subset derived transiently from pinned REPD technology;
- a compact aggregate report, bounded manifest, DuckDB audit and source evidence.

Parquet is written with DuckDB 1.3.2 and ZSTD compression, then independently read back against an exact three-column schema, composite keys, a dataset-level semantic digest and whole-file SHA receipts. Each file is hard-capped at 20 MB and the durable closure at 30 MB total. Descriptive fields, technology, row-level repository provenance and per-row digests are forbidden from the bridges; exact source commits and paths are recorded once in the manifest and joined from the owning repositories when needed. No raw or selected Companies database, company-master Parquet, embedded relationship JSON, JSON cartridge or source archive is part of the durable closure.

Publication is restricted to an immutable candidate branch. `main`, `data/current/`, Pages and releases remain unchanged. Historical workflows live under `.github/workflow-history/` as inert audit evidence; checkpoint `202608281337` is the sole active publication path.

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
