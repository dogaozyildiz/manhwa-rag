"""Turn a natural-language query into structured predicates.

This is the module that makes this project more than a vector-search demo.
"Completed romance manhwa under 100 chapters similar to Solo Leveling" is half
SQL and half embeddings. Sending the whole sentence to a vector store returns
plausible-looking results that quietly violate every numeric constraint — the
user asked for under 100 chapters and gets a 900-chapter series ranked first.

Extraction is rule-based first, deliberately:

* it is deterministic and unit-testable, so the eval measures something stable;
* it costs nothing and adds no latency;
* the phrasings that matter here ("under 100 chapters", "completed", "manhwa",
  "before 2015") are a small, closed set that regex handles precisely.

An LLM refinement pass is available for phrasings rules miss, but the rules run
first and the LLM may only *fill gaps*, never overwrite a confident match.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# AniList's genre vocabulary. Filters must use these exact strings, since they
# are compared against the `genres` array column.
KNOWN_GENRES = [
    "Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy", "Horror",
    "Mahou Shoujo", "Mecha", "Music", "Mystery", "Psychological", "Romance",
    "Sci-Fi", "Slice of Life", "Sports", "Supernatural", "Thriller",
]

# Words users actually type -> canonical genre.
GENRE_SYNONYMS = {
    "romantic": "Romance", "romcom": "Romance", "love story": "Romance",
    "scifi": "Sci-Fi", "science fiction": "Sci-Fi", "sf": "Sci-Fi",
    "slice-of-life": "Slice of Life", "iyashikei": "Slice of Life",
    "psychological thriller": "Psychological", "sports": "Sports",
    "magical girl": "Mahou Shoujo", "mecha": "Mecha", "horror": "Horror",
    "isekai": "Fantasy", "cultivation": "Fantasy", "murim": "Action",
}

# The domain's most load-bearing mapping: the word for the medium *is* a
# country-of-origin filter.
#
# "webtoon" is deliberately absent. It is a format and a platform name used
# generically ("what is a webtoon?"), so treating it as an origin marker
# silently attaches a Korea filter to general industry questions. "korean"
# already covers "korean webtoons".
ORIGIN_TERMS = {
    "manhwa": "KR", "korean": "KR",
    "manga": "JP", "japanese": "JP",
    "manhua": "CN", "chinese": "CN",
}

STATUS_TERMS = {
    "completed": "FINISHED", "finished": "FINISHED", "ended": "FINISHED",
    "complete": "FINISHED", "concluded": "FINISHED",
    "ongoing": "RELEASING", "releasing": "RELEASING", "running": "RELEASING",
    "currently airing": "RELEASING", "still going": "RELEASING",
    "hiatus": "HIATUS", "cancelled": "CANCELLED", "canceled": "CANCELLED",
}


@dataclass
class CatalogueFilters:
    country: str | None = None
    status: str | None = None
    min_chapters: int | None = None
    max_chapters: int | None = None
    min_year: int | None = None
    max_year: int | None = None
    genres: list[str] = field(default_factory=list)
    exclude_genres: list[str] = field(default_factory=list)
    min_score: int | None = None

    def is_empty(self) -> bool:
        return not any(
            [
                self.country, self.status, self.min_chapters, self.max_chapters,
                self.min_year, self.max_year, self.genres, self.exclude_genres,
                self.min_score,
            ]
        )

    def describe(self) -> list[str]:
        """Human-readable predicates, shown in the UI so the user can see what
        the system actually constrained on.

        ASCII only — these strings reach Windows consoles and log files, where
        cp1252 cannot encode characters like the greater-than-or-equal sign.
        """
        out: list[str] = []
        if self.country:
            out.append({"KR": "Korean", "JP": "Japanese", "CN": "Chinese"}.get(
                self.country, self.country))
        if self.status:
            out.append(self.status.lower())
        if self.min_chapters is not None:
            out.append(f">={self.min_chapters} chapters")
        if self.max_chapters is not None:
            out.append(f"<{self.max_chapters} chapters")
        if self.min_year is not None:
            out.append(f"from {self.min_year}")
        if self.max_year is not None:
            out.append(f"before {self.max_year}")
        for g in self.genres:
            out.append(g)
        for g in self.exclude_genres:
            out.append(f"not {g}")
        if self.min_score is not None:
            out.append(f"score >={self.min_score}")
        return out


_NUM = r"(\d{1,4})"
# The unit is REQUIRED, not optional. With it optional, "rated above 85" parsed
# as ">=85 chapters" — a comparison operator followed by a number is not enough
# to know what is being compared, and guessing produces filters the user never
# asked for.
_UNIT = r"\s*(?:chapters?|chs?|episodes?|eps?)"
_UNDER_RE = re.compile(
    rf"(?:under|below|less than|fewer than|shorter than|at most|max(?:imum)?|<)\s*{_NUM}{_UNIT}",
    re.I,
)
_OVER_RE = re.compile(
    rf"(?:over|above|more than|longer than|at least|min(?:imum)?|>)\s*{_NUM}{_UNIT}",
    re.I,
)
_BETWEEN_RE = re.compile(
    rf"between\s*{_NUM}\s*(?:and|-|to)\s*{_NUM}{_UNIT}", re.I
)
_BEFORE_YEAR_RE = re.compile(r"(?:before|prior to|earlier than|pre-?)\s*(\d{4})", re.I)
_AFTER_YEAR_RE = re.compile(r"(?:after|since|from|post-?)\s*(\d{4})", re.I)
_IN_YEAR_RE = re.compile(r"\b(?:in|during)\s*(\d{4})\b", re.I)
_SCORE_RE = re.compile(
    r"(?:score|rated|rating)\s*(?:of\s*)?(?:at least|above|over|>=?)?\s*(\d{1,3})", re.I
)
_EXCLUDE_RE = re.compile(r"(?:no|without|not|excluding|except)\s+([a-z\- ]{3,20})", re.I)


def _find_genres(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for phrase, canonical in GENRE_SYNONYMS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", lowered) and canonical not in found:
            found.append(canonical)
    for genre in KNOWN_GENRES:
        if re.search(rf"\b{re.escape(genre.lower())}\b", lowered) and genre not in found:
            found.append(genre)
    return found


def extract_filters(query: str) -> CatalogueFilters:
    """Rule-based extraction. Deterministic, free, and unit-tested."""
    filters = CatalogueFilters()
    lowered = query.lower()

    for term, country in ORIGIN_TERMS.items():
        if re.search(rf"\b{re.escape(term)}s?\b", lowered):
            filters.country = country
            break

    for term, status in STATUS_TERMS.items():
        if re.search(rf"\b{re.escape(term)}\b", lowered):
            filters.status = status
            break

    if (m := _BETWEEN_RE.search(query)) is not None:
        low, high = int(m.group(1)), int(m.group(2))
        filters.min_chapters, filters.max_chapters = min(low, high), max(low, high)
    else:
        if (m := _UNDER_RE.search(query)) is not None:
            filters.max_chapters = int(m.group(1))
        if (m := _OVER_RE.search(query)) is not None:
            filters.min_chapters = int(m.group(1))

    if (m := _BEFORE_YEAR_RE.search(query)) is not None:
        filters.max_year = int(m.group(1))
    if (m := _AFTER_YEAR_RE.search(query)) is not None:
        filters.min_year = int(m.group(1))
    if (m := _IN_YEAR_RE.search(query)) is not None:
        year = int(m.group(1))
        filters.min_year = filters.min_year or year
        filters.max_year = filters.max_year or year

    if (m := _SCORE_RE.search(query)) is not None:
        score = int(m.group(1))
        # Users say "rated 8" for a 0-100 scale stored as 80.
        filters.min_score = score * 10 if score <= 10 else score

    # Exclusions are checked before inclusions so "no romance" does not also
    # register Romance as a wanted genre.
    excluded: list[str] = []
    for m in _EXCLUDE_RE.finditer(query):
        for genre in _find_genres(m.group(1)):
            if genre not in excluded:
                excluded.append(genre)
    filters.exclude_genres = excluded
    filters.genres = [g for g in _find_genres(query) if g not in excluded]

    return filters


def strip_filter_terms(query: str) -> str:
    """Remove the constraint phrases, leaving the semantic remainder.

    "completed romance manhwa under 100 chapters like Solo Leveling"
      -> "like Solo Leveling"

    The remainder is what gets embedded. Leaving "under 100 chapters" in the
    embedded text pulls the vector toward series that *discuss* chapter counts,
    which is not what the user meant.

    An empty remainder is a meaningful result, not a failure: "completed
    romance manhwa" is a pure filter query with no semantic component, and the
    retrieval layer handles that by ranking on popularity instead of similarity.
    """
    text = query
    for pattern in (
        _BETWEEN_RE, _UNDER_RE, _OVER_RE, _BEFORE_YEAR_RE,
        _AFTER_YEAR_RE, _IN_YEAR_RE, _SCORE_RE,
    ):
        text = pattern.sub(" ", text)
    for term in list(ORIGIN_TERMS) + list(STATUS_TERMS):
        text = re.sub(rf"\b{re.escape(term)}s?\b", " ", text, flags=re.I)
    # Genre words became structured predicates, so drop them here too rather
    # than letting them pull the vector toward series that merely mention the
    # genre in their synopsis.
    for phrase in list(GENRE_SYNONYMS) + [g.lower() for g in KNOWN_GENRES]:
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.I)
    # Leftover connectives, exclusion words and ranking hints left behind by the
    # stripped constraints. These carry no semantic signal on their own, and
    # leaving them makes the embedded remainder noisier than an empty string.
    text = re.sub(
        r"\b(?:with|and|or|the|a|an|of|series|title|titles|chapters?|chs?|"
        r"no|not|without|excluding|except|best|top|good|great|rated|rating|"
        r"score|scored|popular|show|find|me|some|any)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    return text
