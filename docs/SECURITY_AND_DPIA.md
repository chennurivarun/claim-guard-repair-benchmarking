# ClaimGuard pilot security and DPIA checklist

This document covers the local SQLite pilot. A client deployment must complete the insurer-specific rows before production use.

## Data-flow controls

| Boundary | Pilot control | Evidence |
|---|---|---|
| PDF upload | PDF signature, byte limit and page limit validation; invalid files fail closed | API integration and PDF acceptance tests |
| Local persistence | SQLite foreign keys, WAL, busy timeout; application data kept under `backend/data` | `app/database.py` |
| Extraction | Original page, extraction method, confidence and available bounding box are retained | invoice-line and page records |
| External model | PII redaction, original-content hash, prompt-injection flags and explicit untrusted-text framing | `app/security/redaction.py` |
| LLM mapping | JSON schema; supplied candidate IDs only; explicit `NO_MATCH`; no arithmetic fields | `app/llm/mapping.py` |
| Web research | Handler initiated; versioned domain allow-list; provisional evidence excluded until approval | research workflow tests |
| Decisions | Human actor, rationale, before/after values and processing-run version are audited | hash-chained audit events |
| Exports | JSON, XLSX and SQLite remain review outputs; DOCX/PDF require liability and challenge gates | report-route tests |

## DPIA sign-off checklist

| Item | Pilot status | Production owner / action |
|---|---|---|
| Lawful basis and claims-processing purpose documented | Needs insurer sign-off | Insurer DPO |
| Data minimisation for external model calls | Implemented in code | Validate insurer-approved redaction set |
| Processor/subprocessor list | Not applicable while models are disabled | Add configured model/research vendors |
| UK data residency and transfer mechanism | Needs deployment decision | Insurer security and legal |
| Retention schedule for PDFs, exports and audit events | Needs insurer policy | Configure deletion/archive job |
| Data-subject access and correction route | Handler correction is implemented | Map to insurer DSAR process |
| Role-based access control and SSO | Not part of single-user local pilot | Required before multi-user deployment |
| Encryption at rest and key management | Host-volume responsibility in pilot | Required for managed deployment |
| Backup restore and disaster recovery test | Portable SQLite export implemented | Schedule restore exercise |
| Incident response and breach notification | Needs insurer process | Insurer DPO / security |
| Source allow-list approval | Placeholder `*.example.test` only | Replace with insurer-approved domains |
| Contracted labour-rate schedule | Open onboarding dependency | Claims-policy owner supplies override |

## Production blockers

The local pilot must not be exposed to the public internet. Before production, add authenticated user identities, authorisation by insurer/claim, managed secrets, encrypted storage, retention automation, monitoring, rate limiting, malware scanning, insurer-approved source domains, and completed DPIA sign-off.
