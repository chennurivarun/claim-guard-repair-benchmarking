# ClaimGuard handover — read this first

This package contains the complete local-pilot application, database migrations, automated tests, setup documentation and a controlled ten-invoice demonstration set.

## Start here

| Need | File or folder |
| --- | --- |
| Install and run the application | `docs/CLIENT_HANDOVER_QUICK_START.md` |
| Product and workflow explanation | `docs/CLAIMGUARD_BEGINNER_HANDBOOK.md` |
| Completion and verification record | `docs/COMPLETION_AUDIT.md` |
| Benchmark formula and evidence rules | `docs/BENCHMARKING_MODEL.md` |
| Ten PDFs for the P90 and knowledge-graph demo | `output/pdf/p90-demo-invoice-set/` |
| Detailed changes and output report | `output/pdf/ClaimGuard-Detailed-Changes-and-Outputs-2026-08-05.pdf` |
| Final regression QA and corrected price rule | `docs/FINAL_QA_2026-08-07.md` |

## Configuration

- Copy `backend/.env.example` to `backend/.env` and add the environment-specific values.
- Azure Document Intelligence values belong in `backend/.env`; do not place service keys in the frontend.
- The frontend `.env.example` only controls the API base URL.
- No live credentials are included in this package.

## Demonstration sequence

1. Start the backend and frontend using the quick-start guide.
2. Upload the ten PDFs from `output/pdf/p90-demo-invoice-set/` in numeric order.
3. Switch between invoices on Overview or Documents and confirm the extracted values change.
4. Open Repair benchmarks to inspect Min, Max, Median, P90, exact challenge counts and source invoices.
5. Open Knowledge graph to inspect repeated repairer-to-item challenge patterns.
6. Open Review findings to inspect the billed price, P90, governed ontology/historical-claim evidence, final supported price and explanation.

The invoice being reviewed is excluded from its own P90. The final supported price uses the higher of P90 and any reliable governed ontology/historical-claim price. A challenge requires the billed price to exceed that supported price by the selected 5%/10% threshold and by at least £5.
