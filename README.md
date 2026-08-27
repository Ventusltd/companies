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

## Boundaries

- Companies House is credited as the public-register source.
- Director names, individual PSC records, dates of birth and residential addresses are excluded.
- Total assets and net assets remain separate factual fields.
- REPD name matches are candidates unless independently verified.
- Generic offices, estate agents and ordinary wholesalers do not qualify merely because they have assets.
- No public credit or bankability score is produced.
- Raw Companies House archives are processed in temporary Actions storage and are not committed.

Source: Companies House. Public-register information retrieved and processed by Deploy Net Zero.
