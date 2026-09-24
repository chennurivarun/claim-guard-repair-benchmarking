# Assessment detail: Friday comparison and PDF table layout

## Baseline and evidence

Compared `3cd8420` (latest repository commit on Friday, 18 September) with
`7e95fc6` (release preceding this change). The exact revision running on the
company laptop on Friday is not known.

The deterministic assessment parser and the AI extraction adapter/factory were
unchanged between those revisions. Upload classification, conversion selection
and persistence had changed, but reverting the assessment parser would restore
the same code. This comparison does not establish why the user's earlier run
worked, or that the files/settings in those runs were identical.

A reproducible failure exists in both revisions: assessment table cells stored
as separate PDF text runs become separate lines in `page.get_text("text")`.
The parser expects a complete row with spaces between columns. It therefore
reads identity and totals but loses operations. This reproduces the displayed
"No operations extracted" symptom without any model or API call.

Earlier reconstructed DOCX tests used a renderer that joins cells with three
spaces. Those tests exercised the expected row shape and missed ordinary PDF
exports. The new tests draw each cell separately and retain page coordinates.

## Before / after

All inputs below are repository reconstructions, not the company's originals.
Each reconstruction was also exported with installed LibreOfficeDev
26.8.0.0.alpha0 and read by the old and new parser. No cloud AI/OCR was used.

| Reconstructed format | Friday parser: PDF export operations | New parser: PDF export operations | Spaced-text reference operations |
| --- | ---: | ---: | ---: |
| 1 | 0 | 60 | 60 |
| 2 | 0 | 17 | 17 |
| 3 | 1 | 27 | 27 |
| 4 | 1 | 73 | 73 |
| 5 | 0 | 60 | 60 |
| 6 | 0 | 60 | 60 |
| 7 | 0 | 60 | 60 |

Format 2's local reconstruction contains 17 labour operations. This is not a
claim that the unavailable original has no parts/paint schedule.

## Change

Keep the existing parser as the first reading. Rebuild visual rows from the
positioned words already collected for native PDF and OCR pages, preserving
wide gaps as column separators, and pass those rows through the same parser.
Use the additional reading only when it adds operations and preserves every
previously read operation, including repeated rows and their amounts.

Known header values and printed totals remain evidence; row sums are not used
to overwrite printed figures. Rows never join across pages or across different
vertical positions. No converter/model change or database migration is needed.

## Validation

- Seven formats: descriptions, codes, categories, quantities, rates, amounts
  and derived-price flags agree with the existing spaced-row reference.
- Reverse PDF drawing order produces identical operations.
- A numeric value on a different visual line is not attached to an incomplete row.
- API upload and existing-assessment recovery cover Formats 1 and 4, with
  existing assessment identity, pairing and parts total preserved.
- Total Labour supplies 41 panel/mechanical and paintwork operations for
  Format 1; Total Parts supplies 11 parts for Format 4.
- Full backend regression: **711 passed** (`.venv/bin/pytest tests --tb=short`,
  166.32 seconds); 40 dependency deprecation warnings. Targeted Ruff and
  `git diff --check` passed.

## Applying the fix

Update the backend code and restart its process. In Upload documents, use
**Retry engineer assessment details** on assessments showing zero detail rows.
This reads the stored PDF again while preserving its pairing. Refresh Document
intelligence and check the resulting rows. Fresh uploads use the new reading
automatically. Updating code alone does not change already stored extracts.

The company's original PDFs and configured provider have not been tested here.
Image-only schedules still depend on usable OCR or a working vision reader;
coordinates cannot recover words that were never read. The existing retry
action accepts only assessments with zero saved operations.
