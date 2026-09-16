/** Per-row disclosure state for the extracts tables.
 *
 * The rule this file exists to enforce: **a user's choice is absolute.**
 *
 * These tables' defaults are recomputed from props on every render -- an
 * invoice is pre-expanded when it rolls its costs up into a section total
 * whose breakdown resolves, and is not when it runs past
 * `AUTO_EXPAND_LINE_LIMIT`. The Document Intelligence screen refetches after
 * every batch and after every page correction, so those inputs genuinely
 * change between two renders of the same row.
 *
 * Storing *departures from the default* therefore inverted a user's choice
 * whenever the default flipped underneath it: a row the reader opened closed
 * itself, a row they collapsed re-opened. Storing the resolved boolean
 * cannot: once a key is in the map, the default is no longer consulted for
 * it at all.
 */
export type ExpansionChoices = ReadonlyMap<string, boolean>

export const NO_EXPANSION_CHOICES: ExpansionChoices = new Map()

/** Whether a row is open: the user's own choice if they made one, otherwise
 * whatever the current props say the default is. */
export function isRowExpanded(
  choices: ExpansionChoices,
  key: string,
  fallback: boolean
) {
  return choices.get(key) ?? fallback
}

/** Record the opposite of what the row shows right now, as an absolute
 * choice. `fallback` is only read for a key the user has not touched yet. */
export function toggleRowExpansion(
  choices: ExpansionChoices,
  key: string,
  fallback: boolean
): ExpansionChoices {
  const next = new Map(choices)
  next.set(key, !isRowExpanded(choices, key, fallback))
  return next
}
