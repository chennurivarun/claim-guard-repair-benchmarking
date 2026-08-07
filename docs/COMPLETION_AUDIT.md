# ClaimGuard completion audit

| Field | Result |
| --- | --- |
| Audit date | 6 August 2026 |
| Product authority | Product decisions v1.4, then ClaimGuard PRD, then UK Motor Invoice Validation PRD v1.0 |
| Implementation verdict | Complete for the documented single-machine pilot |
| Production verdict | Not approved for shared/public insurer deployment until the controls in `SECURITY_AND_DPIA.md` are completed |

## Definition-of-done trace

| # | PRD completion condition | Status | Implementation or proof |
| ---: | --- | --- | --- |
| 1 | Start from documented commands | Pass | Root `README.md` documents install, migration, bootstrap, API and UI commands. |
| 2 | Upload and validate all required/optional input roles | Pass with authoritative v1.4 override | Handler runtime accepts current invoice PDFs only. Ontology and previous-invoice workbooks are validated admin seed imports, as explicitly required by the later product decision. |
| 3 | Process and display every page of all five PDFs | Pass | Native, scanned, mixed 20-page and rotated-bundle acceptance tests pass; Document Pages exposes the persisted page payload. |
| 4 | AT-001 through AT-009 | Pass | See the acceptance trace below. |
| 5 | Native, OCR and rotation paths | Pass | Full backend suite exercises all three paths against the supplied Downloads fixtures. |
| 6 | Exact clear-invoice totals | Pass | Invoices 90538 and 91283 match their expected labour, parts, VAT, MOT and gross totals. |
| 7 | Page/source provenance per line | Pass | Lines retain page, raw description, method, confidence and bounding box when the source exposes coordinates. |
| 8 | Validated and versioned ontology imports | Pass | Excel adapter validates rows, isolates the gold set and publishes immutable ontology versions. |
| 9 | Candidate-constrained LLM mapping | Pass | Strict Pydantic output accepts a supplied ontology ID or `NO_MATCH`; invented IDs and malformed output retry then fail safely. End-to-end persistence is tested. |
| 10 | No LLM arithmetic or untraceable final price | Pass | `Decimal` domain code owns quantity, benchmarks, gates, VAT and totals; issued letters require approved, traceable evidence. |
| 11 | Governed missing-item research | Pass | Reviewer-triggered research, allow-list validation, approval, new item/observation/version, remapping and immutable reprocessing are tested. |
| 12 | Separate invoice, ontology and historical prices | Pass | Price Comparison and exported result rows expose each evidence source separately, with differences and provenance. |
| 13 | Positive-only net/VAT/gross calculations | Pass | Unit and integration tests cover the £5-and-5% gate, no negative offset, separate VAT impact and MOT exclusion. |
| 14 | Evidence strength separate from amount | Pass | Challenge Score is an independent 0–100 evidence measure; queue/amount fields remain separate. |
| 15 | Approve, reject and edit consequential decisions | Pass | Challenge Review provides per-line Accept, Edit and Reject with mandatory rationale; mapping, research, liability and finalisation remain human-gated. |
| 16 | Audit prior AI output and human changes | Pass | Append-only audit events preserve actor, reason, before/after values and hashes for new events; older bootstrap events are visibly labelled legacy unsealed. |
| 17 | Consistent JSON, Excel and SQLite downloads | Pass | Export tests validate the full result graph, 12-sheet XLSX and consistent SQLite online backup. Governed DOCX/PDF letters are also implemented. |
| 18 | Provider adapter replacement | Pass | Canonical adapter protocol and registry include Excel plus future provider boundaries; a differently named replacement adapter runs without core/UI changes. |
| 19 | Immutable reprocessing and delta | Pass | Reprocessing creates a new processing/mapping/comparison run, keeps the old run, stamps versions and returns summary changes. |
| 20 | Security, redaction, prompt-injection defence and DPIA | Pass for pilot documentation | PDF signature/size validation, PII redaction, untrusted-text framing, injection flags, allow-listed research and the security/DPIA checklist are present and tested. |

## Acceptance-test trace

| Test | Status | Evidence |
| --- | --- | --- |
| AT-001 — three scanned invoices | Pass | `test_three_scanned_pages_become_three_invoice_units` scans three pages, uses OCR and preserves three invoice units. |
| AT-002 — mixed 20-page bundle | Pass | `test_twenty_page_bundle_finds_invoice_and_estimate` processes all pages, identifies page 17 as invoice and page 20 as estimate/order. |
| AT-003 — invoice 90538 | Pass | Parameterised native-invoice acceptance verifies £266.00 labour, £220.03 parts, £486.03 taxable, £97.21 VAT, £54.85 MOT and £638.09 gross. |
| AT-004 — invoice 91283 | Pass | Parameterised native-invoice acceptance verifies £335.00 labour, £253.41 parts, £588.41 taxable, £117.68 VAT, £54.85 MOT and £760.94 gross. |
| AT-005 — rotated MINI history | Pass | `test_rotated_service_book_sequence_is_preserved` detects image pages, corrects pages 9–12 and preserves record order/review flags. |
| AT-006 — no fabricated benchmark | Pass | Comparison-engine tests return review/not-challengeable and zero when approved evidence is unavailable. |
| AT-007 — ontology growth | Pass | Research workflow tests create governed evidence/version, remap into a new immutable run and prevent duplicate growth. |
| AT-008 — positive-only aggregation | Pass | Aggregation tests prove £25 + £10 + £0 + £40 with an underpriced line equals £75. |
| AT-009 — provider replacement | Pass | Replacement adapter tests import the canonical bundle and reprocess without provider-specific comparison or UI code. |

## Final verification record

| Check | Result |
| --- | --- |
| Backend full suite | **100 passed** on 6 August 2026, including benchmark aggregation, rolling-P90 exclusion, repairer grouping, native PDF, OCR and rotation fixtures |
| Python static checks | Ruff passed across `app`, `tests` and `alembic` |
| Frontend lint | ESLint passed |
| Frontend production build | TypeScript and Vite build passed; only a non-blocking 500 kB chunk-size advisory remains |
| Migration replay | Fresh SQLite database upgraded to Alembic `20260717_0001 (head)` with 38 tables including Alembic metadata |
| Live UI check | API-connected primary and advanced journeys, invoice switching, per-line challenge decisions, exact benchmark evidence, source-invoice drill-down, repairer knowledge graph, ontology bank and audit report verified without console/network errors at desktop and mobile widths |
| Cross-view benchmark consistency | Benchmark summary, Review Findings and the repairer graph use the same uploaded-batch rolling-P90 service, exclude the current invoice and apply the selected 5%/10% threshold plus the £5 materiality gate |
| Demonstration invoice pack | Two originals plus eight controlled variants are supplied; synonyms exercise ontology normalisation and four synthetic repairers make cross-repairer graph patterns demonstrable |
| Pilot comparison snapshot | 18 lines, 17 mappings plus one no-match, 86 comparables, two challenged lines, £96.75 net challenge, £19.35 VAT impact, £116.10 gross effect |

## Deliberate pilot boundaries

| Boundary | Required before production |
| --- | --- |
| Authentication and authorization | Insurer SSO, verified handler identity and role-based access for Handler, Reviewer and Admin |
| Deployment | TLS/reverse proxy, secrets management, CSRF review, hardened headers, monitoring and backup/restore operations |
| Privacy | Insurer-approved DPIA, retention/deletion policy, processor records and approval of any cloud-model data path |
| Licensed evidence | Replace placeholder research hosts and future provider stubs with contracted, allow-listed sources and documented usage rights |
| Data store | SQLite is appropriate for this trusted local pilot; evaluate PostgreSQL and tenant isolation before concurrent multi-user use |
