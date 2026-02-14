from __future__ import annotations

import re

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,5}\d{2,4}(?!\w)")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.IGNORECASE)
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
EXPLICIT_ADDRESS_RE = re.compile(
    r"\b(?:via|viale|piazza|piazzale|corso|strada|largo)\s+[A-ZÀ-ÖØ-Ýa-zà-öø-ÿ'\-\s]{3,}(?:,\s*\d+[A-Za-z]?)?",
    re.IGNORECASE,
)

_PATTERNS = [
    (EMAIL_RE, "[REDACTED_EMAIL]"),
    (PHONE_RE, "[REDACTED_PHONE]"),
    (IBAN_RE, "[REDACTED_IBAN]"),
    (CARD_RE, "[REDACTED_CARD]"),
    (EXPLICIT_ADDRESS_RE, "[REDACTED_ADDRESS]"),
]


def redact_pii(text: str) -> tuple[str, bool]:
    redacted = text or ""
    had_pii = False
    for pattern, replacement in _PATTERNS:
        redacted, count = pattern.subn(replacement, redacted)
        had_pii = had_pii or count > 0
    return redacted, had_pii


def contains_pii(text: str) -> bool:
    candidate = text or ""
    return any(pattern.search(candidate) for pattern, _ in _PATTERNS)
