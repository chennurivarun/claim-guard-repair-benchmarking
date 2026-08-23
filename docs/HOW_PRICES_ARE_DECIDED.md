# How a price is decided — one page

Every challenged line follows the same five steps. The same numbers appear on
every screen, in the Excel export, and in the letter. The on-screen
"How the price was calculated" panel shows these exact steps for each line.

## The five steps (worked example from a real line)

A garage billed **£266.00** for "Carried Out Full Service".

| Step | What happens | Example |
| --- | --- | --- |
| 1. Market signal (P90) | Take the 90th-percentile price of the **other** invoices in this claim batch for the same repair item. The invoice being checked is never counted in its own benchmark. Needs at least 3 comparable prices. | 7 earlier invoices → **£216.60** |
| 2. Approved price | The price book (ontology) value for this item, if one has been approved. | **£138.00** |
| 3. Blend | 70% × P90 + 30% × approved price. If only one of the two exists, that one is used alone. | 0.7 × 216.60 + 0.3 × 138.00 = **£193.02** |
| 4. Supported price | The lower of the billed price and the blend — we never support more than was billed. | min(266.00, 193.02) = **£193.02** |
| 5. Gates | Challenge only if the difference beats BOTH gates: more than the 10% (or 5%) threshold AND at least £5. | 266.00 − 193.02 = **£72.98** → 37.8% over and > £5 → **CHALLENGE £72.98** |

VAT impact is shown separately (20% × 72.98 = £14.60). MOT fees stay outside VAT.

## Numbers you may see that are NOT part of the calculation

- **Historical claims median** (e.g. £100.00) — context from the governed
  claims history, shown for reference. It is labelled "Context only" on screen.
- **Engineer gate results** — the engineer-assessment comparison is a separate
  evidence stream with its own gate; it never mixes into this price.

## Why a line shows no challenge

Any one of these, and the line is "Within":
- fewer than 3 comparable prices for the P90 (new item — approve its
  price-book proposal in Manual review and it builds history),
- the repair-item match is not yet approved (approve it inline),
- the difference fails either gate (under threshold % or under £5).

## The rules that never change

Cheaper lines never offset a challenge. Nothing AI-extracted or provisional
enters a letter until a person approves it. Every input, weight, and gate
check is stored per line and visible to the handler.
