# ClaimGuard

ClaimGuard is a UK motor-claims invoice validation and price-challenge pilot. A handler confirms liability, uploads repair invoices, reviews extraction and ontology mapping, compares each net line against governed evidence, and issues an auditable challenge only after human approval.

The project is a working full-stack implementation: a React/Vite interface in the shadcn design language, a FastAPI service, deterministic comparison logic, an optional schema-constrained hosted LLM boundary, a SQLite audit store, native PDF/Azure OCR processing, and JSON/XLSX/SQLite/DOCX/PDF outputs.

## What ClaimGuard does

ClaimGuard is an invoice-checking assistant for UK motor insurance claims. It reads repair invoices, checks every line against approved and historical prices, explains potential overcharges, and helps a claims handler create an evidence-backed challenge package. **ClaimGuard recommends; the human handler makes the final decision.**

| Example result | Amount |
| -------------- | -----: |
| Garage invoice — net | £643.26 |
| Challenge Price — proposed payable | £546.51 |
| Potential net saving | £96.75 |
| VAT impact | Shown separately |
| MOT | Kept outside VAT calculations |

The primary user is an insurer's claims handler. The everyday workflow is organised into five plain-language screens:

| Screen | What the handler does |
| ------ | --------------------- |
| **Documents** | Uploads PDFs or Excel files and reviews processing, classification and extracted invoice data. |
| **Benchmarks** | Reviews aggregate invoice history and compares the selected invoice against P90 without including that invoice in its own benchmark. |
| **Review findings** | Accepts, adjusts or rejects each challenged line with its supporting price evidence visible. |
| **Challenge decision** | Confirms the financial summary and generates the challenge letter, evidence schedule and audit record. |
| **Summary** | Understands the claim, current stage, Challenge Price, potential saving and next action. |

The Documents screen accepts one PDF, several PDFs, or a folder. Every invoice remains separately selectable while the benchmarking module aggregates approved evidence across the uploaded set. Extracted vehicle makes/models are also matched against the supplied static UK insurance-group lookup; unmatched vehicles are explicitly sent to manual review rather than guessed.

### Uploaded-invoice P90 benchmarking

The **Benchmarks** screen normalizes equivalent descriptions, combines approved line prices from stored invoices, calculates the interpolated 90th percentile (`PERCENTILE.INC`), and excludes the invoice currently being reviewed from its own benchmark. The selected threshold is shared with Review findings and Challenge decision.

### External UK benchmark research

ClaimGuard also includes a small, governed research import for source-backed UK market observations. The included GOV.UK MOT and Honda UK alignment rows are stored through the existing source-provider/import/price-observation model and shown with direct provenance in **Ontology Bank → Price observations**. They remain **provisional** and do not change P90, supported prices, or challenge decisions until a business owner approves source priority and the runtime rule. See [`docs/UK_EXTERNAL_BENCHMARK_RESEARCH.md`](docs/UK_EXTERNAL_BENCHMARK_RESEARCH.md) for the source-access matrix, scope limitations, exact staged values, and next decision.

| Rule | Result |
| ---- | ------ |
| Current line price does not exceed both gates | **Within threshold** — no P90 challenge |
| Current line price is more than the selected percentage above P90 and at least £5 higher | **Challenge** — difference and percentage are explained |
| Information button | Shows every earlier invoice number, original description, date and price used |

The default P90 percentage gate is 10%; the handler can switch it to 5% on the Benchmarks screen. The existing governed 60/40 ontology-and-historical comparison, handler mapping approval and final challenge controls remain unchanged.

Specialist tools—including page classification, extraction review, calculation checks, ontology mapping, missing-item research and ontology management—remain available under **Advanced tools**. No capability is removed from the simplified handler workflow.

For the complete beginner-friendly handover—including the product, user journey, UI/UX, architecture, database, folder structure, setup, testing and production boundaries—use the [ClaimGuard Beginner Handbook](docs/CLAIMGUARD_BEGINNER_HANDBOOK.md).

For a shorter plain-English product walkthrough, see [`docs/PRODUCT_OVERVIEW.md`](docs/PRODUCT_OVERVIEW.md).

## Product rules at a glance

| Area              | Pilot rule                                                                                                                                      |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| Liability         | The invoice never decides fault. A handler must confirm exactly `ADMITTED`, `DENIED`, `SPLIT LIABILITY`, `PENDING`, or `HUMAN REVIEW REQUIRED`. |
| Issue gate        | Analysis may continue in draft; a challenge can be issued only for human-confirmed `ADMITTED` or `SPLIT LIABILITY`.                             |
| Benchmark         | 60% approved ontology + 40% eligible historical weighted median; policy fallbacks are versioned.                                                |
| Challenge gate    | Positive difference must be at least **£5 and 5%** of the quantity-adjusted net line total.                                                     |
| Terminology       | **Challenge Price** is the headline; “proposed payable” is supporting text only.                                                                |
| VAT and MOT       | Evidence and challenge figures are net; VAT impact is separate; MOT remains outside VAT.                                                        |
| Research          | Handler-initiated by default (`auto_research=false`); handler approval is sufficient in the pilot (`two_step_approval=false`).                  |
| Settlement        | Invoice-level agreed net amount is mandatory; line-level allocation is optional.                                                                |
| Contracted labour | Ask during insurer onboarding; a supplied contractual labour schedule overrides ontology labour rates.                                          |

## Quick start

### Client: run the handed-over project

Install Node.js 20+, Python 3.11+ and [uv](https://docs.astral.sh/uv/). Tesseract is not required for the company-laptop setup. Unzip the handover, open Terminal in the `claim-guard` folder, then run:

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
uv run claimguard-bootstrap
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep that terminal open. Open a second terminal in the same `claim-guard` folder and run:

```bash
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173). The bundled demo works without an AI key. To enable the hosted Gemini adjudicator, add `CLAIM_GUARD_LLM_API_KEY=...` to `backend/.env` and restart FastAPI.

For scanned invoices, configure the company-provided Azure AI Document Intelligence endpoint and key in `backend/.env`:

```dotenv
CLAIM_GUARD_DOCUMENT_OCR_PROVIDER=azure
CLAIM_GUARD_AZURE_DOCUMENT_ENDPOINT=https://your-resource.cognitiveservices.azure.com
CLAIM_GUARD_AZURE_DOCUMENT_API_KEY=your-company-key
CLAIM_GUARD_AZURE_DOCUMENT_MODEL=prebuilt-layout
```

Restart FastAPI and open `http://localhost:8000/health`; `ocr_provider` should read `azure` and `ocr_status` should read `azure_configured`. The model value must be exactly `prebuilt-layout`. With Azure selected, scanned invoices never fall through to local Tesseract. To install local Tesseract support only on a suitable development machine, use `uv sync --extra local-ocr`.

For a database created before source highlighting was added, run this once from `backend/` after the migration:

```bash
uv run python scripts/reprocess_source_regions.py
```

This backfills page and field coordinates while preserving reviewed invoice lines and audit history.

| Step | Command                                                     | Outcome                                                                                                                                                                |
| ---: | ----------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
|    1 | Install Python 3.11+, `uv`, and Node.js 20+                  | Azure Document Intelligence handles scanned documents on company laptops; local Tesseract is optional.                                                         |
|    2 | `cp .env.example .env`                                      | Uses the local Vite API proxy; set `VITE_API_URL` only for a separately hosted API.                                                                                    |
|    3 | `cd backend && cp .env.example .env && uv sync --extra dev` | Creates the backend environment and installs runtime plus test dependencies.                                                                                           |
|    4 | `uv run alembic upgrade head`                               | Applies the managed SQLAlchemy schema migration. Run from `backend/`.                                                                                                  |
|    5 | `uv run claimguard-bootstrap`                               | Idempotently imports the supplied seed workbooks and builds pilot case `CG-2026-0048`. Run from `backend/`.                                                            |
|    6 | `uv run uvicorn app.main:app --reload`                      | Starts FastAPI at `http://localhost:8000`.                                                                                                                             |
|    7 | In another terminal: `npm install && npm run dev`           | Starts the UI at `http://localhost:5173`.                                                                                                                              |

| Local endpoint       | URL                                                                                                                      |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| ClaimGuard UI        | [http://localhost:5173](http://localhost:5173)                                                                           |
| API documentation    | [http://localhost:8000/docs](http://localhost:8000/docs)                                                                 |
| Health check         | [http://localhost:8000/health](http://localhost:8000/health)                                                             |
| Pilot workspace JSON | [http://localhost:8000/api/v1/claims/CG-2026-0048/workspace](http://localhost:8000/api/v1/claims/CG-2026-0048/workspace) |

When `VITE_API_URL` is empty, Vite proxies `/api` and `/health` to the local FastAPI service. If that API is unavailable, the UI displays the connection failure instead of silently presenting demo data as a live result. Governed XLSX, SQLite, DOCX and PDF outputs require the live API.

## Supplied pilot data

The handover includes these fixtures in `sample-data/`, so bootstrap and demo setup do not depend on the original developer's computer.

| Source                         | Verified acceptance expectation                                                                                                                  |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| `1185790_doc_11857903.pdf`     | Three scanned invoice pages remain three invoice units.                                                                                          |
| `1381115_doc_13811151.pdf`     | All 20 pages are analysed; page 17 is an invoice and page 20 is an estimate/order excluded from challenge totals.                                |
| `1597491_doc_15974912.pdf`     | Invoice 90538: labour £266.00; parts £220.03; taxable £486.03; VAT £97.21; MOT £54.85; gross £638.09.                                            |
| `1643919_doc_16439191.pdf.pdf` | Invoice 91283: 18 lines; labour £335.00; parts £253.41; taxable £588.41; VAT £117.68; MOT £54.85; gross £760.94. This is the default pilot case. |
| `1646540_doc_16465407.pdf`     | Image pages are detected, pages 9–12 are rotation-corrected, and ambiguous historical rows are flagged.                                          |
| `ontology_seed.xlsx`           | 72 ontology items imported; 63 have price observations and all seed observations remain provisional pending approval.                            |
| `historical_claims_seed.xlsx`  | 191 runtime observations imported; 34 gold-set rows are kept out of live benchmark evidence.                                                     |

### Bootstrapped comparison snapshot

| Metric                             |                               Result |
| ---------------------------------- | -----------------------------------: |
| Extracted invoice lines            |                                   18 |
| Ontology mappings                  | 17 review mappings + 1 safe no-match |
| Eligible historical comparables    |                                   86 |
| Positive challenge lines           |                                    2 |
| Original net invoice including MOT |                              £643.26 |
| Challenge Price                    |                              £546.51 |
| Net Challenge Amount               |                               £96.75 |
| VAT impact                         |                               £19.35 |
| Gross cash effect                  |                              £116.10 |
| Evidence strength                  |                             71 / 100 |

The bootstrapped case deliberately remains unfinalised: its mappings/evidence require handler decisions. JSON, Excel, and SQLite audit exports are available immediately; negotiation DOCX/PDF endpoints correctly return `409` until positive challenge lines are approved and the issue gate passes. This is a governance control, not a missing export feature.

## Architecture

| Layer       | Implementation                                         | Responsibility                                                                                                                          |
| ----------- | ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Reviewer UI | React 19, TypeScript, Vite, Tailwind CSS, shadcn/Radix | Four-screen handler workflow, shared invoice split-view, source highlighting, specialist tools, evidence detail, and report downloads. |
| API         | FastAPI, Pydantic v2                                   | Versioned claim, liability, upload, processing, research, approval, comparison, settlement, finalisation, workspace, and report routes. |
| Persistence | SQLAlchemy 2 + SQLite                                  | Relational case graph, immutable audit events, version stamps, WAL mode, foreign keys, busy timeout, and consistent online backup.      |
| Extraction  | PyMuPDF, pdfplumber, Pillow, Azure Document Intelligence | Native text/table extraction first, hosted OCR for scans, page provenance, source highlighting, and optional local Tesseract fallback. |
| Comparison  | Python `Decimal`, RapidFuzz, versioned policy YAML     | Deterministic mapping support, evidence eligibility, weighted benchmarks, £5/5% gates, VAT treatment, and replayable results.           |
| Research    | Provider-neutral adapter workflow                      | Explicit handler trigger, captured source evidence, one-click pilot approval, and configurable maker-checker state.                     |
| Reporting   | openpyxl, python-docx, ReportLab/LibreOffice           | Full result JSON, 12-sheet Excel, SQLite snapshot, and gated negotiation letters in DOCX/PDF.                                           |

| Repository area                  | Purpose                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------ |
| `src/features/claim-guard/`      | ClaimGuard screens, workspace contract, and demo data.                         |
| `src/components/ui/`             | shadcn UI primitives.                                                          |
| `backend/app/api/`               | FastAPI request boundary.                                                      |
| `backend/app/extraction/`        | PDF classification, native extraction, OCR, and provenance.                    |
| `backend/app/data_sources/`      | Provider-neutral Excel and future provider adapter contracts.                  |
| `backend/app/llm/`               | Schema-constrained optional model boundary; deterministic mode remains default. |
| `backend/app/security/`          | External-model redaction and prompt-injection safeguards.                      |
| `backend/app/services/`          | Seed import, document processing, comparison, research, and case result graph. |
| `backend/app/exports/`           | JSON, XLSX, SQLite, DOCX, and PDF generation.                                  |
| `backend/alembic/`               | Managed SQLite schema migrations.                                              |
| `backend/tests/`                 | Unit, integration, native-PDF, OCR, rotation, and seed acceptance suites.      |
| `docs/PRODUCT_DECISIONS_V1_4.md` | Authoritative reconciled product decision record.                              |
| `docs/SECURITY_AND_DPIA.md`      | Pilot security controls, production blockers, and DPIA checklist.              |

## Governance and finalisation

| Gate                   | Enforced behaviour                                                                                                                                             |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Liability authority    | AI advice and human correction are stored separately; only the handler's confirmation controls issue.                                                          |
| Evidence eligibility   | Provisional or unapproved external prices may support review but cannot enter an issued letter.                                                                |
| Historical sufficiency | A positive line using provisional ontology evidence needs at least three eligible historical comparables before challenge approval.                            |
| Line review            | Every positive Challenge Amount must be reviewed before case finalisation.                                                                                     |
| Research approval      | One handler approval writes the pilot item, observation, mapping, audit event, and new ontology version; maker-checker can be enabled without a schema change. |
| Arithmetic             | Quantities, VAT, benchmarks, thresholds, and totals are deterministic `Decimal` calculations; an LLM is never the source of authoritative arithmetic or price. |
| Extraction review      | Items below the configurable 90% threshold require Accept, Edit or Reject; rejected lines stay audited but leave calculations and mapping.                     |
| Reproducibility        | Outputs retain processing, ontology, policy, import, extraction, model, and prompt versions; reprocessing preserves prior runs.                                |

## Reports

For case `CG-2026-0048`, request `GET /api/v1/claims/CG-2026-0048/reports/{format}`.

| Format   | Contents                                                                                                                   | Availability                          |
| -------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| `json`   | Versioned complete result graph and provenance.                                                                            | Draft and final                       |
| `xlsx`   | Claim, Liability, Invoices, Pages, Lines, Checks, Mappings, Comparisons, Challenges, Evidence, Versions, and Audit sheets. | Draft and final                       |
| `sqlite` | Consistent backup of the complete local pilot database, including committed WAL content and audit records.                 | Draft and final; local/admin use only |
| `docx`   | Negotiation letter built only from approved structured facts.                                                              | After successful case finalisation    |
| `pdf`    | Negotiation letter via LibreOffice when available, with a deterministic ReportLab fallback.                                | After successful case finalisation    |

Generated files are written beneath `backend/data/exports/<case-reference>/`. Runtime data is intentionally git-ignored.

## Deployment boundary

| Boundary             | Pilot position                                                                                                                                                |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Intended environment | Single-machine, trusted local evaluation. Keep Uvicorn bound to `127.0.0.1`.                                                                                  |
| Identity             | Actor names are captured for audit, but authentication and insurer SSO/RBAC are not part of this local build.                                                 |
| Network deployment   | Do not expose this pilot to a shared or public network until authenticated handler identity, Reviewer/Admin authorization and CSRF/security review are added. |
| SQLite export        | The backup contains every case in the local database, not a case-filtered subset; treat it as an admin artifact.                                              |
| Long-lived data      | Alembic migrations and portable backups are included; insurer retention, encrypted backup storage and restore scheduling remain deployment responsibilities.  |

## Verification

| Scope                | Command                                     | Notes                                                                                                            |
| -------------------- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Frontend lint        | `npm run lint`                              | ESLint across the React/TypeScript app.                                                                          |
| Frontend type/build  | `npm run build`                             | Runs TypeScript project build and production Vite bundling.                                                      |
| Backend lint         | `cd backend && uv run ruff check app tests` | Python style and correctness checks.                                                                             |
| Fast backend suite   | `cd backend && uv run pytest -m "not slow"` | Unit and integration coverage without large OCR fixtures.                                                        |
| OCR acceptance suite | `cd backend && uv run pytest -m slow`       | Uses the configured OCR provider and any supplied large fixtures; local-only tests may require the optional Tesseract extra.            |
| Full backend suite   | `cd backend && uv run pytest`               | Runs all available tests; missing external fixture/tool prerequisites may cause marked acceptance tests to skip. |
| Migration replay     | `cd backend && uv run alembic upgrade head` | Applies or safely replays the current managed schema revision.                                                       |
| Bootstrap replay     | `cd backend && uv run claimguard-bootstrap` | Re-running creates no duplicate seed, case, document, or comparison records.                                     |

## Configuration

| File                   | Purpose                                                                   |
| ---------------------- | ------------------------------------------------------------------------- |
| `.env.example`         | Frontend API origin (`VITE_API_URL`).                                     |
| `backend/.env.example` | Database, storage, upload, SQLite, CORS, research, and approval defaults. |

All backend settings use the `CLAIM_GUARD_` prefix. SQLite schema creation and default configuration seeding occur at API startup unless disabled. The default database is `backend/data/claim_guard.db`.

The static `vehicle_category_lookup` dataset is seeded idempotently at startup from [`sample-data/vehicle_category_lookup.csv`](sample-data/vehicle_category_lookup.csv). It stores the supplied make/model, normalized aliases, insurance group range/category, body type, fuel type and source. Matching proceeds from exact make/model to alias and model-family matches; no match returns `manual_review`. Insurance group is deliberately stored separately from vehicle body type and official classification.

To expand the supplied 45-model catalogue after handover, add CSV rows using the same columns, keep multiple aliases separated with `|`, then run:

```bash
cd backend
uv run claimguard-import-vehicle-lookup ../sample-data/vehicle_category_lookup.csv
```

The import is safe to repeat: normalized make/model matches are updated and new models are added. Existing extracted vehicles are reclassified immediately; unmatched vehicles remain in manual review.

### Hosted AI setup

ClaimGuard supports the Gemini Developer API free tier for ontology mapping adjudication. Create a key in [Google AI Studio](https://aistudio.google.com/app/apikey), then add it only to `backend/.env`:

```dotenv
CLAIM_GUARD_LLM_PROVIDER=gemini
CLAIM_GUARD_LLM_MODEL=gemini-2.5-flash-lite
CLAIM_GUARD_LLM_API_KEY=your_personal_key_here
```

| State | Runtime behaviour |
| ----- | ----------------- |
| Key configured | Gemini chooses one candidate retrieved by deterministic code, or returns no-match, using a strict JSON schema. |
| Key missing | The health response reports `configuration_required`; comparison remains fully usable in deterministic mode. |
| Timeout, invalid response, or free-tier limit | The failure code is retained in the comparison result and mapping flags; that run safely continues in deterministic mode. |
| Provider changed later | Implement the same `StructuredLLMClient` boundary; comparison and financial code do not change. |

Azure AI and Azure OpenAI are also supported through the same boundary. They are
not the same service as Azure Document Intelligence: Document Intelligence performs
OCR/layout extraction, while an image-capable LLM is an optional fallback for pages
that OCR or deterministic parsing cannot make usable.

```dotenv
CLAIM_GUARD_LLM_PROVIDER=azure_openai
CLAIM_GUARD_LLM_MODEL=your-text-model-or-deployment
CLAIM_GUARD_LLM_VISION_MODEL=your-image-capable-model-or-deployment
CLAIM_GUARD_LLM_API_KEY=your_rotated_secret
CLAIM_GUARD_LLM_BASE_URL=https://your-resource.services.ai.azure.com
CLAIM_GUARD_LLM_API_VERSION=2024-05-01-preview
CLAIM_GUARD_LLM_VISION_ENABLED=true
```

| Extraction layer | Behaviour |
| ---------------- | --------- |
| Native PDF / Azure layout | Runs first and remains authoritative when it produces usable fields and lines. |
| Vision fallback | Receives rendered page images only when the normal extraction is incomplete or unreadable. |
| Local validation | Rejects malformed, negative, out-of-range, zero-price, or wrong-page line items and recalculates arithmetic independently. |
| Human review | Vision confidence is capped below automatic approval, so extracted values remain reviewable. |

Keep `CLAIM_GUARD_LLM_VISION_ENABLED=false` until the configured model deployment is
confirmed to accept image inputs. A failed or invalid model response does not overwrite
a successful deterministic extraction, and comparison never uses invented prices.

The API key is sent only from FastAPI to the configured provider and is never included in frontend code, prompts, audit payloads, or error messages. Mapping receives redacted invoice descriptions plus an allow-list of retrieved ontology candidates. Vision receives bounded rendered pages and untrusted extracted text only when fallback is required. Neither path can create authoritative prices or calculate VAT, benchmarks, Challenge Price, or settlement totals.

Research evidence is accepted only from the hostname patterns in the versioned `CLAIM_GUARD_RESEARCH_SOURCE_ALLOWLISTS` map. The checked-in `*.example.test` entry is deliberately a non-production placeholder; replace it with insurer-approved UK supplier/provider hosts before enabling a real research adapter.

The local pilot contract is fixed to `/api/v1`, GBP and UK. `CLAIM_GUARD_AUTO_RESEARCH` must remain `false` until an insurer-approved retrieval provider is integrated; the shipped workflow deliberately accepts reviewer-triggered structured evidence only.

## PRD authority

| Authority                                                                                               | Follow it for                                                                                                                                           |
| ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Explicit product-owner decisions and [`docs/PRODUCT_DECISIONS_V1_4.md`](docs/PRODUCT_DECISIONS_V1_4.md) | Product behaviour, terminology, liability and human gates, evidence weights, thresholds, handler workflow, UI scope, settlement, and research approval. |
| ClaimGuard product PRD                                                                                  | Runtime journey and user experience where v1.4 does not override it.                                                                                    |
| Downloaded UK Motor Invoice Validation PRD v1.0                                                         | Technical architecture, security, audit, data governance, resilience, and detailed acceptance tests.                                                    |

In short: **v1.4 is the product authority; the longer v1.0 is the engineering and assurance authority.** A lower-priority document never silently overrides a higher-priority decision.
