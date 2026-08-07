# Repair benchmarking model

ClaimGuard stores each mapped repair invoice line as an immutable historical observation. The shared ontology ID is the grouping key, so descriptions such as “front screen”, “windscreen” and “replace windshield” can contribute to one approved canonical item rather than being benchmarked separately.

## What is calculated

| Measure | Meaning |
| --- | --- |
| Minimum / maximum | Lowest and highest observed net invoice-line cost. |
| Mean | Arithmetic average of observed net invoice-line costs. |
| Median | Middle observed cost; the average of the two middle costs for an even population. |
| Mode | A value repeated more often than any other value; blank where no unique repeat exists. |
| 25th / 75th percentile | Interpolated quartiles used to show the central cost band. |
| Outlier count | Values outside the standard 1.5 × interquartile-range fences. |
| Count | Number of invoice observations included in the group. |
| Labour statistics | The same measures for explicit labour rates, or hourly labour lines when available. |

For each invoice line, ClaimGuard calculates two independent price signals:

| Signal | Calculation |
| --- | --- |
| Uploaded-invoice P90 | Interpolated 90th percentile (`PERCENTILE.INC`) of earlier uploaded invoices mapped to the same canonical repair item. The current invoice is excluded and at least three earlier prices are required. |
| Governed price | 60% approved ontology price + 40% eligible historical-claim weighted median when both are reliable; otherwise the one reliable source is used. Unit, quantity, approval, sample-size and lineage checks can prevent this signal from being used. |

The final supported price is the **higher** of P90 and the reliable governed price, capped at the current billed price. This conservative rule retains both evidence streams and prevents the system from claiming a larger reduction than either reliable stream supports. A challenge requires the current price to exceed that final supported price by both at least £5 and more than the selected 5% or 10% threshold.

The mapping LLM may choose only from retrieved ontology candidates. It does not create repair categories and never supplies or changes a price.

Estimates and credit notes do not enter the dashboard population. A finalised ClaimGuard invoice is appended only after its mapping has a human-reviewed approved or edited status, so an invoice never influences its own challenge recommendation.

Zero, missing and invalid costs stay visible in the data-quality count but are excluded from benchmark statistics. A group is labelled **Insufficient** below 3 observations, **Usable** from 3–9, and **Strong** from 10 observations.

## UK classification policy

| Stored dimension | Standard / usage |
| --- | --- |
| `official_vehicle_class` | Type-approval class, such as M1 passenger vehicle or N1 light goods vehicle. |
| `bodywork_code` | Passenger-car bodywork codes AA–AF: saloon, hatchback, estate, coupe, convertible and multipurpose vehicle. |
| `market_segment` | Optional business segment such as SUV or luxury. This is explicitly not represented as an official regulatory class. |
| `classification_source` | Provenance for the supplied classification; rows without source data stay **Unclassified**. |

The M1 definition and passenger/light-commercial framing are aligned with the [DVSA MOT manual](https://www.gov.uk/guidance/mot-inspection-manual-for-private-passenger-and-light-commercial-vehicles/introduction) and the [Clean Air Zone vehicle categories](https://www.gov.uk/government/publications/air-quality-clean-air-zone-framework-for-england/annex-a-clean-air-zone-minimum-classes-and-standards). The AA/AB/AC bodywork codes follow the [vehicle type-approval bodywork codification](https://www.legislation.gov.uk/eudr/2007/46/pdfs/eudr_20070046_2011-02-24_en.pdf).

For production-level insurer enrichment, use a licensed provider rather than inventing vehicle risk or repair classes. Thatcham Research describes its ABIcode/Vehicle Risk Data as an industry-standard vehicle coding structure and its rating data as covering cars and LCVs; licensing and source lineage should be retained with every imported classification. [Thatcham Vehicle Risk Data](https://www.thatcham.org/pf/vehicle-risk-data/)

## Comparison selection and dashboard controls

When a current vehicle has a sourced classification, ClaimGuard first looks for at least three observations with the exact same governed category. If that minimum is met, only that category is used. Otherwise, the engine falls back to all vehicle categories and records the requested category, selected population and fallback reason in the comparison evidence.

The dashboard can filter by vehicle category, repair item and minimum sample size. Every benchmark row exposes its source invoices, while the data-quality panel reports classification coverage, excluded cost rows and the latest observation date.

## Repairer knowledge graph

The graph is a second view of the same rolling-P90 exceptions; it does not calculate a separate benchmark.

| Visual measure | Meaning |
| --- | --- |
| Repairer circle size | Distinct challenged invoices for the repairer. |
| Repairer colour intensity | Total positive difference above P90. |
| Repair-item node size | Distinct challenged invoices containing the canonical item. |
| Connection thickness | Distinct challenged invoices for the repairer/item relationship. |
| Node or connection selection | Exact invoice lines, billed values, earlier P90, differences and history counts. |

Repairer names are conservatively grouped by case-insensitive, whitespace-normalised identity. The original display name remains visible in evidence. The graph and aggregate benchmark table consume the same rolling-P90 exception records and therefore use the same threshold and £5 gate. Review Findings displays that P90 evidence alongside the governed ontology/historical-claim calculation and applies the conservative combined supported-price rule described above.
