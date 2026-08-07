# ClaimGuard Client Quick Start

## 1. Start the application

From the unzipped `claim-guard` folder:

```bash
cd backend
cp .env.example .env
uv sync --extra dev
uv run alembic upgrade head
uv run claimguard-bootstrap
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```bash
npm install
npm run dev
```

Open `http://localhost:5173`.

## 2. Add Azure Document Intelligence

Open `backend/.env` and paste the company values into these two lines:

```dotenv
CLAIM_GUARD_DOCUMENT_OCR_PROVIDER=azure
CLAIM_GUARD_AZURE_DOCUMENT_ENDPOINT=https://your-resource.cognitiveservices.azure.com
CLAIM_GUARD_AZURE_DOCUMENT_API_KEY=your-company-key
CLAIM_GUARD_AZURE_DOCUMENT_MODEL=prebuilt-layout
```

The model value must be exactly `prebuilt-layout`. Restart FastAPI, then open
`http://localhost:8000/health`. The response should show:

```json
{
  "ocr_provider": "azure",
  "ocr_status": "azure_configured"
}
```

No Tesseract installation is required.

Keep all keys in `backend/.env`. Never put secret keys in `src/` or a frontend
`.env` file because frontend values can be exposed in the browser.

If `/health` does not show both `"ocr_provider": "azure"` and
`"ocr_status": "azure_configured"`, stop and restart FastAPI after checking the
four variable names above. Upload errors now report the Azure problem directly;
they do not hide it behind a Tesseract error.

## 3. Expand the vehicle catalogue

Edit `sample-data/vehicle_category_lookup.csv`. Add one model per row. Required
columns are `make`, `model`, `group_range`, and `group_category`; body type,
fuel type, aliases, and source are optional. Separate multiple aliases with `|`.

Then run:

```bash
cd backend
uv run claimguard-import-vehicle-lookup ../sample-data/vehicle_category_lookup.csv
```

The command safely adds new models and updates existing make/model matches. It
does not duplicate rows.

## 4. Run the P90 demonstration

The verified native-text PDFs are in `output/pdf/p90-demo-invoice-set/`.

- On a fresh database, upload all ten PDFs together.
- If the two original invoices are already loaded, upload only invoices 03–10.
- Select invoice `9510` and open **Benchmarks**.

The screen calculates P90 from the other nine invoices, shows the exact invoice
lines used as evidence, and recommends a challenge only when the current charge
is both more than the selected percentage above P90 and at least £5 higher.
