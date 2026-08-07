# ClaimGuard product overview

## The product in one sentence

ClaimGuard is an invoice-checking assistant for UK motor insurance claims. A repair garage sends an invoice; ClaimGuard checks every line, finds prices that appear too high, explains the evidence, and helps a human claims handler create a challenge package.

ClaimGuard does not make the final decision. The claims handler does.

## Simple example

| Item | Amount |
| ---- | -----: |
| Garage invoice — net | £643.26 |
| Challenge Price — proposed payable | £546.51 |
| Potential net saving | £96.75 |
| VAT impact | Shown separately |
| MOT | Kept outside VAT calculations |

`£546.51` is always described as the **Challenge Price**. “Proposed payable” is supporting text, not a competing headline term.

## Who uses it?

The primary user is an insurer's **claims handler**. They need to answer three questions:

1. Is the invoice information correct?
2. Are any parts or labour prices unreasonable?
3. What amount should be challenged, and what evidence supports it?

## Complete workflow

| Step | What happens |
| ---: | ------------ |
| 1. Upload | The handler uploads invoice PDFs or Excel files. |
| 2. Read documents | The system separates and classifies document pages. |
| 3. Extract | Garage, vehicle, invoice totals and line items are extracted. |
| 4. Check arithmetic | Quantity, unit price, net, VAT and totals are validated. |
| 5. Map items | Invoice descriptions are matched to standard parts and labour items. |
| 6. Compare prices | Prices are compared with the approved price bank and previous invoices. |
| 7. Flag findings | Lines above the policy limits are marked for review. |
| 8. Human review | The handler accepts, adjusts or rejects each finding. |
| 9. Approve | The handler checks the complete financial summary. |
| 10. Generate output | The system creates the challenge letter, evidence schedule and audit record. |
| 11. Record settlement | The final agreed amount can be captured later. |

## The four main screens

### 1. Overview

The Overview tells the handler:

- Which claim they are reviewing
- What stage the case has reached
- What action they need to take next
- The original invoice amount
- The Challenge Price
- The potential saving
- Why the invoice was challenged

A first-time user should immediately understand: **“Two invoice lines need my decision.”**

### 2. Documents

Documents contains everything related to uploaded files:

- PDF and Excel upload
- Processing status
- Document-page classification
- Extracted invoice data
- Corrections to wrongly extracted information

### 3. Review findings

This is the main working screen. The handler reviews one challenged line at a time with the decision and evidence kept together.

| Information | Example |
| ----------- | ------: |
| Garage charged | £20.02 |
| Approved price-bank value | £12.42 |
| Historic median | £13.27 |
| Recommended Challenge Price | £13.27 |
| Potential saving | £6.75 |

The handler can:

- **Accept Challenge Price**
- **Adjust amount**
- **Do not challenge**
- Open the detailed evidence and persisted comparable observations

### 4. Approve challenge

This is the final confirmation screen. It shows:

- Accepted findings
- Original net invoice
- Challenge Price
- Net saving
- VAT impact
- Gross cash effect
- MOT treatment
- Files that will be generated

The handler then selects **Generate challenge package**. Settlement capture becomes available after the package has been issued.

## What is inside Administration?

The main sidebar stays simple. Less-frequent and more technical tools remain under Administration.

| Tool | Purpose |
| ---- | ------- |
| Document pages | Inspect how pages were classified. |
| Extracted invoice | Review every extracted field and line. |
| Calculation checks | Inspect totals, VAT and arithmetic. |
| Ontology mapping | See which standard item each invoice line matched. |
| Missing items | Research items not found in the approved price bank. |
| Ontology bank | Manage approved parts, labour and reference prices. |
| Audit trail | See every system and human action. |
| Reports | Download JSON, Excel, PDF, DOCX or SQLite outputs. |

No features are removed. They are organised according to how frequently a claims handler needs them.

## How ClaimGuard calculates a supported price

For a matched invoice line, the default policy uses:

- **60% approved ontology price**
- **40% historical invoice median**

A challenge is normally raised only when the positive difference passes both gates:

- At least **£5**
- At least **5%**

The challenge is based on the **net line total**, so quantity padding is included in the assessment. These weights and gates live in versioned policy configuration rather than being permanently hard-coded. Every result records the policy version used.

## What is the ontology bank?

“Ontology” is the product's approved catalogue of repair items.

| Garage description | Standard item |
| ------------------ | ------------- |
| Air Filter Element | Engine air filter |
| Oil Service Labour | Full-service labour |
| Front Pads & Discs Fit | Front brake fitting labour |

The bank stores:

- Standard item name
- Part or labour category
- Unit
- Approved net price
- Evidence source
- Approval status
- Version history

This allows differently worded garage invoices to be compared consistently.

## What happens when an item is missing?

The handler sees a **Research** button. For the pilot:

1. Research starts only when the handler clicks.
2. The result remains provisional.
3. The handler reviews and approves it.
4. One approval writes the item to the ontology bank.
5. The claim is recalculated.

Automatic research is disabled by default with `auto_research: false`. A second reviewer can be enabled later using `two_step_approval: true` without changing the workflow's core data model.

## Liability rule

ClaimGuard does not decide who caused the accident. The system can check whether the claim and invoice are consistent, but a human handler must confirm liability.

Challenge issuance is normally available when liability is human-confirmed as:

- **ADMITTED**
- **SPLIT LIABILITY**

Other statuses can still use draft invoice analysis, but final issuance remains gated.

## Technology underneath

| Layer | Technology | Responsibility |
| ----- | ---------- | -------------- |
| Frontend | React + TypeScript | User interface and handler workflow |
| Design system | shadcn + Tailwind CSS | Consistent components and styling |
| Icons | Lucide | Minimal, understandable interface icons |
| Backend | FastAPI | Processing and business APIs |
| Database | SQLite | Claims, evidence, decisions and audit data |
| Documents | PDF and Excel pipeline | Uploading, reading and generating files |
| Policy | Versioned YAML | Weights, gates and configurable rules |
| Reports | PDF, DOCX, Excel, JSON and SQLite | Negotiation and audit outputs |

## What is stored for audit?

ClaimGuard keeps machine suggestions and human decisions separate. It records:

- Original uploaded documents
- Extracted values
- Corrections
- Ontology mappings
- Price evidence
- Policy version
- System recommendation
- Handler decision and rationale
- Final generated outputs
- Settlement amount
- Timestamps and record hashes

An auditor can later answer: **“Why did we challenge this line, who approved it, and what evidence was used?”**

## The product's real value

ClaimGuard is not merely a PDF reader. It turns this:

> “Here is a messy garage invoice—please investigate it.”

Into this:

> “These two lines are overpriced, here is the supporting evidence, here is the recommended payable amount, and here is an audit-ready challenge package.”

That is the complete product in its simplest form.
