# Phase 5 — end-to-end verification record

Date: 23 August 2026 · Branch: `phase-1-remediation` · Environment: fresh SQLite database, no LLM key (deterministic fallbacks exercised), native PDF extraction only.

## F1 — Full-corpus intake

26 documents across four cases: the 10-invoice P90 demo set, the 10 CLM-UK engineer/invoice pairs, the 5 original acceptance fixtures, and the bootstrapped pilot case.

| Check | Result |
| --- | --- |
| Documents finishing READY | **26 / 26** |
| FAILED documents | **0** |
| Documents silently discarded | **0** |
| Engineer assessments recognised as separate documents | 5 / 5 |
| `1185790` three scanned pages → three invoice units | Pass (matches documented acceptance) |
| `1381115` 20 pages → invoice + estimate units | Pass |
| `1646540` 12 pages → 8 invoice units, 143 lines | Pass — after fixing a live-found regression |

**Defect found and fixed during this run:** retaining all parsed invoices (the no-discard rule) exposed a `UNIQUE(document_id, document_group_id)` violation when two units in one document parse the same invoice number. Fixed with page-span disambiguation plus a regression test (`tests/integration/test_duplicate_invoice_numbers.py`).

## F2 — Live calculation verification

Against the live API on the P90 corpus (154 lines, 27 challenged case-wide):

| Check | Result |
| --- | --- |
| Hand-recomputation of every decided line (70/30 blend, min(), both gates) at thresholds 5 and 10 | **0 mismatches** in 15 decided lines × 2 thresholds |
| Sum of line challenges equals workspace summary | Pass at both thresholds |
| Every decided line carries the ordered `calculation` breakdown with gate pass/fail | Pass |
| Invalid threshold rejected | Pass — 422 `INVALID_P90_THRESHOLD` |
| Golden pilot case reproduces documented figures on a fresh database | Pass — £643.26 / £546.51 / £96.75 / £19.35 / £116.10 |
| Workspace = export totals | Pinned by `tests/integration/test_p90_price_decision.py` consistency tests |

## F3 — Browser walkthrough (live UI against live API)

| Screen / behaviour | Result |
| --- | --- |
| Documents: upload panel, READY rows, Benchmarking queue / Manual review tabs | Pass |
| Navigation: Claim details page removed; Manual review present under Advanced tools | Pass |
| Benchmarks: P90 aggregate table, threshold selector | Pass |
| Review findings: challenged-only content, honest "P90 not available yet" explanation, decision buttons enabled | Pass |
| Evidence sheet: unified "70% P90 + 30% approved external" decision, evidence detail, comparables | Pass |
| Historical source record opens in-app with real observation data | Pass |
| Manual review hub: both queues render (documents + new item proposals) | Pass |
| Challenge decision: real totals before any decision (no £0.00), liability panel inline | Pass |
| Inline Approve exercised end-to-end: rationale dialog → audit-trail write → row shows Reviewed/Approved, counter 1 of 2 | Pass |
| Browser console errors across entire walkthrough | **None** |

## Standing suites at the end of Phase 5

- Backend: `uv run pytest -m "not slow"` — pass (150+ tests, 1 pre-existing fixture skip).
- Frontend: `npm run typecheck`, `lint`, `test`, `build` — all pass.
- Migrations: `alembic upgrade head` through `20260823_0009`.

## Addendum — full Auda flow with AI enabled (live, 23 Aug 2026)

Provider: OpenRouter `stealth/ox-alpha` (free tier), configured via
`openai_compatible`. Fresh database, real end-to-end run.

| Step | Result |
| --- | --- |
| Rolled-up calculation invoice | **Fully automatic**: AI text tier extracted the priced calculation rows; no manual review needed |
| Comparison with AI adjudicator | `ai_status: used`, no failures |
| Unmatched lines → ontology proposals | All 4 extracted lines auto-staged with provenance |
| One-click approval of "Total Parts" | New ontology version created; mapping went 0 → 4 lines MATCHED on re-compare |
| Governance | Provisional prices contributed no challenges; approved observation priced its line correctly (billed = observed → Within) |
| AI briefings | Real (fallback = false) and accurate — the Full Report briefing identified the assessment number, repairer, and vehicle; the photo-page briefing flagged poor scan quality and listed what a reviewer should verify |
| Failure handling observed | One `LLM_INVALID_EXTRACTION` on the assessment schema degraded gracefully to manual review; free-tier 429 rate limits never failed a document |

Hardening that came out of this run: tolerant JSON parsing and schema-in-prompt
for loosely-conforming models; internal exceptions no longer leak to the UI;
AI degradation now surfaces as a calm informational notice after comparisons
and document batches.

## Outside the scope of this run (client inputs still required)

- The Auda 2–7 format/invoice PDFs and `certificate.pdf` exist only on the client machine; the LLM text tier and briefing fallbacks that handle them are covered by unit/integration tests but not yet by those exact files.
- LLM-backed extraction, adjudication, and briefings ran in fallback mode (no API key). Configure a key per `docs/CLIENT_MACHINE_SETUP.md` to activate them.
- Pricing formula sign-off (`docs/PRICING_FORMULA_DECISION.md`); Option A is live as the default.
