"""AniList GraphQL client for the catalogue corpus.

No API key required for public media data. Responses are cached to
`data/raw/anilist_{country}.json` so the corpus is fetched once and every later
run — tests, re-ingests, eval sweeps — works offline and puts no load on a free
public API.

Rate limiting is real here, so requests are paced and 429s are retried against
the `Retry-After` header rather than a guessed backoff.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import httpx

ANILIST_URL = "https://graphql.anilist.co"
PER_PAGE = 50  # AniList's maximum

QUERY = """
query ($page: Int, $perPage: Int, $country: CountryCode) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { currentPage hasNextPage }
    media(type: MANGA, countryOfOrigin: $country, sort: POPULARITY_DESC,
          isAdult: false) {
      id
      title { romaji english native }
      synonyms
      description(asHtml: false)
      countryOfOrigin
      format
      status
      chapters
      volumes
      startDate { year }
      endDate { year }
      genres
      tags { name rank isGeneralSpoiler }
      averageScore
      popularity
      siteUrl
    }
  }
}
"""


@dataclass(frozen=True)
class FetchPlan:
    country: str
    limit: int


async def _post(client: httpx.AsyncClient, variables: dict) -> dict:
    """One GraphQL call, retrying on rate limit using the server's own hint."""
    for attempt in range(6):
        resp = await client.post(
            ANILIST_URL, json={"query": QUERY, "variables": variables}, timeout=30.0
        )
        if resp.status_code == 429:
            # Trust Retry-After when present; AniList sets it.
            wait = float(resp.headers.get("Retry-After", 2**attempt))
            print(f"    rate limited, waiting {wait:.0f}s")
            await asyncio.sleep(wait)
            continue
        resp.raise_for_status()
        payload = resp.json()
        if "errors" in payload:
            raise RuntimeError(f"AniList error: {payload['errors']}")
        return payload["data"]["Page"]
    raise RuntimeError("AniList: still rate limited after 6 attempts")


async def fetch_country(country: str, limit: int) -> list[dict]:
    """Fetch the most popular `limit` series for a country of origin."""
    out: list[dict] = []
    async with httpx.AsyncClient(headers={"Accept": "application/json"}) as client:
        page = 1
        while len(out) < limit:
            data = await _post(
                client, {"page": page, "perPage": PER_PAGE, "country": country}
            )
            media = data["media"]
            if not media:
                break
            out.extend(media)
            print(f"    {country} page {page}: +{len(media)} (total {len(out)})")
            if not data["pageInfo"]["hasNextPage"]:
                break
            page += 1
            # Pace requests: this is a free public API, and hammering it is both
            # rude and the fastest way to get rate limited.
            await asyncio.sleep(1.0)
    return out[:limit]


async def fetch_catalogue(plans: list[FetchPlan], cache_dir: Path) -> list[dict]:
    """Fetch every plan, caching each country's raw response to disk."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    all_media: list[dict] = []

    for plan in plans:
        cache = cache_dir / f"anilist_{plan.country}.json"
        if cache.exists():
            media = json.loads(cache.read_text(encoding="utf-8"))
            if len(media) >= plan.limit:
                print(f"  {plan.country}: {len(media)} from cache")
                all_media.extend(media[: plan.limit])
                continue
        print(f"  {plan.country}: fetching {plan.limit} ...")
        media = await fetch_country(plan.country, plan.limit)
        cache.write_text(json.dumps(media, ensure_ascii=False), encoding="utf-8")
        all_media.extend(media)

    return all_media
