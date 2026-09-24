# Missing assessment details — 24 September 2026

The reported PDFs now upload and pair, but the assessment table has no operations. The screenshots establish the missing saved rows, not whether every original page reached a model or whether the model extracted those rows.

## Reproduced defects and changes

| Defect | Correction |
| --- | --- |
| A vision result containing only identity/totals suppressed the text reader. | Text fallback runs when no operations were found, or a section with a reported total has no operations. |
| A deterministic assessment header overrode AI extraction even when the deterministic result had no operations. | Preserve deterministic fields/totals and supplement missing sections from the other reader. Do not append a second interpretation of an existing section or merge conflicting assessment identities. |
| The UI claimed the original document was total-only merely because no rows were stored. | Explain that rows were not extracted and ask the reviewer to check the original. |
| An already-stored header-only assessment could not be retried. | Add **Retry engineer assessment details** on Upload documents. This adds operations to the existing assessment without deleting its identity, totals, pairing or review status. |
| “Assessment matched” obscured an empty extraction. | Display assessment detail-row counts and a specific missing-details message. |

Recovery is available only for assessments with zero saved operations. It rejects finalised cases and documents that already contain operations. If no details are recovered, the existing assessment stays intact and the UI reports that result. This patch does not manufacture parts from invoice totals or guarantee recovery of partially missing rows within an already-populated section.

## Verification

| Check | Evidence |
| --- | --- |
| Failure reproduced before the fix | Two regression tests failed: the text reader received zero calls after a header-only vision result; zero operations persisted despite a detailed AI result. |
| Backend checks | 152 relevant extraction, parser, persistence, pairing, mapping-review and batch-intake tests passed; 3 additional assessment-merge tests passed. AI responses in regression tests are stubs, with real PDF analysis and database persistence. |
| Frontend checks | 82 extracts, linking and intake tests passed; TypeScript and targeted ESLint checks passed. |
| Browser recovery | Isolated copy of the local sample database, AI/OCR disabled. Removed the reconstructed Format 4 assessment's operations to represent the older saved state. The browser showed 0 detail rows and the retry button. Clicking retry restored 73 rows and removed the button. |
| Total Parts click | The Ford Puma invoice's £1,104.39 Total Parts link opened assessment D067789900, displaying 11 parts including RR DOOR and the door hinges. |
| Browser console | No warnings/errors during the recovery and parts-link checks. |

The unavailable original PDFs, company DeepSeek endpoint and Windows laptop were not tested. These checks establish the code corrections and recovery flow, not universal extraction accuracy.

## Recipient instructions

1. Use the updated project code, retaining the existing `backend/.env` and data directory.
2. Restart the backend from `backend` with `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`. Restart the frontend with its usual `npm run dev` command and refresh the browser.
3. On **Upload documents**, find an assessment showing **0 detail rows**, then click **Retry engineer assessment details**. No database reset or re-upload is required.
4. Confirm its detail-row count increases. Open **Document intelligence**, expand the matching invoice and click **Total Parts Amount**. Verify the displayed parts against the original assessment PDF.
5. If the count remains zero, the UI will report that no details were extracted. Check whether the uploaded PDF includes the detailed schedule pages; this outcome still needs investigation and is not proof the source is total-only.

No new dependency or database migration is introduced by this patch.

## Word conversion question

`docx2pdf` is another possible conversion route when desktop Microsoft Word is installed on Windows/macOS. It automates Word; it is not a standalone Word renderer. See the [maintainer's documentation](https://github.com/AlJohri/docx2pdf). It was evaluated as an alternative but not installed or integrated in this assessment-extraction patch. The reported PDF extraction issue occurs after conversion.
