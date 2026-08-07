# ClaimGuard Product Decisions v1.4

| Field | Value |
|---|---|
| Status | Authoritative for implementation |
| Date | 6 August 2026 (P90 operational-policy addendum) |
| Product | ClaimGuard |
| Market | UK third-party motor liability review and repair-invoice quantum validation |

## 1. Authority and precedence

This document reconciles the ClaimGuard PRD and the downloaded UK Motor Invoice Validation PRD v1.0. When requirements conflict, use this order:

1. The product owner's explicit decisions, including later written changes.
2. This v1.4 decision record.
3. The ClaimGuard PRD for runtime behaviour, terminology, handler workflow and frontend scope.
4. UK Motor Invoice Validation PRD v1.0 for engineering architecture, security, audit, data governance and acceptance-test detail.

No implementation may silently choose a lower-priority rule. Future changes must be recorded in a new version of this decision document and benchmark-policy changes must create a new policy version.

## 2. Product and runtime decisions

| Area | Authoritative decision |
|---|---|
| Runtime input | A claims handler uploads one or more invoice PDFs. Ontology and previous-invoice data are not uploaded per case. |
| Reference banks | Ontology and previous repair/service invoices are seeded once by an admin, stored centrally in SQLite and grown through governed approvals and settlements. |
| Primary journey | Create claim → Human-confirm liability status → Upload → Extraction review → Mapping → Comparison & challenge → Output. Every step is persisted and re-openable. |
| Frontend | React + Vite using the shadcn design language. Use a table-first work surface, restrained status colour and Sheets/dialogs for secondary detail. |
| Supporting screens | Review queue, Ontology manager, Dashboard/Reports and Settings. They remain secondary to the five-step handler journey. |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic and SQLite in WAL mode. Domain logic must not depend on the frontend. |
| Product name | `ClaimGuard`, held in one configuration value so insurer branding can replace it later. |
| Provider strategy | Provider-neutral canonical models and adapters. Licensed Audatex, GT Motive, TecAlliance, Thatcham or insurer data must not require changes to extraction, comparison or UI logic. |

### Mandatory Claim & Liability gate

The latest product clarification adds a mandatory claim and liability section before quantum validation. The invoice pipeline may continue while liability is pending, but final challenge issue is human-gated and must carry the confirmed liability status.

| Area | Authoritative rule |
|---|---|
| Parties | Store the paying insurer/insured driver and the claiming insurer, claims company or third party/driver. |
| Vehicles | Store both vehicles, registrations, policy numbers and roles in the accident. |
| Accident | Store claim number, accident date/location, account, damage description and supporting evidence. |
| Liability statuses | Exactly `ADMITTED`, `DENIED`, `SPLIT LIABILITY`, `PENDING`, or `HUMAN REVIEW REQUIRED`. |
| Decision authority | A claims handler confirms liability. An LLM may summarise evidence or flag contradictions but may not make the final legal fault decision. |
| Invoice limitation | A repair invoice cannot prove the accident or establish fault. It is evidence for vehicle/date/repair consistency and quantum only. |
| Consistency checks | Check claim/invoice VRM and vehicle, invoice date after accident, repairer/vehicle consistency, damage-to-repair plausibility, duplicate invoice hash/number and liability state. |
| Audit | Preserve both the original AI suggestion and every human correction, reason, actor and timestamp. |

The frontend exposes the complete surface through simple grouped navigation: **Claim & Liability**, **Upload & Processing**, **Document Pages**, **Extracted Invoice**, **Calculation Checks**, **Ontology Mapping**, **Price Comparison**, **Missing Items**, **Challenge Review**, **Ontology Bank**, and **Audit & Reports**.

## 3. Locked policy decisions

| Decision | Rule |
|---|---|
| Research approval | A handler may approve a researched ontology item alone during the pilot. One approval creates the item, observation, mapping, audit event and new ontology version. |
| Maker-checker | `two_step_approval: false` by default. The data/state model must support pending second approval so enabling it later is configuration-only. |
| Research trigger | Reviewer-initiated. Missing items show a **Research** action; `auto_research: false` by default. |
| Letter basis | Net figures throughout, with one separate VAT-impact line showing the gross effect. MOT remains outside VAT computation. |
| Operational benchmark | Compare the current invoice line with the interpolated P90 of earlier invoices mapped to the same canonical repair item. The current invoice never enters its own benchmark. Approved ontology prices remain governed mapping/evidence context and are not blended into the operational P90. |
| Minimum challenge | A line is challengeable only when the positive difference is at least £5 **and** exceeds the handler-selected 5% or 10% threshold above P90. |
| Challenge basis | Quantity-adjusted net line total. Unit-price evidence remains visible but is not the monetary challenge basis. |
| Settlement | Final agreed net amount is mandatory per invoice. Line-level settlement allocation is optional. Settled observations enrich the historical bank. |
| Contracted labour | Ask during pilot onboarding whether contracted labour-rate schedules exist. When applicable, a contracted rate overrides an ontology standard labour rate. |

### Operational P90 rules

| Condition | Benchmark behaviour |
|---|---|
| At least three earlier comparable invoice prices | Calculate interpolated P90 and apply the selected percentage threshold plus the £5 minimum variance. |
| Fewer than three earlier comparable invoice prices | Show insufficient history and do not create a P90 challenge. |
| Ontology mapping missing or provisional | Keep the line visible for mapping review; do not mix unrelated descriptions into a benchmark. |
| No reliable mapped history | `REVIEW_REQUIRED` or `NOT_CHALLENGEABLE`; final Challenge Amount is £0. No issued letter may contain the line. |
| Invoice Price below benchmark | Challenge Amount is £0. Underpriced lines never offset challenged lines. |

## 4. Exact terminology

| Term | Required meaning and display rule |
|---|---|
| **Invoice Price** | The quantity-adjusted comparable net amount charged for the current invoice line. |
| **Challenge Price** | The evidence-backed net amount the insurer proposes to pay. For the operational benchmark workflow this is the earlier-invoice P90 at line level and the post-challenge invoice amount at invoice level. |
| **Challenge Amount** | `max(Invoice Price − Challenge Price, 0)`, after the £5-and-selected-percentage eligibility gate. Invoice total is the sum of positive eligible line amounts only. |
| **Challenge Score** | A 0–100 measure of evidence strength/defensibility, never a monetary amount. Overcharge magnitude must not increase this score. |
| **Previous repair & service invoices** | Required label for the seeded historical corpus until records are genuinely insurer-approved, negotiated or settled. Never relabel prior invoices as approved claims. |
| Proposed payable | Explanatory subtext only; it must not replace **Challenge Price** as the headline label. |

Queue priority may combine amount at risk and Challenge Score, but it must be stored and displayed separately from both.

## 5. Comparison presentation

The comparison table must show, per line: Invoice Price, ontology evidence, Previous repair & service invoice statistics, differences versus each source, Challenge Price, Challenge Amount, Challenge Score, reason, approval state and provenance.

Highlighting is evaluated only after the minimum challenge gate:

| State | Rule |
|---|---|
| Red | Eligible line with Challenge Amount ≥ £25 **or** challenge percentage ≥ 25%. |
| Amber | Other eligible line with Challenge Amount ≥ £5 **and** above the currently selected 5% or 10% P90 threshold. |
| Neutral | Below the eligibility gate, below benchmark, not challengeable or awaiting evidence. |

Provisional evidence always carries a visible provisional badge and can support a preview only. It cannot enter an issued negotiation letter until approved.

## 6. Resolved contradictions

| Prior ambiguity or conflict | Resolution |
|---|---|
| Per-case ontology/claims uploads versus fixed reference banks | Runtime accepts PDFs only; reference imports are admin operations. |
| Invoice-only workflow versus full claim workflow | A human-confirmed Claim & Liability gate precedes quantum finalisation. Liability may remain pending during analysis but must be explicit in every output. |
| Streamlit versus React | React/Vite/shadcn is authoritative. FastAPI remains the frontend-independent service boundary. |
| LLM-estimated bundle splits | Forbidden. Split financial amounts only by a deterministic rule or explicit human allocation; otherwise route the bundle to review as non-comparable. |
| Unit price versus line-total challenge | Net line total is authoritative; unit price is supporting evidence. The operational comparison uses the earlier-invoice P90 for that canonical line item. |
| Automated research versus reviewer trigger | Reviewer trigger is the pilot default. |
| Admin-only ontology publication versus handler approval | Handler approval is sufficient in the pilot, with maker-checker configurable. |
| Gross versus net letter figures | Net in evidence and totals; show VAT impact separately. |
| Recommended payable versus Challenge Price | Use **Challenge Price** everywhere; “proposed payable” is explanatory text only. |
| Historical claims wording for seed data | Use **Previous repair & service invoices** and expose the true evidence class. |
| Provisional seed prices versus final letters | Seed observations remain provisional until bulk-reviewed or individually approved; unapproved evidence never enters a letter. |
| Fixed 20% VAT | Seed the current UK rate as an effective-dated regulatory rule. Never permanently hardcode it as the only valid rate. |
| Challenge Score included overcharge magnitude | Remove magnitude from evidence scoring; use it only for challenge calculation and queue priority. |
| Hard-coded model names | Model provider and model ID are configuration. Store model and prompt versions on every AI-assisted result. |

## 7. Engineering invariants retained from v1.0

| Area | Invariant |
|---|---|
| Financial correctness | Use Python `Decimal`, explicit rounding and deterministic code for quantities, VAT, benchmarks, gates and challenge totals. An LLM never performs authoritative arithmetic. |
| Provenance | Every extracted value retains page, raw text, extraction method, confidence and bounding box when available. Clicking a value must reveal its source region. |
| Extraction | Analyse every page. Use native text/table extraction first, OCR/layout repair next and vision only when cheaper tiers fail. Correcting page type/grouping must be possible. |
| Ontology | Canonical item identity is separate from dated price observations, synonyms and vehicle applicability. Prices are appended, never overwritten. |
| Evidence | The LLM is not a price source. Every benchmark must trace to approved ontology evidence, eligible historical evidence or human-approved external evidence. |
| Regulatory rules | VAT rates, MOT treatment and similar limits are effective-dated, sourced and auditable. |
| Audit | Preserve immutable raw extraction, AI suggestion, human decision, before/after values, actor, reason and time. Finalisation and reopening create revisions. |
| Reproducibility | Stamp application/configuration hash, ontology version, policy version, source-import versions, model ID, prompt version and extraction versions. Reprocessing preserves prior runs and provides a delta. |
| Resilience | A page or line failure is isolated, flagged and reviewable; it must not abort an otherwise processable job. |
| Security | Validate file extension, MIME and signature; use safe names and limits; redact/minimise PII sent to cloud models; treat PDF/web content as untrusted data; restrict research to allow-listed adapters; retain DPIA inputs. |
| Data rights | Respect provider licences, terms and access controls. Public observations remain correctly labelled and human-gated. |

## 8. Required outputs

| Output | Requirement |
|---|---|
| Negotiation letter | DOCX and PDF, generated from approved structured facts; all numbers injected by deterministic code. |
| Excel | Invoice summary, pages, extracted lines, checks, mappings, comparisons, challenged items, review, evidence, versions and audit. |
| JSON | Versioned full result graph with schema version and generation time. |
| SQLite | Consistent export copy with schema/application version after pending writes are flushed. |
| Settlement | Mandatory invoice-level agreed amount and optional line allocation. |

## 9. Preserved acceptance suites

Both PRDs' acceptance suites remain mandatory. Where thresholds differ, this v1.4 record controls.

### v1.0 corpus tests

| Test | Preserved expectation |
|---|---|
| AT-001 — `1185790_doc_11857903.pdf` | Analyse three scanned pages, create exactly three invoice units and exercise OCR/vision without merging them. |
| AT-002 — `1381115_doc_13811151.pdf` | Analyse all 20 pages; page 17 is an invoice, page 20 an estimate/order, and non-invoice amounts never enter challenge totals. |
| AT-003 — `1597491_doc_15974912.pdf`, invoice 90538 | Labour £266.00; parts £220.03; taxable subtotal £486.03; VAT £97.21; MOT/non-VAT £54.85; total £638.09. |
| AT-004 — `1643919_doc_16439191.pdf.pdf`, invoice 91283 | Labour £335.00; parts £253.41; taxable subtotal £588.41; VAT £117.68; MOT/non-VAT £54.85; total £760.94. |
| AT-005 — `1646540_doc_16465407.pdf` | Detect image pages, rotate pages 9–12, separate historical records and flag ambiguous rows. |
| AT-006 — no benchmark | No approved reliable evidence means no fabricated price and no final challenge. |
| AT-007 — ontology growth | Approval creates item/observations and a new version, reprocesses the line, preserves the old run and avoids later duplicates. |
| AT-008 — positive-only aggregation | Challenges £25 + £10 + £0 + £40, plus an underpriced line, total exactly £75. |
| AT-009 — provider replacement | A differently shaped provider import maps through an adapter and reprocesses a case without provider-specific core/UI changes. |

### ClaimGuard additions

| Test | Preserved expectation |
|---|---|
| Extraction quality | 100% line extraction on the two clear native invoices; at least 85% on scanned pages. |
| Classification quality | At least 95% invoice/estimate/non-invoice precision; page 17/page 20 classifications above remain exact. |
| Mapping gold set | Seed-bank mappings remain the evaluation gold set; initial target is at least 70% high-confidence auto-map agreement after import. |
| Synthetic overcharge | Inflating two lines on invoice 90538 by 40% challenges only those lines; DB, UI, Excel and letter agree to the penny. |
| Gate behaviour | A below-benchmark line and any line failing either £5 or 5% contribute £0. |
| LLM independence | With no LLM API key, native/table extraction, validation, comparison and challenge math still work for already mapped data. |
| Determinism | Same files and same version stamps reproduce identical deterministic outputs. |
| Performance target | Clean two-page invoice under 60 seconds; mixed 20-page bundle under 4 minutes in the documented test environment. |
| Provenance and approval | 100% of challenged lines show source and policy; zero unapproved external prices in issued letters; zero new ontology items without an authorised human action. |
| Liability gate | Invoice evidence never establishes fault; only a human-confirmed allowed liability status can authorise issue, and original AI advice remains auditable after correction. |

## 10. Definition of implementation alignment

An implementation aligns with v1.4 only when it follows the human-confirmed Claim & Liability gate plus the React/shadcn quantum journey, uses PDF-only handler uploads, applies the locked benchmark and challenge rules, preserves the engineering invariants above, and passes both preserved acceptance suites. A visually complete prototype without the deterministic PDF/database pipeline is not the complete product.
