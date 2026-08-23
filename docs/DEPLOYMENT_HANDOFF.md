# ClaimGuard deployment handoff and release checklist

Use this document for every ClaimGuard release. It is written for the current local/internal pilot and records the checks required before, during and after deployment.

## 1. Decide whether this deployment is allowed

| Target | Current status | Rule |
| --- | --- | --- |
| Trusted single-machine or tightly controlled internal pilot | Allowed after this checklist passes | Keep the API bound to `127.0.0.1`, or behind an insurer-approved authenticated gateway. |
| Shared internal service without authenticated users and claim-level authorisation | Blocked | Add SSO/RBAC and complete the security review first. |
| Public internet | Blocked | Do not expose the current pilot. Complete every production blocker in section 11 first. |

The current application records actor names for audit, but it does not authenticate those identities. A typed actor name is not a security boundary.

## 2. Release identity

Complete this table before deployment. Deploy an exact commit, never an unidentified working folder.

| Field | Value |
| --- | --- |
| Repository | ClaimGuard |
| Branch | `main` |
| Current handoff baseline | `29791118b82c8e968e9c621da383adb23319f17a` |
| Database migration head | `20260823_0009` |
| Release owner | ____________________ |
| Deployment owner | ____________________ |
| Target environment | ____________________ |
| Planned date/time | ____________________ |
| Previous known-good commit/artifact | ____________________ |
| Change/ticket reference | ____________________ |

Before continuing, confirm:

- [ ] The intended commit was reviewed and approved.
- [ ] `git status --short` contains no accidental tracked or untracked release files.
- [ ] `git rev-parse HEAD` matches the approved commit.
- [ ] The previous known-good frontend and backend artifacts are still available for rollback.
- [ ] A named release owner and deployment owner are available during the deployment window.

## 3. What must be deployed

| Component | Build/runtime | Deployment requirement |
| --- | --- | --- |
| Reviewer UI | React/Vite; `npm run build` produces `dist/` | Serve `dist/` with an insurer-approved static server. `VITE_API_URL` is embedded at build time. |
| API | FastAPI/Uvicorn; entry point `app.main:app` | Run from `backend/`. For the local pilot, bind only to `127.0.0.1`. |
| Database | SQLite at `backend/data/claim_guard.db` by default | Store on an encrypted persistent disk. Back up the complete database before migration. Do not put it on ephemeral storage. |
| Uploaded documents | `backend/data/storage` by default | Store on encrypted persistent disk with restricted access. Copy it during upgrades. |
| Generated reports | `backend/data/exports` | Treat as claim data; apply the same access, retention and backup controls. |
| OCR | Native PDF extraction plus optional Azure Document Intelligence | Azure is required for photographed/scanned documents on the company setup. |
| LLM assistance | Gemini, Azure OpenAI or an approved OpenAI-compatible provider | Optional for app startup, but required for the intended unfamiliar-part matching flow. Use only an insurer-approved provider for real claims. |

This repository does not currently include a Dockerfile, reverse-proxy configuration, infrastructure-as-code, or a CI/CD deployment workflow. The deployment owner must supply and review the host-specific service configuration; do not invent it during the release window.

## 4. Configuration and secrets

Create the environment files from the checked-in examples. Never commit `.env` files or put backend keys in `VITE_*` variables, `src/`, browser code, logs, screenshots or tickets.

| Variable | Required when | Expected rule |
| --- | --- | --- |
| `VITE_API_URL` | UI and API use different origins | Absolute API origin, with no trailing slash. Leave blank only when a reverse proxy serves `/api` and `/health` on the UI origin. Rebuild the frontend after changing it. |
| `CLAIM_GUARD_ENVIRONMENT` | Every non-development deployment | Set an accurate environment name such as `staging` or `internal_pilot`. |
| `CLAIM_GUARD_DATABASE_URL` | Every deployment | Point to the persistent SQLite database. The current package does not include a PostgreSQL driver or production database migration plan. |
| `CLAIM_GUARD_STORAGE_DIR` | Every deployment | Point to encrypted persistent storage, not an ephemeral application directory. |
| `CLAIM_GUARD_CORS_ORIGINS` | UI and API use different origins | JSON list containing only the approved UI origin(s). Do not use `*` with credentials. |
| `CLAIM_GUARD_DOCUMENT_OCR_PROVIDER` | Scanned/photographed documents | Use `azure` on the company deployment after Azure is configured. |
| `CLAIM_GUARD_AZURE_DOCUMENT_ENDPOINT` | Azure OCR | Company-managed Azure Document Intelligence endpoint. |
| `CLAIM_GUARD_AZURE_DOCUMENT_API_KEY` | Azure OCR | Secret-store value; rotate according to insurer policy. |
| `CLAIM_GUARD_AZURE_DOCUMENT_MODEL` | Azure OCR | Must be `prebuilt-layout` for the verified flow. |
| `CLAIM_GUARD_LLM_PROVIDER` | LLM matching/extraction enabled | Use the insurer-approved provider: `gemini`, `azure_openai`, `openai_compatible`, or `disabled`. |
| `CLAIM_GUARD_LLM_MODEL` | LLM enabled | Exact approved model/deployment name. |
| `CLAIM_GUARD_LLM_API_KEY` | LLM enabled | Secret-store value; never expose to the frontend. |
| `CLAIM_GUARD_LLM_BASE_URL` | Non-default or Azure/OpenAI-compatible provider | Approved provider endpoint only. |
| `CLAIM_GUARD_LLM_VISION_ENABLED` | Vision fallback approved and tested | Keep `false` until the configured deployment is confirmed to accept images and insurer policy permits sending page images. |
| `CLAIM_GUARD_AUTO_RESEARCH` | Always in this release | Keep `false`. Real automatic research is not approved. |
| `CLAIM_GUARD_RESEARCH_SOURCE_ALLOWLISTS` | Real research adapter enabled | Replace the placeholder domains with insurer-approved UK sources before use. |

Secret/configuration sign-off:

- [ ] No real key appears in Git history or the frontend build.
- [ ] Real claim data will not be sent through free/community model tiers.
- [ ] OCR and LLM endpoints, residency, retention and subprocessors are approved by security/legal.
- [ ] CORS contains only the intended frontend origin(s).
- [ ] Upload size/page limits are appropriate for the target host.
- [ ] The source allow-list is approved, or research remains disabled.

## 5. Back up before changing anything

The database, uploaded files and reports form one operational data set. Back them up together while writes are stopped or using an approved consistent snapshot method.

- [ ] Stop new uploads and handler decisions for the deployment window.
- [ ] Record the existing application commit and migration revision.
- [ ] Back up `backend/data/claim_guard.db`, including committed WAL content through a consistent SQLite backup/snapshot.
- [ ] Back up `backend/data/storage` and `backend/data/exports`.
- [ ] Store the backup encrypted and access-controlled.
- [ ] Verify the backup is non-empty and record its location/checksum.
- [ ] Confirm who can restore it and the restore decision point.

| Backup evidence | Value |
| --- | --- |
| Backup location/reference | ____________________ |
| Database backup verified by | ____________________ |
| Document storage backup verified by | ____________________ |
| Backup time | ____________________ |
| Restore owner | ____________________ |

## 6. Build and test the exact release

Run from a clean checkout of the approved commit. `npm ci` and `uv sync --frozen` use the checked-in lock files.

```bash
npm ci
npm run typecheck
npm run lint
npm run test
npm run build

cd backend
uv sync --frozen --extra dev
uv run ruff check app tests
uv run pytest -m "not slow"
uv run alembic heads
uv run alembic upgrade head
```

Expected migration head for this handoff: `20260823_0009`.

| Gate | Required result | Evidence |
| --- | --- | --- |
| Frontend typecheck | Exit code 0 | ____________________ |
| Frontend lint | Exit code 0 | ____________________ |
| Frontend tests | All tests pass | ____________________ |
| Frontend production build | Exit code 0; `dist/` created | ____________________ |
| Backend lint | Exit code 0 | ____________________ |
| Backend fast suite | All tests pass; only understood documented skips | ____________________ |
| Migration head | `20260823_0009` for this release | ____________________ |
| Migration application | Exit code 0 against a staging copy first | ____________________ |

For a release intended to process scanned documents, also run the slow/OCR acceptance suite in the configured environment:

```bash
cd backend
uv run pytest -m slow
```

## 7. Deployment order

Follow this order so the UI does not call an incompatible or unavailable API.

| Order | Action | Pass condition |
| ---: | --- | --- |
| 1 | Enable the change window and take the verified backup | Backup evidence is recorded. |
| 2 | Install the backend from the approved commit and locked dependencies | Installation succeeds without changing the lock file. |
| 3 | Apply `uv run alembic upgrade head` from `backend/` | Migration reaches the expected head. |
| 4 | Start the API with the approved environment/secrets | Process remains healthy and logs contain no secret values. |
| 5 | Check `GET /health` before routing users to it | HTTP 200, `status=ok`, `database=ok`; AI/OCR statuses match the intended configuration. |
| 6 | Build/deploy the UI with the correct `VITE_API_URL` | UI loads and reaches the intended API. |
| 7 | Run the full smoke test in section 8 | Every mandatory row passes. |
| 8 | Re-enable users and monitor | No new 5xx, processing failures or unexpected manual-review spike. |

Local/internal API command:

```bash
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For a production-build smoke test only, `npm run preview -- --host 127.0.0.1 --port 4173` can preview `dist/`. Vite preview is not the production hosting design; use the organisation's approved static server for a real managed deployment.

## 8. Post-deploy smoke test

Use non-sensitive test fixtures first. Do not begin with a live customer claim.

| Test | Mandatory pass condition | Result |
| --- | --- | --- |
| Health | `/health` returns 200 with `status: ok` and `database: ok`. | ☐ Pass ☐ Fail |
| AI status | When LLM assistance is intended, `/health` shows `ai_status: configured`. | ☐ Pass ☐ Fail ☐ Disabled by design |
| OCR status | When scanned PDFs are intended, `/health` shows `ocr_provider: azure` and `ocr_status: azure_configured`. | ☐ Pass ☐ Fail ☐ Native PDFs only |
| Frontend connection | UI shows API connected; no browser console errors or failed CORS requests. | ☐ Pass ☐ Fail |
| Upload | A known-good native PDF reaches **Ready** and no file is silently discarded. | ☐ Pass ☐ Fail |
| Scanned/Audatex upload | A representative Type 7/Audatex-style file extracts real item rows (for example bumper/wing/brake parts), not only roll-up totals such as “total parts” or “total paint work.” | ☐ Pass ☐ Fail ☐ Not in scope |
| File selection | Changing the selected invoice changes the displayed extracted data; the dropdown is not static. | ☐ Pass ☐ Fail |
| Manual review | A deliberately unreadable/unsupported file appears in Manual review with a reason. | ☐ Pass ☐ Fail |
| Benchmarks | The table loads; a genuine empty state displays zero values/counts rather than blanks or stale figures. | ☐ Pass ☐ Fail |
| Price comparison | Running document price comparison returns HTTP 200, not 500, and produces a stable result. | ☐ Pass ☐ Fail |
| Challenged invoices | The challenged-invoice selector contains only invoices with a positive challenge amount; it does not offer invoices that only show “No price challenges found.” | ☐ Pass ☐ Fail |
| Advanced review findings | All processed invoices and all extracted lines remain inspectable here, including invoices with no challenge. | ☐ Pass ☐ Fail |
| New part matching | An unfamiliar extracted part searches the ontology and creates a reviewable proposal when no safe existing match exists; the screen is not blank. | ☐ Pass ☐ Fail |
| Match approval | Approving/changing a repair-item match updates the selected row, persists the ontology/mapping decision and reruns comparison. | ☐ Pass ☐ Fail |
| Challenge approval | After the repair-item match prerequisite is approved, the challenge approval control works and the review counter/status updates. | ☐ Pass ☐ Fail |
| Audit | The approval/mapping action appears in the audit trail with actor, rationale and before/after data. | ☐ Pass ☐ Fail |
| Refresh/restart | Refreshing the browser and restarting the API preserve documents, selections and decisions. | ☐ Pass ☐ Fail |

If a mandatory check fails, stop the release. Capture the request URL, HTTP status, safe error code, affected document type and application commit. Do not copy claim content or secrets into a public ticket.

## 9. Monitoring for the first release window

| Signal | Watch for | Response |
| --- | --- | --- |
| API health | Non-200 `/health`, database check failure | Remove traffic and investigate database/storage access. |
| HTTP errors | Any sustained 5xx, especially comparison or document processing | Stop new uploads; preserve request/error identifiers; consider rollback. |
| Document processing | Files stuck in processing, sudden manual-review increase, silent omissions | Pause intake and compare against the smoke fixture. |
| AI/OCR provider | Timeouts, 401/403, 429, invalid schema/extraction | Verify configuration and quotas. The app should degrade safely, but reviewers must be told. |
| Disk | Database/storage/export volume approaching capacity | Stop intake before the persistent volume fills. |
| Audit | Missing actions, hash-chain/integrity errors | Stop decisions and preserve the database for investigation. |

Record the monitoring owner and observation window:

| Field | Value |
| --- | --- |
| Monitoring owner | ____________________ |
| Start/end time | ____________________ |
| API/log dashboard | ____________________ |
| Incident channel/contact | ____________________ |

## 10. Rollback plan

Rollback must restore a compatible application, database and document store—not only old frontend files.

1. Stop new uploads and review decisions.
2. Remove user traffic from the failed release.
3. Preserve logs and error identifiers without copying secrets or claim content.
4. Redeploy the recorded previous known-good frontend/backend artifacts.
5. If the new migration changed stored data incompatibly, restore the verified pre-deploy database and storage snapshot. Do not run `alembic downgrade` blindly.
6. Start the previous API, check `/health`, then run the core smoke tests.
7. Re-enable users only after the release owner signs off.
8. Record which data, if any, was created after the backup and how it will be reconciled.

| Rollback decision | Value |
| --- | --- |
| Trigger/threshold | ____________________ |
| Decision owner | ____________________ |
| Previous artifact/commit | ____________________ |
| Database restore required? | ____________________ |
| Rollback completed/tested at | ____________________ |

## 11. Production blockers

These are release gates, not optional improvements. The current pilot must not be deployed as a public or general multi-user service until they are completed.

| Blocker | Required owner/evidence |
| --- | --- |
| Authenticated user identity, insurer SSO and role/claim-level authorisation | Security/identity design plus access-control tests |
| CSRF/session review and authenticated gateway/reverse proxy | Security review and approved configuration |
| Managed secrets and key rotation | Platform/security evidence |
| Encryption at rest and in transit | Platform configuration and certificate/key evidence |
| Malware scanning and upload isolation | Security architecture and tests |
| Rate limiting, abuse controls and request limits | Platform/API tests |
| Retention, deletion, archive and legal-hold automation | DPO/records policy plus operating procedure |
| Encrypted backup schedule and tested disaster recovery | Restore exercise evidence |
| Central monitoring, alerting and incident response | Dashboard, alerts and named on-call owner |
| Insurer-approved LLM/OCR contracts, residency and subprocessor review | Legal/security sign-off |
| Completed DPIA and lawful-basis sign-off | Insurer DPO approval |
| Approved research source allow-list | Claims-policy/security approval |
| Production packaging and deployment automation | Reviewed container/service manifests and CI/CD controls |

See [Security and DPIA](SECURITY_AND_DPIA.md) for the underlying pilot controls and insurer sign-off items.

## 12. Final go/no-go sign-off

| Sign-off | Name | Decision | Time | Evidence/notes |
| --- | --- | --- | --- | --- |
| Engineering |  | ☐ Go ☐ No-go |  |  |
| QA/product |  | ☐ Go ☐ No-go |  |  |
| Deployment/platform |  | ☐ Go ☐ No-go |  |  |
| Security/DPO, when required |  | ☐ Go ☐ No-go |  |  |
| Business/claims owner |  | ☐ Go ☐ No-go |  |  |

The deployment is complete only when all mandatory smoke tests pass, monitoring is active, the release identity is recorded, and the responsible owners select **Go**.
