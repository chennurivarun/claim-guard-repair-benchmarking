# Extraction and recovery verification — 22 September 2026

## Changes

| Problem | Change |
| --- | --- |
| Wide Word-table rows clipped identity/amount columns | Extraction PDF page width now accommodates complete rows. The original upload remains unchanged. |
| Text headers/footers required LibreOffice unnecessarily | Text-only header/footer content is included in extraction. Visual/nested content still uses LibreOffice. |
| Failures disappeared after navigation | Upload screen now shows persisted per-file status, source, actual extraction counts, original links and review/retry actions. Manual-entry placeholders are not counted as extracted invoices. |
| Failed or empty stored files could not be retried | Retry reparses files without extracted records and rebuilds Word intermediates from preserved originals. Existing invoice/assessment records block this action to protect review work. |
| Explicit assessment selection lost on duplicate empty upload | Re-uploading an empty file through the assessment picker retains the assessment hint. |
| Printed `Claim:` omitted to avoid a pairing conflict | Read the printed identifier. Preserve prefixes; conflicting identifiers require review. |
| Unmatched explanation referenced an unrelated invoice | Explain the closest conflicting candidate with shared identity evidence. This does not weaken matching rules. |

## Verification

- 278 frontend tests; lint and production build passed. Existing bundle-size warning remains.
- Backend targeted suites cover Word ingestion, label extraction, all eight fixture pairs, pairing safeguards, source isolation and review/recovery.
- Browser exercised against a real local API and isolated temporary SQLite database, with OCR/LLM disabled. No production records were modified.
- All eight invoice and eight assessment fixtures appeared in the primary upload workflow, including extracts before mapping approval.
- Seven fixture pairs matched automatically. The EXL fixture remained in review: assessment `ABC 123456` conflicts with invoice `123456`. Previous eight-match results omitted the assessment's printed claim reference and should not be used as the acceptance result.
- Invoice parts expanded; Total Labour drill-through displayed 41 matching labour/paint operations for assessment R6725148.
- Source benchmark page displayed Hatchback (4), SUV (3), Supermini (1), with item evidence and P90 figures.
- Created a deliberately corrupted extraction intermediate for `recovery-check.docx` in the temporary dataset. The persisted failed status survived reload. Clicking Retry extraction recovered one invoice from the preserved Word original and removed the retry action.
- Browser console had no warning/error entries during these checks.
- API tests confirm original download bytes are unchanged and retries cannot replace existing invoice IDs. A saved-pages/no-records retry creates no duplicate pages.

## Limits and operation

The eight fixtures are local format examples, not the unavailable original files from the reported failure. These checks do not establish that every real-world format extracts correctly.

Deploy/restart both API and frontend to use these changes. Existing extraction records are not automatically rewritten. Use Retry extraction for files with no records; existing or manually entered records require review. Files rejected before storage must be uploaded again. Image-based, visual/nested Word documents still depend on an installed renderer and appropriate OCR configuration. Unknown vehicle categories remain valid when make/model evidence or a supported lookup is absent.

This work does not deploy a hosted instance or migrate the user's external database.
