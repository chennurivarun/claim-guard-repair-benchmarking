# Missing assessments: investigation and direction

## Conclusion

The latest screenshots show five ready invoice documents and zero extracted assessments. The pairing engine has nothing to pair those invoices with. The earlier logs also show upload requests returning HTTP 422, separately from the invoice database-write failure fixed in `bf4c727`.

Changing Llama to DeepSeek does not address failures before the model is called. The exact reason every assessment failed on the Windows laptop is not established: we have neither its upload response bodies nor its originals. We must distinguish that uncertainty from defects reproduced locally.

An empty file picker after uploading is expected: the UI clears both pickers after a batch. It is not evidence that the user forgot to select assessments.

## How the application actually works

| Stage | Code | What happens |
| --- | --- | --- |
| Selection | `src/features/claim-guard/screens-client-intake.tsx` | Accepts PDF, DOC and DOCX. Other extensions are filtered out. Invoice and assessment selections are combined for one source. |
| Upload loop | `src/features/claim-guard/intake-batch.ts` | Sends invoices first, then assessments, one file at a time. One failure does not stop the remaining files. The assessment picker sends an explicit document-kind hint. |
| Conversion | `backend/app/services/document_processing.py:normalise_document_upload` | Converts Word files to a PDF before creating the document record. Plain Word text/tables use a Python renderer. Images, text boxes and nested tables require LibreOffice. |
| Storage | `store_pdf` in the same service | Preserves the original and extraction PDF. Identical files in the same source reuse the existing document. Conversion failures have no stored-document row. |
| Reading | `backend/app/extraction/pdf_pipeline.py` | Reads native PDF text; uses OCR/image reading for sparse pages. Classifies pages and selects invoice/assessment extraction routes. AI is a conditional extraction tier, not an unconditional reader of every original upload. |
| Saving | `process_document` | Stores invoice lines or assessment operations. Deterministic assessment parsing takes priority when it returns a result; otherwise the extracted AI assessment is used. |
| Pairing | `backend/app/services/engineer_assessment.py:_select_invoice` | Compares extracted identifiers within the same source. Shared matching identifiers allow a proposal; conflicts and ambiguous candidates stay in review. This is separate from AI part-name matching. |
| Display | Upload receipt, mapping review and extracts | Shows persisted records. A count of “documents processed” is the cumulative count of ready documents, not proof that every selected file succeeded in the latest attempt. |

## Findings and evidence

| Finding | Evidence | Disposition |
| --- | --- | --- |
| Explicit assessment intent reached the reader too late | A new regression test uploaded a report titled “Repair authorisation” through the assessment path. Before the fix, the AI assessment reader received zero calls; no assessment was saved. | Fixed: apply the upload hint before grouping and AI selection. The test now calls the reader, saves the assessment and pairs it to an invoice with the same registration. The AI response in this test is a stub; it proves application routing and persistence, not DeepSeek quality. |
| A valid image-bearing Word document can fail before AI | Adding one image to a Word assessment caused conversion rejection with no renderer available. The same document converted successfully using the actual local LibreOffice installation. | The renderer remains necessary for these formats. The error now states that AI has not been reached and gives the PDF alternative. No content is silently discarded to force acceptance. |
| Windows converter detection depended on PATH | The app looked only for `soffice`/`libreoffice` on PATH. A regression test simulated an installed `Program Files/LibreOffice/program/soffice.exe` absent from PATH and failed before the fix. | Fixed: also discover standard Windows and macOS installation locations. This does not install LibreOffice on the user's machine. |
| Model changes do not refresh old extracts | Reupload deduplicates identical files. The process endpoint returns `already_processed` for documents with saved pages. | Intentional protection for existing records, but important during diagnosis. Use a fresh case for a clean comparison; do not delete the existing database. |
| The AI probe does not test the reported workflow | `app/llm/selftest.py` checks connection, a part-name choice and invoice extraction from prepared fixture text. It does not upload Word files, test assessment routing, persist records or pair invoice/assessment documents. | A passing probe is limited evidence. The new local conversion diagnostic tests an earlier stage that the probe bypasses. |
| Native extraction can bypass useful AI work | The invoice text tier is skipped once benchmarkable part rows exist. A deterministic assessment result takes priority even if some details are missing. | Remaining design limitation. Future work should trigger recovery from missing required evidence and record field provenance, rather than assume that any extracted rows mean a complete document. |
| Three existing tests were already failing | Full baseline run: two tests still expected text-only headers/footers to require Office, although those are now supported. A third assumed exactly 15 of 17 operations would land on PDF page 2; the renderer now places 16 there. | Tests now exercise genuinely visual header/footer content and validate all 17 operations against their actual source-page text. The assertions were updated to test preserved evidence instead of obsolete rendering assumptions. |

## Local diagnostic for the Windows laptop

From the latest project's `backend` folder, run:

```powershell
uv run python scripts/diagnose_intake.py --folder "C:\path\to\the\assessment-folder"
```

Replace the path with the actual folder. Run it separately for the invoice folder if needed. It uses the same upload converter as the application and prints a result for each file, the configured text/vision model names, and whether LibreOffice was found. It makes no AI calls, performs no uploads, and changes no database records. Output includes filenames and conversion results, not document text or keys.

| Result | Meaning and next action |
| --- | --- |
| Conversion FAIL | Fix the named format/dependency problem first. Changing the model cannot fix this stage. If the office renderer is unavailable, save the original as PDF in Word and upload that PDF. |
| Conversion PASS, pages need OCR | Conversion succeeded; OCR or a tested image-capable deployment still has to read those pages. This diagnostic does not test those services. |
| All files PASS | Upload invoices and assessments into the same source in a fresh case, then inspect per-file processing results. Capture the exact processing error if an assessment produces zero records. |
| Files ignored | Their extensions are not accepted by the current picker. This is a file-support issue, not a model failure. |

Restart the backend after changing its model configuration. Check both text and vision model settings: changing the text model does not replace an explicitly configured vision model. The current company's DeepSeek deployment has not been exercised in this investigation; its capabilities cannot be inferred solely from its deployment name.

## Direction

Keep the original files, structured extraction, evidence-based pairing and manual handling of real conflicts. Those are appropriate foundations. Change the debugging and acceptance process: require evidence that all expected files reached conversion, extraction and storage before judging matching quality. Preserve rejected-upload outcomes across navigation, distinguish reused results from new processing, and measure extraction completeness per document.

The repository fixtures and mocked AI tests establish specific application behavior. They do not certify all document formats or the eight unavailable originals. Stop using model substitutions or the health endpoint as proof that the complete application works.

## Verification

- Both new regression scenarios failed before their respective production fixes and pass afterward.
- The assessment-routing test covers native PDF input, the configured text-reader boundary, database persistence and registration-based pairing.
- Conversion diagnostic: all 16 local Word fixtures pass conversion. An image-bearing Word assessment fails without a renderer and succeeds through the real local LibreOffice installation. A corrupted file reports a signature failure.
- Frontend upload-loop and intake-screen tests: 26 passed.
- Full backend suite: 679 passed, 40 warnings in 155.67 seconds. Warnings concern existing dependency deprecations. The extended pairing assertion was also rerun separately and passed.
- No original client files, live DeepSeek calls, Windows GUI test, or new browser QA were used in this investigation.
