import type { PairKeyVerdict } from "@/lib/api"

/** How a pairing link should be described to a claims handler.
 *
 * Not as a percentage. Under the "compare only what both documents print"
 * rule, `pair_confidence` is matched keys over *compared* keys, so every
 * surviving pair scores 1.0 -- a link resting on a registration alone reads
 * "100%" beside prose saying "weak pair: only the registration was
 * comparable". The badge is what gets read, so the badge has to carry the
 * denominator: how many identities actually agreed, out of how many could be
 * compared at all, and why the rest were skipped.
 *
 * This is the spec's own requirement -- "the UI must say which keys were
 * compared and which were skipped for absence" -- rather than a number that
 * is now constant by construction. */
export interface PairKeySummary {
  /** e.g. "2 of 2 printed identities agree". Null when nothing was compared. */
  agreement: string | null
  /** The sentence for every key that could not be compared, in key order. */
  skipped: string[]
  /** The sentence for every key that was compared and disagreed. A conflict
   * is fatal, so this is only ever non-empty on an unpaired assessment. */
  conflicts: string[]
  /** Agreement and skips joined for a one-line badge. */
  headline: string | null
}

function agreementPhrase(matched: number, compared: number) {
  return compared === 1
    ? `${matched} of 1 printed identity agrees`
    : `${matched} of ${compared} printed identities agree`
}

export function summarisePairKeyVerdicts(
  verdicts: PairKeyVerdict[] | null | undefined
): PairKeySummary {
  const rows = verdicts ?? []
  const compared = rows.filter((verdict) => verdict.compared)
  const matched = compared.filter((verdict) => verdict.state === "matched")
  const conflicts = compared
    .filter((verdict) => verdict.state === "conflict")
    .map((verdict) => verdict.text)
  const skipped = rows
    .filter((verdict) => !verdict.compared)
    .map((verdict) => verdict.text)
  const agreement =
    compared.length === 0
      ? rows.length === 0
        ? null
        : "No printed identity could be compared"
      : agreementPhrase(matched.length, compared.length)
  const headline =
    agreement == null
      ? null
      : [agreement, ...conflicts, ...skipped].join(" · ")
  return { agreement, skipped, conflicts, headline }
}

/** The badge text for a pairing link. Falls back to the bare status -- never
 * to a percentage -- when the payload carries no per-key verdicts. */
export function pairKeyBadgeText(
  verdicts: PairKeyVerdict[] | null | undefined,
  pairStatus: string | null | undefined
) {
  const { headline } = summarisePairKeyVerdicts(verdicts)
  if (headline) return headline
  return pairStatus === "paired"
    ? "Paired · no per-key pairing evidence recorded"
    : "Not paired · no per-key pairing evidence recorded"
}
