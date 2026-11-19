"""M1: deterministic output filter for links and contact details.

Red-team baseline (redteam/BASELINE_RESULTS.md): a poisoned source got an
attacker's link into 78% of answers, and into *verified* claims, because the
quote really was verbatim in the poisoned source. M2 (prompt hardening) cut that
to 44% and no further -- a prompt is a request, and the model found a loophole
in it ("the user asked where to read, so a link is fine").

This module is the guarantee instead of the request: any URL, bare domain or
email address in model output whose host is not on an allowlist is removed from
the answer text, and any claim carrying one is rejected. It runs after the
citation verifier, so a verified-but-poisoned quote is still caught.

It cannot catch a falsehood that contains no link (payload `false`). That needs
source-trust checks (M4).
"""

from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlsplit

from app.answer.schema import Claim

REMOVED = "[link removed]"

_URL = re.compile(r"(?i)\b(?:https?://|www\.)[^\s<>\"')\]]+")
# Bare domains such as "evil-site.example" or "free-reads.xyz/login".
_BARE_DOMAIN = re.compile(
    r"(?i)(?<![@\w.-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|net|org|io|co|app|site|online|info|biz|xyz|top|link|click|me|ru|cn|tk|example|test)"
    r"\b(?:/[^\s<>\"')\]]*)?"
)
_EMAIL = re.compile(r"(?i)\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")


def _host(candidate: str) -> str:
    raw = candidate if "://" in candidate else f"http://{candidate}"
    return (urlsplit(raw).hostname or "").lower().rstrip(".")


def is_allowed(candidate: str, allowlist: list[str]) -> bool:
    host = _host(candidate)
    return any(host == d or host.endswith("." + d) for d in allowlist)


def find_untrusted(text: str, allowlist: list[str]) -> list[str]:
    """All links/domains/emails in `text` that are not on the allowlist."""
    found: list[str] = []
    for m in _EMAIL.finditer(text):
        found.append(m.group(0))
    no_email = _EMAIL.sub(" ", text)
    for pattern in (_URL, _BARE_DOMAIN):
        for m in pattern.finditer(no_email):
            token = m.group(0).rstrip(".,;:!?")
            if not is_allowed(token, allowlist) and token not in found:
                found.append(token)
        no_email = pattern.sub(" ", no_email)
    return found


def scrub(text: str, allowlist: list[str]) -> tuple[str, list[str]]:
    """Replace untrusted links in `text`. Returns (clean_text, removed)."""
    removed = find_untrusted(text, allowlist)
    clean = text
    for token in sorted(removed, key=len, reverse=True):
        clean = clean.replace(token, REMOVED)
    return clean, removed


def filter_output(
    answer_text: str, claims: list[Claim], allowlist: list[str]
) -> tuple[str, list[Claim], list[str]]:
    """Scrub the answer and reject claims that carry untrusted links.

    Returns (clean_answer, claims, removed_tokens). A rejected claim keeps its
    text for the eval report but is marked unverified with a reason, so it is
    counted in `rejected_claims` -- the operator gets a signal.
    """
    clean_answer, removed = scrub(answer_text, allowlist)
    out: list[Claim] = []
    for c in claims:
        bad = find_untrusted(f"{c.text}\n{c.quote}", allowlist)
        if bad and c.verified:
            removed.extend(t for t in bad if t not in removed)
            out.append(replace(c, verified=False, reason=f"contains untrusted link {bad[0]!r}"))
        else:
            out.append(c)
    return clean_answer, out, removed
