# How to run ClaimGuard (5 steps)

Works on Windows, Mac, or Linux. You need two terminals: one for the backend,
one for the app.

## Step 0 — install these once

| Tool | Get it from | Check it works |
| --- | --- | --- |
| Python 3.11+ | <https://www.python.org/downloads/> | `python --version` |
| uv | <https://docs.astral.sh/uv/> | `uv --version` |
| Node.js 20+ | <https://nodejs.org> (LTS) | `node --version` |

## Step 1 — start the backend (terminal 1)

Open a terminal **in this folder** (the one containing this file), then:

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
uv run claimguard-bootstrap
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Leave this terminal open. On Windows use `copy .env.example .env` instead of `cp`.

## Step 2 — start the app (terminal 2)

Open a second terminal in this same folder:

```bash
npm install
npm run dev
```

## Step 3 — open it

Go to <http://localhost:5173> in your browser. The demo claim CG-2026-0048 is
already loaded. Health check: <http://localhost:8000/health> should say
`"status": "ok"`.

## Step 4 — turn on the AI (recommended, 2 minutes)

Without this the app still works, but sends more documents to manual review.
Edit `backend/.env`, add ONE of these, then restart the backend (Ctrl+C in
terminal 1, run the last command again):

**Google Gemini** (get a free key at <https://aistudio.google.com/app/apikey>):

```dotenv
CLAIM_GUARD_LLM_PROVIDER=gemini
CLAIM_GUARD_LLM_MODEL=gemini-2.5-flash-lite
CLAIM_GUARD_LLM_API_KEY=paste_your_key_here
```

**OpenRouter** (any model, including free ones — <https://openrouter.ai>):

```dotenv
CLAIM_GUARD_LLM_PROVIDER=openai_compatible
CLAIM_GUARD_LLM_MODEL=google/gemini-2.0-flash-exp:free
CLAIM_GUARD_LLM_API_KEY=paste_your_key_here
CLAIM_GUARD_LLM_BASE_URL=https://openrouter.ai/api/v1
```

Check it worked: <http://localhost:8000/health> shows `"ai_status": "configured"`.

For scanned or photographed documents you also need an Azure Document
Intelligence key — see `docs/CLIENT_MACHINE_SETUP.md` section 4.

## Step 5 — try it

Upload PDFs on the **Documents** screen (sample invoices are in
`sample-data/` and `output/pdf/p90-demo-invoice-set/`), then walk:
Documents → Benchmarks → Challenged invoices → Challenge decision.
Documents the tool can't read automatically appear under
**Advanced tools → Manual review** with an AI explanation.

## Updating to a newer version WITHOUT losing your work

Every download is a fresh copy with an **empty database** — your uploaded
documents and decisions live in the old folder. To carry them over:

1. Copy `backend/.env` from the old folder to the new one (your keys).
2. Copy the whole `backend/data` folder from the old folder to the new one
   (your documents, decisions, and price book).
3. From the new `backend` folder run `uv run alembic upgrade head` once, then
   start as usual.

Skip step 2 only when you deliberately want a clean start.

## If something goes wrong

| Problem | Fix |
| --- | --- |
| Backend won't start | Run the Step 1 commands from the `backend` folder, in order |
| Browser shows "API is not ready" | Terminal 1 isn't running — restart Step 1's last command |
| `ai_status: configuration_required` | The key in `backend/.env` is missing or incomplete; recheck Step 4 |
| A document says MANUAL REVIEW | Not an error — open Advanced tools → Manual review and read the AI's explanation |
| "AI assistance was unavailable" notice | Free AI tiers rate-limit; wait a minute and run it again |
| Word `.doc` (old format) rejected | Save it as `.docx` or PDF, or install LibreOffice |

More detail: `docs/CLIENT_MACHINE_SETUP.md` (setup card) and
`docs/WHAT_WE_CHANGED.md` (what this release contains, in plain English).
