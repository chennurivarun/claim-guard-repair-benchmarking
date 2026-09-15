from __future__ import annotations

import re

DEFAULT_ABBREVIATIONS: dict[str, str] = {
    "FRT": "front",
    "N/S": "nearside",
    "NS": "nearside",
    "O/S": "offside",
    "OS": "offside",
    "ASSY": "assembly",
    "R&R": "remove and replace",
    "R&I": "remove and install",
    "S/PLUGS": "spark plugs",
    "DISC": "disc",
    "PADS": "pads",
}

UNIT_ALIASES: dict[str, str] = {
    "ea": "each",
    "each": "each",
    "unit": "each",
    "set": "set",
    "pair": "pair",
    "hr": "hour",
    "hrs": "hour",
    "hour": "hour",
    "hours": "hour",
    "job": "job",
    "l": "litre",
    "ltr": "litre",
    "litre": "litre",
    "test": "test",
}


def strip_scan_artifacts(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"[█▉▊▋▌▍▎▏]+", " ", value)
    value = value.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", value).strip()


def normalise_description(value: str, abbreviations: dict[str, str] | None = None) -> str:
    abbreviations = abbreviations or DEFAULT_ABBREVIATIONS
    text = strip_scan_artifacts(value).upper()
    for abbreviation, expanded in sorted(
        abbreviations.items(), key=lambda item: len(item[0]), reverse=True
    ):
        text = re.sub(
            rf"(?<![A-Z0-9]){re.escape(abbreviation)}(?![A-Z0-9])",
            expanded.upper(),
            text,
        )
    text = re.sub(r"[^A-Z0-9/&+.-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def normalise_unit(value: str | None, *, item_kind: str | None = None) -> str:
    cleaned = strip_scan_artifacts(value).lower().rstrip("s")
    if cleaned in UNIT_ALIASES:
        return UNIT_ALIASES[cleaned]
    if item_kind == "labour":
        return "hour"
    if item_kind in {"service", "fee", "disposal"}:
        return "job"
    return cleaned or "each"


#: The one separator a printed identifier carries meaning in. Everything else
#: is presentation and is dropped.
IDENTIFIER_SEPARATOR = "/"


def normalise_identifier(value: str | None) -> str | None:
    """Comparison form of a printed identifier: uppercase, alphanumeric and "/".

    Registrations, claim references and policy numbers are printed with
    whatever spacing and punctuation the issuing system uses, so one identity
    reads two ways across a pair of documents: ``AB12 XYZ`` -> ``AB12XYZ``,
    ``PL-739284`` -> ``PL739284``, ``245338996 / 1`` -> ``245338996/1``.

    ``/`` survives because the client's claim references are
    ``base/incident``: ``123456/1`` and ``123456/2`` are two claims on one
    policy, and dropping the separator would also collide ``123456/1`` with
    the unrelated ``1234561``. No registration or policy number prints a
    ``/``, so ``normalise_registration`` is unaffected by keeping it.

    A value with no alphanumeric content is not an identifier, so it
    normalises to ``None`` and is treated as "not printed".
    """

    normalised = "".join(
        character
        for character in (value or "").upper()
        if character.isalnum() or character == IDENTIFIER_SEPARATOR
    )
    return normalised if any(character.isalnum() for character in normalised) else None
