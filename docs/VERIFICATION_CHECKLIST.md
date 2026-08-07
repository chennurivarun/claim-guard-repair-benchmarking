# ClaimGuard verification checklist

Verified on 2 August 2026 using the supplied ten-invoice PDF batch and a clean SQLite database.

| Area | Expected behaviour | Verification result |
|---|---|---|
| Clean setup | Bootstrap creates the active ontology, price and historical banks before comparison | Passed: 72 ontology items, 63 price observations and 191 historical observations |
| Batch upload | Multiple PDFs are processed separately and remain selectable | Passed: all ten files completed; one already-stored invoice was correctly deduplicated |
| Invoice switching | Selecting an invoice changes its extracted values, checks, mappings and benchmarks | Passed |
| Native PDF extraction | Text PDFs work without Tesseract or OCR | Passed for all supplied PDFs |
| Extraction confidence | Confidence strictly above 95% is accepted automatically | Passed: 98% rows show `APPROVED`, not `PENDING` |
| Vehicle lookup | Extracted make/model resolves through the static UK lookup where supported | Passed: BMW 320d Sport resolves to group 26-30 / High |
| Calculation checks | Detailed lines, summary-only labour, VAT, MOT and gross total are treated correctly | Passed: synthetic invoices show 18 passed and 1 not applicable; no false labour/subtotal failures |
| Repair-item matching | Comparison creates governed ontology mappings | Passed |
| Mapping confidence | Mapping confidence strictly above 95% needs no redundant handler approval | Passed: high-confidence rows show `APPROVED` / `Accepted` |
| Manual mapping | A no-match row can be changed using a repair-item selector and then approved | Passed end to end; selected invoice remains open after refresh |
| Compare prices button | Button performs comparison before opening findings | Passed |
| P90 minimum history | P90 is withheld until three earlier matching prices exist | Passed: first available on the fourth relevant invoice |
| P90 exclusion | Current invoice is not included in its own benchmark | Passed |
| P90 decision | Current price above P90 is challenged; at or below P90 is within benchmark | Passed |
| P90 evidence | Reviewer can see exact earlier invoice numbers, descriptions and prices | Passed |
| Historical evidence | Details show persisted comparable claims and working source-record links | Passed; source endpoint returned HTTP 200 |
| Challenge decision | Accept, adjust and do-not-challenge controls are correctly gated by mapping approval | Passed: acceptance persisted and remaining-decision count updated |
| Benchmark page | Selected invoice has its own P90 table; global governed history remains separate | Passed |
| Vehicle benchmark quality | Classified and unclassified coverage is explicit | Passed; clean seeded run shows classified vehicle-category rows |
| Layout | Mapping, findings and benchmark screens remain readable without overlapping controls | Passed at desktop viewport; wide evidence tables scroll horizontally |
| Backend regression | Complete automated suite | Passed: 96 tests |
| Frontend regression | TypeScript, ESLint and production build | Passed |

## Business rules retained

- No invoice benchmarks itself.
- A P90 decision requires at least three earlier matching observations.
- Summary-only labour is included in subtotal/VAT/total validation but is not invented as a detailed labour line.
- Bundle prices are not split unless a handler supplies an explicit allocation.
- Low-confidence or unmatched repair items still require a human decision.
- The benchmark dashboard and extraction workflow remain separate modules.

## Handover setup check

1. Copy `.env.example` to the local environment file and add only the approved provider keys.
2. Run the documented database bootstrap before starting the API.
3. Confirm the readiness screen reports active ontology and historical banks.
4. Upload the test batch and confirm invoice switching before demonstrating decisions.
