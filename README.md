# Companies

Annual Companies House public-data processing for Deploy Net Zero.

The repository contains reviewed acquisition, accounts-extraction and cartridge-compilation code. It publishes a stable `data/current/` dataset that is overwritten by each successful annual refresh; Git history provides recovery and chronology.

## Annual workflow

[Run Annual Companies House Refresh](https://github.com/Ventusltd/companies/actions/workflows/annual-companies-house-refresh.yml)

The owner triggers one annual run. It processes the latest rolling electronic-accounts year, then overwrites these compact current views:

- industrial companies in SIC Sections B–E with total or net assets of at least £10 million;
- other specifically energy-relevant £10 million companies;
- deterministic REPD name candidates;
- probable renewable-project SPV candidates;
- behind-the-meter opportunity candidates.

The workflow does not continuously poll Companies House and does not commit raw archives.

Before any bulk download starts, a deterministic fixture proves the £10 million threshold, industrial and behind-the-meter tags, exact and previous-name REPD matches, classification boundary, and privacy exclusions.

The discovery job also freezes the exact official accounts and basic-company ZIP URLs, probes their compressed byte sizes, and publishes a download plan. A run fails before any bulk transfer if a URL leaves the official Companies House host, lacks a plausible `Content-Length`, changes through an off-host redirect, is duplicated, or the full closure exceeds the owner-declared budget (40 GB by default). Each download must then match its preflight byte count before extraction.

REPD candidates carry their GlobalGrid project ID and an exact Atlas V8 coordinate deep link. Canonical `PRIMARY_MATCH` PipelineNews items may annotate an already-established REPD candidate, but NEWS can never create or upgrade company identity. Each manifest pins the accounts, REPD closure and NEWS input hashes.

Before publication, `build/python/202608270444-verify-companies-house-output.py` independently recomputes every cartridge hash and count, checks company-number and cross-cartridge consistency, re-proves the £10 million, SPV, BTM, REPD, Atlas and NEWS gates, and recursively rejects prohibited personal or scoring fields.

## Boundaries

- Companies House is credited as the public-register source.
- Director names, individual PSC records, dates of birth and residential addresses are excluded.
- Total assets and net assets remain separate factual fields.
- REPD name matches are candidates unless independently verified.
- Generic offices, estate agents and ordinary wholesalers do not qualify merely because they have assets.
- No public credit or bankability score is produced.
- Raw Companies House archives are processed in temporary Actions storage and are not committed.

Source: Companies House. Public-register information retrieved and processed by Deploy Net Zero.
