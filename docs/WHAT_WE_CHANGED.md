# What changed in this release — plain English

This release answers the 13 points of feedback from the review session. Instead
of patching each symptom, we fixed the six underlying causes. Here is the whole
story in simple terms.

## The problems, in one line each

The tool only read the five invoice formats it was built with; new documents
failed or vanished. New kinds of parts could never be priced. The maths looked
different on every screen. Approve buttons appeared broken. Source links went
nowhere. Word files needed software the laptop didn't have.

## What we did

### 1. Every document is now read — nothing fails, nothing disappears
- Documents the automatic reader cannot handle are no longer thrown away or
  marked FAILED. They are kept, shown, and sent to a **Manual review** tab.
- An AI now writes a short note on each such document: what it is, what was
  found inside, why it needs a human, and what to do next (ⓘ icon).
- If the automatic reader gets stuck but the text is readable, the document is
  sent to the AI to extract the lines (with personal data removed first). The
  AI can never invent prices — everything it extracts is re-checked and must be
  approved by a person.
- Word documents (.docx) now work on any machine — no extra software needed.
- Handlers can also type in invoice lines by hand for documents that cannot be
  read at all (photos without OCR, for example).

### 2. New kinds of parts and charges now get priced
- Before: the tool could only price the 72 items in its price book, and it
  sometimes matched a new item to the *nearest wrong* one (a radiator grille
  was priced using fan-belt prices).
- Now: weak matches are rejected outright. Unrecognised priced lines become
  **new price-book proposals** shown in Manual review — one click by a handler
  adds them to the price book, and from then on they are compared like any
  other item. Nothing enters a challenge letter until a person approves it.

### 3. One price calculation, explained step by step
- Before: three different formulas lived in different places, so the same line
  could say "within threshold" on one screen and "challenge" on another, and
  nobody could explain how a number was produced.
- Now: there is exactly **one** formula, computed once on the server:
  *supported price = 70% × P90 of the other uploaded invoices + 30% × the
  approved price-book price* (P90 alone when no approved price exists). A
  challenge still needs the billed price to be over the 5%/10% threshold AND
  at least £5 higher.
- Every line now carries a **"How this price was decided"** panel: every input,
  the weighting, both gate checks with pass/fail, and the result — identical
  on every screen, in the Excel export, and in the letter.

### 4. The review flow works in one place, with fewer clicks
- Approve buttons were never broken — they were waiting on a hidden step
  (approving the repair-item match) that lived three screens away. That
  approval now happens **inline** right where the evidence is shown, and the
  challenge button unlocks immediately.
- The Challenge decision page shows the real invoice totals at all times (no
  more £0.00), with approve/reject on each finding directly on the page.
- The Claim details page is gone; the challenged-invoices dropdown only lists
  invoices that actually have challenges.

### 5. Source references actually open
- Historical claim evidence opens a proper record window inside the app
  (invoice number, date, price, vehicle). References that were never web links
  (spreadsheet row citations) now display as citations instead of dead links.

### 6. Proven end to end
- 26 documents of every known format processed with zero failures; every price
  hand-recalculated and matched the server exactly; the full journey clicked
  through in a browser with no errors. See `docs/PHASE5_VERIFICATION.md`.
- The client's "Auda 7" style — the rolled-up calculation invoice, the Audatex
  Full Report (labour in work units, EXTRAS charges), and phone-photo pages —
  is replicated in `sample-data/auda-style/` with automated tests. All three
  process cleanly with an explanation instead of failing.

## What is needed to switch on the full AI behaviour

Three things on the machine that runs the demo (see
`docs/CLIENT_MACHINE_SETUP.md`, five minutes):

1. **An AI key** (Gemini or Azure OpenAI) — activates smart document reading,
   correct part matching, and AI explanations. Without it the tool still works
   but routes more documents to manual review.
2. **Azure Document Intelligence key** — only needed for scanned/photographed
   documents.
3. **A decision on the price formula** — `docs/PRICING_FORMULA_DECISION.md`
   offers options A/B/C; option A (the 70/30 formula above) is already live as
   the default and can be changed in configuration.

One open product question: Audatex reports price labour in *work units*, not
pounds. Turning those into money needs the insurer's agreed labour rate — a
business decision, not a software gap.
