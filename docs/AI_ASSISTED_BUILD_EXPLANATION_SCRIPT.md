# How I Built ClaimGuard Using AI Tools

This is a speaking script for explaining the project to a client, interviewer or technical reviewer. Do not memorise every word. Understand the sequence and explain it naturally.

## 30-second answer

> I built ClaimGuard as an AI-assisted full-stack project. I first converted the motor-claims requirements into a clear workflow and fixed business rules. I used AI tools to help analyse the PRD, explore design options, generate implementation drafts and review the code. The application itself uses React and shadcn for the interface, FastAPI for the backend, SQLite for the pilot database and a PDF/OCR pipeline for invoice extraction. The important financial calculations are deterministic Python rules, not AI guesses. AI is optional and only assists with mapping unclear invoice descriptions to governed ontology items. I reviewed the output, tested the workflows and documented the complete handover.

## Two-minute explanation

> I started with the product requirements rather than immediately generating code. The main problem was to help a UK motor-claims handler read repair invoices, compare every net line against governed price evidence and create an auditable price challenge.
>
> I used AI as a development assistant in several stages. First, it helped me analyse the PRD, identify unclear decisions and turn the requirements into user journeys, screens, data entities and acceptance rules. I then confirmed decisions such as using net line totals, showing VAT separately, keeping MOT outside VAT and requiring human approval before issuing a challenge.
>
> For the frontend, I used React, TypeScript, Vite, Tailwind CSS and shadcn components. I used AI to help create and review component structures, but I kept the user journey simple: Overview, Documents, Review findings and Approve challenge. Specialist functions are grouped under Administration so a first-time handler is not overloaded.
>
> For the backend, I used FastAPI, SQLAlchemy, Alembic and SQLite. The backend manages claims, documents, extracted invoice lines, ontology mappings, evidence, challenge decisions, settlement and audit history. SQLite keeps the pilot easy to run, and the database layer can later move to PostgreSQL for production.
>
> The document pipeline accepts repair-invoice PDFs. It uses PyMuPDF and pdfplumber for native text, Pillow and Tesseract for scanned pages, and validation rules to extract invoice details and line items. Every page and extracted value retains provenance so a reviewer can trace it back to the source.
>
> The financial engine is deterministic. It uses Decimal arithmetic, versioned policy rules and approved or historical evidence to calculate the benchmark, Challenge Price and potential saving. AI does not calculate money, VAT or liability. An optional hosted Gemini model can help choose between already-retrieved ontology candidates, but it cannot invent ontology IDs or prices. Low-confidence cases remain for human review.
>
> Finally, I used AI-assisted testing and review to find errors, check edge cases, improve the UI wording and prepare the documentation. I still inspected the code, ran the frontend build and backend tests, verified the PDF outputs and made the final product decisions. So AI accelerated the work, but the architecture, business rules, verification and responsibility remained under human control.

## Full explanation by build stage

| Stage | What I did | How AI helped | What remained under my control |
|---|---|---|---|
| Requirements | Read the PRD and converted it into workflows and rules | Summarised requirements, exposed ambiguities and suggested questions | Final interpretation and product decisions |
| Product design | Defined handler screens, administration screens and navigation | Generated alternatives and reviewed first-time-user clarity | Selected the final UX and terminology |
| Architecture | Separated browser, API, services, database and document pipeline | Compared technical approaches and drafted architecture | Chose the stack and safety boundaries |
| Frontend | Built the React and shadcn interface | Drafted components, states, copy and refactoring suggestions | Reviewed behaviour, consistency and usability |
| Backend | Built FastAPI routes, services and data models | Drafted implementation patterns and helped diagnose errors | Defined domain behaviour and approved code changes |
| PDF pipeline | Added native-PDF extraction, OCR fallback and validation | Suggested parsing and edge-case handling | Verified extracted data and failure behaviour |
| Price comparison | Implemented benchmarks, gates and Challenge Price | Helped translate policy language into testable rules | Kept calculations deterministic and approved formulas |
| Optional AI feature | Added constrained ontology-candidate adjudication | Helps rank or choose from retrieved candidates | No invented items, prices or financial decisions |
| Testing | Ran builds, API tests, rule tests and output checks | Suggested cases and helped interpret failures | Executed checks and accepted only verified results |
| Documentation | Produced README, product handbook and handover material | Helped organise and simplify explanations | Verified that documentation matches the product |

## The development flow

Use this sequence when somebody asks how the work progressed:

1. I analysed the PRD and listed missing decisions.
2. I confirmed the business terminology and financial rules.
3. I converted the claim journey into screens and backend states.
4. I designed the data model and API boundaries.
5. I built the PDF extraction and invoice-normalisation pipeline.
6. I implemented deterministic mapping retrieval and price comparison.
7. I added optional constrained AI assistance for ambiguous mapping.
8. I built the handler UI using reusable shadcn components.
9. I tested the complete journey with sample invoices.
10. I improved the UX, documented the system and created the handover package.

## How to describe the AI tools honestly

> I used AI tools as a product-analysis, coding, debugging, design-review and documentation assistant. I gave them the PRD and project context, requested specific scoped changes, inspected the generated work and verified it using builds, tests and manual workflow checks. I did not treat generated code as automatically correct. I controlled the requirements, architecture, financial rules, privacy boundaries and final acceptance.

Avoid saying, “AI built the whole project for me.” A better explanation is:

> AI accelerated the implementation, while I directed the product, selected the architecture, reviewed the changes and verified the result.

## Important technical explanation

| Area | Simple explanation |
|---|---|
| React frontend | The screens the claims handler sees and uses |
| shadcn design language | Reusable, accessible interface components with consistent styling |
| FastAPI backend | Receives requests and runs the claim workflow and business services |
| SQLite | Stores pilot claims, documents, decisions and audit records in one local file |
| PDF/OCR pipeline | Reads both normal PDFs and scanned invoice pages |
| Ontology | A controlled catalogue of standard repair items and evidence |
| Deterministic engine | Normal Python rules calculate amounts the same way every time |
| Optional Gemini integration | Helps with ambiguous wording only; it does not decide money or liability |
| Audit trail | Records important inputs, versions, decisions and outputs for review |

## Common questions and ready answers

### Did AI write all the code?

> AI helped generate and revise parts of the implementation, but I directed it feature by feature. I reviewed the project structure, connected the components, corrected problems and verified the result with automated tests and manual checks. Generated code was treated as a draft until it passed verification.

### Do you understand the code if AI assisted you?

> Yes. The frontend calls FastAPI endpoints. FastAPI routes delegate work to domain services. SQLAlchemy stores the claim and audit data in SQLite. The document pipeline extracts invoice content, the mapping layer connects lines to ontology items, and deterministic comparison rules calculate the challenge. I can trace a user action from the screen to the API, service, database and generated output.

### Where is AI used inside the actual product?

> The core product works without an AI key. Extraction, calculations, candidate retrieval and challenge rules are deterministic. A hosted Gemini provider is optional and can assist when an invoice description has several possible ontology candidates. It is restricted to the supplied candidates and cannot generate prices or approve a challenge.

### Why did you not let AI calculate the Challenge Price?

> Financial results must be reproducible and auditable. Therefore Challenge Price, VAT impact, quantity adjustment and policy gates are calculated using versioned Python rules and Decimal arithmetic. The same inputs always produce the same result.

### How did you prevent hallucination?

> The optional model receives a limited set of candidate ontology items. It must choose from that list or return no match. It cannot invent an ontology ID, price, VAT amount or liability decision. Low-confidence or unsupported cases are sent to a human reviewer.

### How did you check whether AI-generated changes were correct?

> I used TypeScript checks, frontend production builds, Python linting, backend tests, API tests and manual end-to-end review. I also checked generated PDF reports visually and verified that the documentation matched the final implementation.

### Why SQLite?

> This is a portable pilot, so SQLite makes setup and handover simple. SQLAlchemy and Alembic separate the application from the database details, allowing a future production deployment to migrate to PostgreSQL with appropriate infrastructure work.

### What would you change before production?

> I would add insurer identity and role-based access, managed secrets, PostgreSQL, encrypted object storage, backups, monitoring, retention controls, privacy approval, controlled evidence sources and production hosting. The handbook clearly separates the ready pilot from these production requirements.

### What was the hardest part?

> The hardest part was not generating screens. It was translating insurance rules into a workflow that remains understandable, auditable and safe. Mapping garage descriptions, preserving source evidence, applying quantity-aware net calculations and keeping human approval in control required the most careful design.

## Demonstration script

While showing the application, say:

1. “This is the Overview. It tells the handler the claim state and next action.”
2. “Under Documents, the handler uploads an invoice and can inspect how every page was processed.”
3. “The system extracts invoice lines and maps garage wording to standard ontology items.”
4. “The comparison engine checks the quantity-adjusted net line total against governed evidence.”
5. “Challenge Price means the evidence-backed net amount proposed for payment.”
6. “Potential saving is the original eligible net amount minus Challenge Price.”
7. “The handler reviews every proposed challenge and can accept, adjust or reject it.”
8. “Nothing is issued automatically. Human approval is required.”
9. “The final step generates the challenge package and preserves the audit history.”
10. “AI is optional and constrained to ambiguous text mapping; it does not control the money.”

## Final closing statement

> ClaimGuard is an AI-assisted development project, but it is not an uncontrolled AI decision system. I used AI to accelerate analysis, implementation, review and documentation. The delivered application keeps claim liability, financial calculations and final challenge approval deterministic, traceable and under human control.

