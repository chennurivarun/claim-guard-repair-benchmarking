# Browser verification — 23 September 2026

Verified application commit `21b1562` through the Codex Browser against a fresh temporary SQLite database and local API. This used repository sample documents, with LLM and OCR disabled; it is not a verification of the company's DeepSeek deployment or unavailable originals.

| Check | Observed result |
| --- | --- |
| Main upload workflow | Selected eight invoice DOCX files and eight assessment DOCX files through the two file pickers; all 16 processed successfully. |
| Extraction | Receipt contained eight invoices and eight assessments, all ready. |
| Automatic pairing | Seven assessments paired to their expected invoices. EXL remained unpaired with the explicit claim-reference conflict `ABC 123456` versus `123456`. |
| Refresh persistence | Reload retained 16 processed documents and seven automatic pairings. |
| Invoice parts | GH58JKL invoice expanded to parts and other charges with amounts. |
| Labour drill-through | Clicking Total Labour opened paired assessment R6725148 operations, including labour and paint rows through sequence 41. |
| Mapping approval | Approve mapping succeeded; the conflicting EXL pair remained unresolved. |
| Benchmark page | Main navigation displayed Hatchback (4 invoices), SUV (3), Supermini (1), and item-level P90 evidence rows. |
| Failure recovery | A separate synthetic Word invoice was stored through the application service in the temporary database. Its extraction intermediate was deliberately corrupted. Processing marked it failed; the browser displayed the failure after reload. Retry extraction rebuilt from the preserved original and produced one ready invoice; the retry action disappeared. |
| Browser console | No warning/error entries observed during these checks. |

The earlier full backend suite passed 679 tests. The explicit unfamiliar-assessment AI-routing regression uses a stub AI reader, and the Windows LibreOffice discovery regression simulates Windows paths. Neither establishes live model accuracy or complete operation on the recipient's laptop.

The remaining acceptance check is to run the latest code on that laptop and confirm that its assessment uploads reach storage, extract assessment records, and pair using the original printed identifiers. Health/probe success alone does not establish this.
