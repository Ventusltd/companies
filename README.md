# Companies

Annual Companies House public-data processing for Deploy Net Zero.

The repository contains reviewed acquisition, accounts-extraction and cartridge-compilation code. It publishes a stable `data/current/` dataset that is overwritten by each successful annual refresh; Git history provides recovery and chronology.

## Boundaries

- Companies House is credited as the public-register source.
- Director names, individual PSC records, dates of birth and residential addresses are excluded.
- Total assets and net assets remain separate factual fields.
- REPD name matches are candidates unless independently verified.
- No public credit or bankability score is produced.
- Raw Companies House archives are processed in temporary Actions storage and are not committed.

Source: Companies House. Public-register information retrieved and processed by Deploy Net Zero.
