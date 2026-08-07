from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_REDACTIONS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    ("PHONE", re.compile(r"(?<!\w)(?:\+44\s?\d{4}|0\d{4})[\s-]?\d{3}[\s-]?\d{3}(?!\w)")),
    ("VIN", re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)),
    ("VRM", re.compile(r"\b[A-Z]{2}\d{2}\s?[A-Z]{3}\b", re.IGNORECASE)),
    ("POSTCODE", re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)),
    ("SORT_CODE", re.compile(r"\b\d{2}-\d{2}-\d{2}\b")),
    ("BANK_ACCOUNT", re.compile(r"\b\d{8}\b")),
)

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "IGNORE_INSTRUCTIONS",
        re.compile(r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions", re.IGNORECASE),
    ),
    (
        "SYSTEM_PROMPT_REQUEST",
        re.compile(r"(?:show|reveal|print|repeat)\s+(?:the\s+)?system\s+prompt", re.IGNORECASE),
    ),
    (
        "ROLE_OVERRIDE",
        re.compile(
            r"(?:you\s+are\s+now|act\s+as|developer\s+message|system\s+message)", re.IGNORECASE
        ),
    ),
    (
        "TOOL_INSTRUCTION",
        re.compile(
            r"(?:call|invoke|use)\s+(?:the\s+)?(?:tool|function|shell|terminal)", re.IGNORECASE
        ),
    ),
)


@dataclass(frozen=True)
class PreparedUntrustedText:
    text: str
    original_sha256: str
    redaction_counts: dict[str, int]
    prompt_injection_flags: tuple[str, ...]


def prepare_untrusted_text(value: str) -> PreparedUntrustedText:
    """Redact common pilot PII and frame document text as inert model data."""

    redacted = value
    counts: dict[str, int] = {}
    for label, pattern in _REDACTIONS:
        redacted, count = pattern.subn(f"[REDACTED_{label}]", redacted)
        if count:
            counts[label] = count
    flags = tuple(label for label, pattern in _INJECTION_PATTERNS if pattern.search(redacted))
    framed = f"<untrusted_document_text>\n{redacted}\n</untrusted_document_text>"
    return PreparedUntrustedText(
        text=framed,
        original_sha256=hashlib.sha256(value.encode("utf-8")).hexdigest(),
        redaction_counts=counts,
        prompt_injection_flags=flags,
    )
