# Pricing formula — decision note

**For:** product owner sign-off · **Needed before:** the unified-calculation release is finalised
**Default if no preference is stated:** Option A (already implemented behind a policy constant; changing option is a configuration change, not a rework)

ClaimGuard historically computed a supported price in three overlapping ways
(a backend ontology/history consensus, a screen-side P90 blend, and the engineer
comparison stream). The remediation consolidates to **one formula, computed once,
with a step-by-step explanation stored for every line**. Please choose the formula.

## Option A — P90-anchored blend (recommended)

> Supported price = 70% × uploaded-invoice P90 + 30% × approved governed price.
> When no approved governed price exists, the P90 stands alone.

- P90 is the interpolated 90th percentile (PERCENTILE.INC) of earlier matching
  invoice lines in the claim batch, always excluding the invoice under review,
  requiring at least 3 observations.
- A challenge still requires the billed price to exceed the supported price by
  the selected 5% or 10% threshold **and** by at least £5.
- Why recommended: it matches what the screens already tell handlers, anchors on
  observed market prices from the claim itself, and uses governed prices as a
  moderating input rather than the whole answer.

## Option B — Higher-of

> Supported price = the higher of the P90 and any reliable approved governed price.

- Most generous to the repairer; produces the fewest challenges.
- Simplest to explain ("we allow the higher of market and approved price").

## Option C — Governed consensus

> Supported price = 60% approved ontology price + 40% eligible historical
> weighted median; P90 used only when neither is available.

- The original pilot design. Strongest dependence on the ontology price book,
  which is only as good as its coverage — new or unusual repairs fall back badly.

## What does not change under any option

- The £5 + 5%/10% dual gate, VAT shown separately, MOT outside VAT.
- Engineer assessments stay a separate, clearly-labelled evidence stream and are
  never mixed into the P90 population.
- Cheaper lines never offset the challenge; provisional evidence never enters an
  issued letter; every input, weight, and gate check is stored per line and shown
  to the handler.

**Sign-off:** reply with A, B, or C (and any threshold preference).
