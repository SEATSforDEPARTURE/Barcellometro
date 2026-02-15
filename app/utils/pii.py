from __future__ import annotations

import re

EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,5}\d{2,4}(?!\w)")
IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", re.IGNORECASE)
CARD_CANDIDATE_RE = re.compile(r"(?:\d[ -]*){13,19}")
DISCORD_MENTION_RE = re.compile(r"<(?:@!?\d+|@&\d+|#\d+)>")
DISCORD_CHANNEL_URL_RE = re.compile(
    r"https?://(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/\d+/\d+(?:/\d+)?",
    re.IGNORECASE,
)
EXPLICIT_ADDRESS_RE = re.compile(
    r"\b(?:via|viale|piazza|piazzale|corso|strada|largo)\s+[A-ZÀ-ÖØ-Ýa-zà-öø-ÿ'\-\s]{3,}(?:,\s*\d+[A-Za-z]?)?",
    re.IGNORECASE,
)

_PATTERNS = [
    (EMAIL_RE, "[REDACTED_EMAIL]"),
    (IBAN_RE, "[REDACTED_IBAN]"),
    (EXPLICIT_ADDRESS_RE, "[REDACTED_ADDRESS]"),
]


def _luhn_valid(number: str) -> bool:
    total = 0
    reverse_digits = number[::-1]
    for idx, digit_char in enumerate(reverse_digits):
        digit = int(digit_char)
        if idx % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans = [m.span() for m in DISCORD_MENTION_RE.finditer(text)]
    spans.extend(m.span() for m in DISCORD_CHANNEL_URL_RE.finditer(text))
    return spans


def _overlaps_protected(span: tuple[int, int], protected_spans: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < protected_end and end > protected_start for protected_start, protected_end in protected_spans)


def _iter_valid_card_spans(text: str) -> list[tuple[int, int]]:
    valid_spans: list[tuple[int, int]] = []
    protected_spans = _protected_spans(text)
    for match in CARD_CANDIDATE_RE.finditer(text):
        span = match.span()
        if _overlaps_protected(span, protected_spans):
            continue
        normalized = re.sub(r"\D", "", match.group(0))
        if len(normalized) not in {13, 15, 16, 19}:
            continue
        if _luhn_valid(normalized):
            valid_spans.append(span)
    return valid_spans


def _iter_phone_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    protected_spans = _protected_spans(text)
    for match in PHONE_RE.finditer(text):
        span = match.span()
        if _overlaps_protected(span, protected_spans):
            continue
        normalized = re.sub(r"\D", "", match.group(0))
        if 7 <= len(normalized) <= 15:
            spans.append(span)
    return spans


def _redact_spans(text: str, spans: list[tuple[int, int]], replacement: str) -> tuple[str, bool]:
    if not spans:
        return text, False
    redacted = text
    for start, end in reversed(spans):
        redacted = f"{redacted[:start]}{replacement}{redacted[end:]}"
    return redacted, True


def redact_pii(text: str) -> tuple[str, bool]:
    redacted = text or ""
    had_pii = False
    for pattern, replacement in _PATTERNS:
        redacted, count = pattern.subn(replacement, redacted)
        had_pii = had_pii or count > 0
    redacted, had_cards = _redact_spans(redacted, _iter_valid_card_spans(redacted), "[REDACTED_CARD]")
    redacted, had_phones = _redact_spans(redacted, _iter_phone_spans(redacted), "[REDACTED_PHONE]")
    had_pii = had_pii or had_cards or had_phones
    return redacted, had_pii


def contains_pii(text: str) -> bool:
    candidate = text or ""
    return (
        any(pattern.search(candidate) for pattern, _ in _PATTERNS)
        or bool(_iter_valid_card_spans(candidate))
        or bool(_iter_phone_spans(candidate))
    )
