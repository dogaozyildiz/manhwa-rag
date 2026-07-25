"""Turn a raw AniList record into a database-ready series row.

The interesting part is `build_card`. This corpus inverts the usual RAG
chunking problem: instead of documents too long to embed, catalogue records are
too *short* and too *similar*. A bare 300-character synopsis embeds into
something almost indistinguishable from every other action-fantasy synopsis,
and carries none of the facts a user actually asks about.

So each record is composed into a card that leads with every alias and states
the facts in prose before the synopsis. This is what gets embedded; the typed
columns still drive filtering.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.ingest.clean import clean_description, collect_titles

# Tags below this AniList rank are noise — long-tail descriptors that appear on
# hundreds of series and blur the embedding rather than sharpening it.
MIN_TAG_RANK = 60
MAX_TAGS = 12

COUNTRY_LABEL = {
    "KR": "Korean manhwa",
    "JP": "Japanese manga",
    "CN": "Chinese manhua",
    "TW": "Taiwanese manhua",
}

STATUS_LABEL = {
    "FINISHED": "Completed",
    "RELEASING": "Ongoing",
    "NOT_YET_RELEASED": "Not yet released",
    "CANCELLED": "Cancelled",
    "HIATUS": "On hiatus",
}


@dataclass
class SeriesRecord:
    anilist_id: int
    title_romaji: str | None
    title_english: str | None
    title_native: str | None
    titles: list[str]
    titles_blob: str
    description: str
    card: str
    country: str | None
    format: str | None
    status: str | None
    chapters: int | None
    volumes: int | None
    start_year: int | None
    end_year: int | None
    genres: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    average_score: int | None = None
    popularity: int | None = None
    site_url: str | None = None

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.card.encode("utf-8")).hexdigest()

    @property
    def display_title(self) -> str:
        return self.title_english or self.title_romaji or self.title_native or "Untitled"


def _select_tags(raw_tags: list[dict] | None) -> list[str]:
    if not raw_tags:
        return []
    kept = [
        t["name"]
        for t in raw_tags
        # Spoiler tags are excluded: surfacing "Character Death" as a retrieval
        # signal would spoil the series to anyone browsing the catalogue.
        if not t.get("isGeneralSpoiler") and (t.get("rank") or 0) >= MIN_TAG_RANK
    ]
    return kept[:MAX_TAGS]


def build_card(
    *,
    titles: list[str],
    country: str | None,
    status: str | None,
    chapters: int | None,
    start_year: int | None,
    end_year: int | None,
    genres: list[str],
    tags: list[str],
    average_score: int | None,
    description: str,
) -> str:
    """Compose the text that actually gets embedded.

    Facts are written as prose rather than `key: value` because the embedding
    model was trained on prose — "Completed Korean manhwa with 201 chapters"
    embeds closer to a natural-language query than "status=FINISHED".
    """
    primary = titles[0] if titles else "Untitled"
    aliases = [t for t in titles[1:] if t]
    header = primary
    if aliases:
        header += f" (also known as {' · '.join(aliases[:6])})"

    facts: list[str] = []
    if country:
        facts.append(COUNTRY_LABEL.get(country, country))
    if status:
        facts.append(STATUS_LABEL.get(status, status.title()))
    if chapters:
        facts.append(f"{chapters} chapters")
    if start_year:
        span = f"started {start_year}"
        if end_year and end_year != start_year:
            span = f"ran {start_year}–{end_year}"
        elif end_year:
            span = f"published {start_year}"
        facts.append(span)
    if average_score:
        facts.append(f"average score {average_score}/100")

    parts = [header]
    if facts:
        parts.append(". ".join(facts) + ".")
    if genres:
        parts.append(f"Genres: {', '.join(genres)}.")
    if tags:
        parts.append(f"Themes: {', '.join(tags)}.")
    if description:
        parts.append(description)
    return "\n".join(parts)


def to_record(media: dict) -> SeriesRecord | None:
    """Raw AniList media -> SeriesRecord, or None if unusable."""
    titles = collect_titles(media)
    if not titles:
        return None

    description = clean_description(media.get("description"))
    genres = list(media.get("genres") or [])
    tags = _select_tags(media.get("tags"))
    title = media.get("title") or {}
    start = (media.get("startDate") or {}).get("year")
    end = (media.get("endDate") or {}).get("year")

    card = build_card(
        titles=titles,
        country=media.get("countryOfOrigin"),
        status=media.get("status"),
        chapters=media.get("chapters"),
        start_year=start,
        end_year=end,
        genres=genres,
        tags=tags,
        average_score=media.get("averageScore"),
        description=description,
    )

    return SeriesRecord(
        anilist_id=media["id"],
        title_romaji=title.get("romaji"),
        title_english=title.get("english"),
        title_native=title.get("native"),
        titles=titles,
        # Newline-joined so trigram matching cannot bleed across alias
        # boundaries and invent a match spanning two different titles.
        titles_blob="\n".join(titles),
        description=description,
        card=card,
        country=media.get("countryOfOrigin"),
        format=media.get("format"),
        status=media.get("status"),
        chapters=media.get("chapters"),
        volumes=media.get("volumes"),
        start_year=start,
        end_year=end,
        genres=genres,
        tags=tags,
        average_score=media.get("averageScore"),
        popularity=media.get("popularity"),
        site_url=media.get("siteUrl"),
    )
