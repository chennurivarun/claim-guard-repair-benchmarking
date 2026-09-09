# Client invoice demonstration

The September 2026 workflow starts with **Benchmark data setup**, followed by **Document Intelligence**. This supersedes older README references to synthetic in-house data for the primary client demo.

| Stage | Behavior |
| --- | --- |
| Benchmark data setup | Upload client-provided third-party claims or in-house repair invoices into separate groups. Counts and consolidated extraction tables reflect persisted documents. |
| Document Intelligence | Upload one fresh invoice and an optional engineer estimate. Live invoices are excluded from both reference groups. |
| Source documents | Review the selected invoice pages and linked estimate pages. |
| Review extraction | Review invoice lines and estimate operations; vehicle fields missing from the invoice can be filled from a safely linked estimate, with source attribution. |
| Calculation checks | Check extraction arithmetic and run comparison. |
| Invoice outcome & evidence | Show challenge, no challenge, or insufficient evidence, then inspect every line and its supporting evidence. |
| Repair Price Benchmarking / In-house Benchmark | Review the respective client reference population. Each reference invoice is excluded from its own retrospective comparison. |

## Dataset selection

Upload only the client's files into the two setup areas. Existing unlabelled documents are not automatically assumed to be client data. Re-uploading an existing document in a reference area explicitly selects it for that group without duplicating the document. A file already assigned to a different group is rejected. A live file must be fresh; an existing reference file cannot be reused as the held-out demonstration invoice.

No files were deleted. Legacy data remains stored for audit, while the client benchmark views and client invoice pricing exclude it. Source labels are stored in document metadata, so no schema migration is necessary. Ingestion prepares reference data and is not represented as model training.

## Estimate handling

An optional estimate supplied with a live invoice carries an explicit association to that invoice document. Conflicting registrations prevent pairing. For batch uploads, safe identifier matching is used; tied matches remain unpaired. Estimate operations remain supporting evidence and do not become client invoice price observations. Missing vehicle fields are filled with their document source saved; existing invoice values are retained. Unresolved or unreadable documents can be opened in Manual review.

## Validation and demo preparation

Regression tests cover reference separation, live exclusion, in-house-only evidence, empty datasets, duplicate uploads, ambiguous linkage, field enrichment, and actual PDF invoice/estimate processing. Frontend build, lint, and Vitest checks cover the UI code. Browser checks cover navigation and empty client intake/benchmark states.

Select the actual client reference files and keep a separate live example before presenting. Real client extraction quality and benchmark coverage still require validation against those documents. The historical and in-house P90 sources each require at least three matched observations; missing evidence must not be presented as an established no-challenge result.
