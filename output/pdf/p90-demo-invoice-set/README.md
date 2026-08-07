# ClaimGuard P90 demo invoice set

This folder contains one ten-invoice test set:

| Files | Purpose |
|---|---|
| `Invoice_01_Original.pdf` and `Invoice_02_Original.pdf` | The two supplied original invoices, unchanged |
| `Invoice_03_Variant.pdf` to `Invoice_10_Variant.pdf` | Eight native-text invoices using the same repair pattern with controlled description and price variation |

The variants use four clearly synthetic repairers—Northfield Motor Repairs, Riverside Auto Centre, Metro Vehicle Services and Citywide Repair Group—so the repairer knowledge graph can demonstrate cross-repairer patterns. The two original invoices are copied without modification.

## Ontology-normalisation examples

The eight variant invoices deliberately use these descriptions for the same two canonical repair items:

| Canonical repair item | Descriptions exercised across invoices |
|---|---|
| Oil filter | Oil Filter; OL Filter; Oil_Fil; Engine Oil Filter; Oil Filter Element; Filter - Oil; OIL-FLTR; Oilfilter |
| Oil & filter / environmental disposal charge | Oil Disposal; Oil and Filter Disposal; Waste Oil Disposal; Environmental Oil Disposal; Oil/Filter Disposal Charge; Oil Disposal Fee; Waste Oil and Filter; Oil & Filter Disposal |

Air-filter and pollen-filter wording also varies in a smaller set of safe aliases.

## Recommended demonstration

For a fresh database, upload all ten PDFs as one batch, then select invoice `9510`. ClaimGuard excludes the selected invoice from its own benchmark and calculates P90 from the nine other invoices.

If the two supplied originals are already present in the database, upload only `Invoice_03_Variant.pdf` through `Invoice_10_Variant.pdf` to avoid duplicate history.

The P90 alert gate requires both:

- more than the selected percentage above P90 (10% by default); and
- at least £5 positive difference.

Verified examples for invoice `9510`:

| Standard item | Current | P90 | Difference | Expected result |
|---|---:|---:|---:|---|
| Oil filter | £26.50 | £15.69 | £10.81 | Challenge |
| Air filter (engine) | £63.28 | £37.46 | £25.82 | Challenge |
| Cabin / pollen filter | £35.70 | £21.13 | £14.57 | Challenge |
| Spark plug | £99.52 | £58.90 | £40.62 | Challenge |
| Engine oil (per litre) | £120.00 | £71.04 | £48.96 | Challenge |
| Full / main service labour | £475.00 | £281.20 | £193.80 | Challenge |

Small-value differences remain visible as evidence but are labelled `Within threshold`, avoiding challenge recommendations for amounts such as £0.77.
