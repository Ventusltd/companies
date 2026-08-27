# COMPANIES HOUSE RECOVERY CHECKPOINT

Status: code-only workstream on `202608270257-companies-house-phase`. No Companies House output has been published and `data/current/` remains unchanged.

## Safe recovery order

1. Run **Validate Companies House Compiler**. It uses deterministic local fixtures, finishes without downloading Companies House archives and cannot publish.
2. Run **Plan Companies House Refresh** with three months and a 12 GB ceiling. It discovers official URLs and records byte sizes, ETags and modification dates without downloading the archives or publishing.
3. Review this branch before merging it. Do not run a publishing workflow from the branch.
4. After merge, run **Annual Companies House Refresh** once to create the verified bootstrap and `retained-companies-v1.json`. The 27 August 2026 plan was 13 archives and 30,058,865,034 compressed bytes.
5. Only after the bootstrap is present and verified, use **Quarterly Companies House Refresh**. The 27 August 2026 quarterly plan was four archives and 7,046,921,879 compressed bytes.

## Publication gates

- Annual and quarterly downloads must match the official preflight byte closure.
- Quarterly compilation requires a hash-bound retained bootstrap state.
- Every cartridge hash, record count, company number and cross-cartridge record is independently rechecked.
- The £10 million GBP threshold, SIC B–E, BTM, SPV, REPD, Atlas and NEWS rules are re-proved before publication.
- NEWS may annotate an established REPD match only; it may never establish company identity.
- Director names, individual PSC records, dates of birth, residential addresses, credit scores and bankability scores are rejected.
- Raw archives remain temporary Action artifacts and are never committed.

## PipelineNews boundary

PipelineNews candidate generation `202608270055` remains frozen at main commit `77bda8c3809d02550d06a1c4154315f56d1120fb`. The immutable candidate manifest remains `not-authorised`; owner authorisation remains a separate record. The stable route, `releases/current.json` and GlobalGrid catalogue are outside this Companies House workstream and must not change.
