"""Cleaning for AniList descriptions and Wikipedia extracts.

AniList descriptions are user-edited and messy in specific, repeatable ways:
HTML tags (`<br>`, `<i>`, `<b>`), attribution footers (`(Source: Tappytoon)`),
and editorial notes (`Note: Includes 22 extra chapters.`). All three hurt
retrieval — the attribution footer in particular is near-identical across
hundreds of records, so leaving it in makes unrelated series look similar to
each other and to any query mentioning a platform name.
"""

from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]+>")
_SOURCE_RE = re.compile(r"\(\s*Source\s*:.*?\)", re.I | re.S)
_NOTE_RE = re.compile(r"^\s*note\s*:.*$", re.I | re.M)
_WS_RUN_RE = re.compile(r"[ \t]+")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def clean_description(raw: str | None) -> str:
    """AniList synopsis -> plain prose."""
    if not raw:
        return ""
    text = html.unescape(raw)
    # <br> carries paragraph structure; convert before stripping other tags.
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = _TAG_RE.sub("", text)
    text = _SOURCE_RE.sub("", text)
    text = _NOTE_RE.sub("", text)
    text = _WS_RUN_RE.sub(" ", text)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


def clean_wikipedia(raw: str) -> str:
    """Wikipedia plain-text extract -> markdown-ish headings for the chunker.

    The extract uses `== Section ==` markers. Converting them to `##` lets the
    carried-over heading-aware chunker do its job unchanged.
    """
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        match = re.match(r"^(={2,6})\s*(.+?)\s*\1$", stripped)
        if match:
            level = len(match.group(1))
            lines.append(f"{'#' * level} {match.group(2)}")
        else:
            lines.append(line)
    text = "\n".join(lines)
    text = _BLANK_RUN_RE.sub("\n\n", text)
    return text.strip()


def drop_boilerplate_sections(text: str) -> str:
    """Remove reference/navigation sections that carry no answerable content."""
    drop = {
        "references",
        "external links",
        "see also",
        "further reading",
        "notes",
        "bibliography",
        "sources",
        "footnotes",
    }
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        heading = re.match(r"^(#{2,6})\s+(.*)$", line)
        if heading:
            skipping = heading.group(2).strip().lower() in drop
        if not skipping:
            out.append(line)
    return _BLANK_RUN_RE.sub("\n\n", "\n".join(out)).strip()


def normalise_title(title: str) -> str:
    """Fold a title for fuzzy comparison.

    Lowercases, strips punctuation and collapses whitespace, so that
    "Kimetsu no Yaiba", "kimetsu-no-yaiba" and "Kimetsu no Yaiba!" all reduce to
    the same key. Deliberately does NOT strip non-Latin script — Korean and
    Japanese titles must survive intact, since they are the aliases users
    actually type.
    """
    text = html.unescape(title).lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return _WS_RUN_RE.sub(" ", text).strip()


def collect_titles(media: dict) -> list[str]:
    """Every distinct alias for a series, in preference order.

    Preserves original casing and script — the trigram index matches on these
    directly, and a user searching "나 혼자만 레벨업" needs the native string
    present verbatim.
    """
    title = media.get("title") or {}
    candidates = [
        title.get("english"),
        title.get("romaji"),
        title.get("native"),
        *(media.get("synonyms") or []),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for candidate in candidates:
        if not candidate:
            continue
        key = normalise_title(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(candidate.strip())
    return out
