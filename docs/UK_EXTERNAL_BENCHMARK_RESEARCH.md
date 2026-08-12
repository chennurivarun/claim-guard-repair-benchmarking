# UK external benchmark source assessment

## Purpose

This investigation tests whether external UK motor-repair sources can strengthen ClaimGuard's existing invoice-history P90 benchmark. It does **not** activate a new challenge rule. The current comparison engine remains unchanged until the business owner defines source priority and approves the final rule.

## What was found

| Source | Access | Data found | Fit for ClaimGuard | Decision now |
|---|---|---|---|---|
| GOV.UK MOT fee schedule | Public, Open Government Licence | Statutory maximum Class IV car MOT fee in GBP; MOT is VAT-exempt | Exact job-level match to `LAB-0001` | Staged as provisional, source-linked evidence |
| Honda UK National Recommended Pricing | Public manufacturer schedule | Fixed repair prices in GBP including parts, labour and VAT | Front-wheel alignment cleanly matches job-level `LAB-0007`; many other rows combine parts and labour and must not be forced into part-only ontology items | Stage only the clean alignment match; retain other rows for ontology review |
| Ford Essential repairs | Public manufacturer schedule | Model-group fixed prices including parts, labour and VAT | Useful job prices, but most current ontology items split parts and labour | Research candidate only until combined-job ontology categories are approved |
| Vauxhall fixed-price repairs | Public manufacturer schedule | Fixed repair prices including parts, labour and VAT | Same scope mismatch as Ford for most rows | Research candidate only |
| Audatex | Licensed product/integration | Parts, paint and labour breakdown export is described, but no public price dataset | Strong potential if the client supplies authorised access | Do not scrape or fabricate; request licensed export/API access |
| cap hpi | Subscriber API | Vehicle valuation and product services require credentials | Useful vehicle context, not a direct public repair-line price source | Optional licensed enrichment only |
| Glass's Guide | Commercial login | Valuation and service/repair products, no open price rows | Potential context/benchmark source if licensed | Request authorised access |
| FCA motor claims review | Public report | Aggregate 2023 repair cost, labour rate and labour hours | Market reasonableness context; not comparable to a repair line item | Keep outside the line-item benchmark |
| DfT transport expenditure data | Public ODS | Transport maintenance/spares price indices | Useful for future time normalisation; not a repair price | Do not treat as an ontology price |

The complete machine-readable matrix is in `sample-data/uk_external_source_assessment.csv`.

## Curated observations staged in the application

| Ontology item | External observation | Published price | Normalised net | VAT treatment | Status |
|---|---|---:|---:|---|---|
| `LAB-0001` — MOT test (Class IV) | GOV.UK maximum car MOT fee | £54.85 | £54.85 | Exempt | Provisional |
| `LAB-0007` — Front wheel alignment | Honda UK national recommended price | £75.00 | £62.50 | Published gross, converted at 20% VAT | Provisional |

The Honda schedule states that its fixed prices include parts, labour and VAT. Therefore the source's £75.00 published price is retained as `original_price`, while £62.50 is stored in ClaimGuard's existing net-price field. This preserves both the exact source value and a comparable net value.

## Governance and runtime behaviour

- The data uses existing `SourceProvider`, `SourceImport`, and `PriceObservation` tables; no parallel benchmark database was created.
- Each source receives priority `0`, `requires_human_approval = true`, and `challenge_rule_enabled = false`.
- Observations are `PROVISIONAL`, not approved market evidence.
- Imports are identified by a source-file SHA-256 digest, so replaying the same file creates no duplicates.
- The current-invoice P90 logic, historical-claim comparison, challenge gates, and decisions are unchanged.
- The Ontology Bank exposes provider, official source link, date, scope, VAT basis, published price, net price, and approval status.

## Why most visible manufacturer prices were not imported

ClaimGuard's ontology currently separates many part and labour items. Public fixed-price offers often represent a complete fitted job containing the part, labour and VAT. Mapping a £175 fitted brake-pad job to a part-only brake-pad item—or to labour-only fitting—would create a false benchmark. Those sources are documented but intentionally not imported until a combined-job ontology item or governed allocation policy exists.

## Recommended next decision

The manager should review the source matrix and decide:

1. which providers are allowed in production;
2. whether manufacturer fixed-price jobs need new combined-job ontology categories;
3. source priority by repair category and vehicle population;
4. whether the later rule is `MIN(historical P90, approved external benchmark)` or another governed policy;
5. minimum sample, age, geography, VAT, and vehicle-comparability controls.

Only after those decisions should a migration promote selected observations from provisional to approved and allow the comparison engine to consume them.

## Reproduce the local import

From `backend/`, after the normal environment setup:

```bash
uv run claimguard-import-external-benchmarks
```

Normal `claimguard-bootstrap` also stages the file idempotently after importing the supplied ontology and historical workbooks.

## Primary sources checked

- GOV.UK MOT fees: https://www.gov.uk/getting-an-mot/mot-test-fees
- Honda UK fixed-price repairs and published schedule: https://www.honda.co.uk/cars/owners/maintaining-your-honda/repairs/fixed-price-repairs.html
- Ford UK repairs: https://www.ford.co.uk/owner/service-and-maintenance/ford-repairs
- Vauxhall parts and fixed-price repairs: https://www.vauxhall.co.uk/owners/parts-and-tyres.html
- Audatex AudaBridge: https://audatex.co.uk/solutions/audabridge/
- cap hpi developer services: https://developer.cap.co.uk/webservices
- Glass's Guide: https://glass.co.uk/homepage/
- FCA motor claims analysis: https://www.fca.org.uk/publication/multi-firm-reviews/motor-insurance-claims-analysis-multi-firm-review-2025.pdf
- DfT transport expenditure data: https://www.gov.uk/government/statistical-data-sets/transport-expenditure-tsgb13
