# ClaimGuard first-time-user UX audit

Date: 17 July 2026

## Verdict

The application is functionally rich but difficult for a first-time claims handler to understand. It exposes the product's data model and implementation concepts instead of guiding the handler through one clear case task.

## Journey findings

| Step | Screen | Health | Main first-time-user problem |
|---:|---|---|---|
| 1 | Claim & Liability | Poor | A long record, decision gate, statuses, checks, and evidence are presented together without a clear first action. |
| 2 | Navigation | Poor | The four-stage stepper conflicts with an eleven-screen sidebar; internal terms such as Ontology Mapping and Ontology Bank are exposed. |
| 3 | Upload & Processing | Fair–poor | A completed case still looks like an upload form and technical pipeline console; READY, ACTIVE, PASS, and draft states compete for attention. |
| 4 | Price Comparison | Poor | The user must interpret net/gross/MOT, policy weights, ontology, historical medians, scores, filters, and challenge status before understanding the decision required. |
| 5 | Challenge Review | Poor | The financial summary repeats, settlement appears before review completion, UUIDs are visible, and repeated generic actions do not explain why each line should be accepted or rejected. |

## Highest-priority redesign

1. Replace the exposed eleven-page information architecture with one guided case flow and one primary action per screen.
2. Add a case home that states what happened, what needs attention now, and what the handler should do next.
3. Use progressive disclosure: show unresolved tasks by default and move technical evidence, policy arithmetic, IDs, and audit detail into drawers or advanced views.
4. Use claims-handler language in the main flow; keep ontology and pipeline terminology in admin or evidence details.
5. Make the top stepper and navigation express the same workflow.
6. Make line decisions contextual and accessible, with line-specific action names and a plain-language reason for every challenge.
7. Offer settlement capture only after challenge decisions and finalisation.

## Accessibility risks observed

- Repeated `Accept`, `Edit`, and `Reject` controls have no line-specific accessible names.
- A disabled button is used as the status indicator for `2 decisions remaining`.
- Dense comparison tables are difficult on the observed narrow viewport.
- Screen changes occur through buttons without distinct routes, weakening browser history, deep linking, and orientation.

Keyboard order, focus management, zoom behaviour, and measured colour contrast were not exhaustively tested in this audit.

## Evidence

- `01-claim-liability.png`
- `02-navigation.png`
- `03-upload-processing.png`
- `04-price-comparison.png`
- `05-challenge-review.png`
