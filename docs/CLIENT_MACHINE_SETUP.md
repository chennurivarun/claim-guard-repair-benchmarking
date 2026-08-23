# Client machine setup card

One page. Complete every row before demonstrating ClaimGuard on a new machine. Each check has a verification step — do not skip the verification column.

## 1. Base prerequisites

| Item | Install | Verify |
| --- | --- | --- |
| Node.js 20+ | [nodejs.org](https://nodejs.org) LTS | `node --version` |
| Python 3.11+ | [python.org](https://www.python.org/downloads/) | `python --version` |
| uv | [docs.astral.sh/uv](https://docs.astral.sh/uv/) | `uv --version` |

## 2. Application setup (from the `claim-guard` folder)

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
uv run claimguard-bootstrap
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Second terminal, from the `claim-guard` folder:

```bash
npm install
npm run dev
```

Verify: open <http://localhost:8000/health> and <http://localhost:5173>.

## 3. AI mapping and extraction (required for correct part matching)

Without an AI key, repair-item matching falls back to fuzzy text similarity only, which
can select the wrong ontology item for unfamiliar invoices. Configure one provider in
`backend/.env` and restart the backend.

Gemini (fastest to enable):

```dotenv
CLAIM_GUARD_LLM_PROVIDER=gemini
CLAIM_GUARD_LLM_MODEL=gemini-2.5-flash-lite
CLAIM_GUARD_LLM_API_KEY=your_key_from_aistudio.google.com
```

Azure OpenAI (preferred where data-governance policy requires the company tenant):

```dotenv
CLAIM_GUARD_LLM_PROVIDER=azure_openai
CLAIM_GUARD_LLM_MODEL=your-deployment-name
CLAIM_GUARD_LLM_API_KEY=your_rotated_secret
CLAIM_GUARD_LLM_BASE_URL=https://your-resource.services.ai.azure.com
CLAIM_GUARD_LLM_API_VERSION=2024-05-01-preview
```

Verify: `http://localhost:8000/health` must show `"ai_status": "configured"`.
`configuration_required` means the key is missing or incomplete; the app still runs,
but matching is deterministic-only.

### Alternative: any OpenAI-compatible provider (OpenRouter, local gateways)

The same boundary accepts any OpenAI-compatible endpoint — including
[OpenRouter](https://openrouter.ai), which fronts many models (some free):

```dotenv
CLAIM_GUARD_LLM_PROVIDER=openai_compatible
CLAIM_GUARD_LLM_MODEL=google/gemini-2.0-flash-exp:free
CLAIM_GUARD_LLM_API_KEY=your_openrouter_key
CLAIM_GUARD_LLM_BASE_URL=https://openrouter.ai/api/v1
```

Swap `CLAIM_GUARD_LLM_MODEL` for any OpenRouter model id, including free
(`:free`) or stealth alpha models. Models that lack strict JSON-schema support
are handled automatically (the client falls back to JSON mode and validates
locally), but weaker models may fail extraction more often — test first.

**Testing models before committing to one:** from `backend/`, copy
`scripts/probe_models.example.json`, list the models you want to compare, set
the key environment variables, and run:

```bash
cd backend
uv run python scripts/llm_model_probe.py --models scripts/probe_models.example.json
```

It scores each model on connectivity/latency, the wrong-part mapping trap
(a model that picks the fan belt for a radiator grille is unusable for
mapping), and line extraction from the Audatex-style fixture.

**Data governance:** free/community models may log or train on inputs. The
probe only ever sends the synthetic fixtures in this repository. For real
claim documents, use a paid provider under the insurer's data terms (Gemini
paid tier or Azure OpenAI in the company tenant), never free-tier routing.

## 4. Scanned documents (Azure Document Intelligence)

Required for photographed or scanned invoices; native PDFs work without it.

```dotenv
CLAIM_GUARD_DOCUMENT_OCR_PROVIDER=azure
CLAIM_GUARD_AZURE_DOCUMENT_ENDPOINT=https://your-resource.cognitiveservices.azure.com
CLAIM_GUARD_AZURE_DOCUMENT_API_KEY=your-company-key
CLAIM_GUARD_AZURE_DOCUMENT_MODEL=prebuilt-layout
```

Verify: `/health` shows `"ocr_provider": "azure"` and `"ocr_status": "azure_configured"`.

## 5. LibreOffice (optional, two features)

| Feature | Without LibreOffice | With LibreOffice |
| --- | --- | --- |
| `.docx` invoice upload | Works — built-in Python conversion | Works — higher-fidelity page images |
| Legacy `.doc` upload | Not supported (clear error shown) | Works |
| Negotiation letter PDF | Works — deterministic ReportLab layout | Works — Word-identical layout |

Install from [libreoffice.org](https://www.libreoffice.org/download/) and ensure
`soffice` is on PATH (`soffice --version`).

## 6. Pre-demo smoke test

1. Upload one known-good PDF from `sample-data/` on the Documents screen — status must reach **Ready**.
2. Open Benchmarks — P90 table renders with counts.
3. Open Review findings — evidence sheet opens and shows the calculation panel.
4. `/health` — no field reads `configuration_required` unless intentionally unconfigured.
