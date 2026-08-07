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
