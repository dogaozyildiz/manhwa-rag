"""Wikipedia client for the industry-prose corpus.

Uses the MediaWiki action API with `extracts` in plain-text mode, which returns
readable section-headed prose rather than wikitext markup. Cached to
`data/raw/wikipedia.json` so later runs need no network.

The article list is the *industry*, not individual series — publishers,
platforms, formats, business models. Series facts belong in the catalogue half;
duplicating them here would give two sources that can disagree.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

API = "https://en.wikipedia.org/w/api.php"

# Wikimedia's User-Agent policy requires a client name, a version, and a way to
# make contact. A UA without contact information is rejected with 403 on every
# request — not rate-limited, refused outright from the first call.
# https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy
USER_AGENT = (
    "manhwa-rag/0.1 (https://github.com/manhwa-rag; practice project) python-httpx"
)

ARTICLES = [
    # Formats and traditions
    "Manhwa",
    "Manga",
    "Manhua",
    "Webtoon",
    "Web manga",
    "Light novel",
    "Comics",
    # Korean industry
    "Naver Webtoon",
    "Kakao Entertainment",
    "Lezhin Comics",
    "Line Webtoon",
    "Tapas Media",
    "Ridibooks",
    # Japanese industry
    "Shueisha",
    "Kodansha",
    "Shogakukan",
    "Kadokawa Corporation",
    "Weekly Shōnen Jump",
    "Weekly Shōnen Magazine",
    "Big Comic Spirits",
    "Manga Plus",
    "Shōnen Jump+",
    # Demographics and genres
    "Shōnen manga",
    "Shōjo manga",
    "Seinen manga",
    "Josei manga",
    "Isekai",
    "Yaoi",
    "Yuri (genre)",
    # Business, distribution, legal
    "Scanlation",
    "Digital comics",
    "Comixology",
    "Manga industry",
    "Anime industry",
    "Media franchise",
    "Copyright infringement",
    "Localization (publishing)",
    "Serial (literature)",
    # Adaptation pipeline
    "Anime",
    "Original video animation",
    "Live-action adaptation",
    # Notable market context
    "Demon Slayer: Kimetsu no Yaiba",
    "Solo Leveling",
    "One Piece",
    "Tower of God",
    "The God of High School",
    "Attack on Titan",
    "Berserk (manga)",
    "Naruto",
    "Webtoon (platform)",
    "Comic book",
]


async def _fetch_extract(client: httpx.AsyncClient, title: str) -> dict | None:
    params = {
        "action": "query",
        "format": "json",
        "prop": "extracts|info",
        "inprop": "url",
        "explaintext": "1",
        "exsectionformat": "wiki",  # keeps "== Section ==" markers
        "redirects": "1",
        "titles": title,
    }
    resp = await client.get(API, params=params, timeout=30.0)
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages", {})
    for page_id, page in pages.items():
        if page_id == "-1" or "extract" not in page:
            return None
        extract = page["extract"].strip()
        if len(extract.split()) < 150:
            return None
        return {
            "title": page["title"],
            "url": page.get("fullurl"),
            "extract": extract,
        }
    return None


async def fetch_articles(cache_dir: Path) -> list[dict]:
    cache = cache_dir / "wikipedia.json"
    if cache.exists():
        docs = json.loads(cache.read_text(encoding="utf-8"))
        print(f"  wikipedia: {len(docs)} from cache")
        return docs

    cache_dir.mkdir(parents=True, exist_ok=True)
    docs: list[dict] = []
    failures = 0
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        for i, title in enumerate(ARTICLES, 1):
            try:
                doc = await _fetch_extract(client, title)
            except Exception as exc:  # noqa: BLE001 - one bad article must not
                failures += 1                      # abort the whole corpus fetch
                print(f"    [{i}/{len(ARTICLES)}] {title}: FAILED ({exc})")
                continue
            if doc is None:
                print(f"    [{i}/{len(ARTICLES)}] {title}: skipped (missing/too short)")
                continue
            docs.append(doc)
            print(
                f"    [{i}/{len(ARTICLES)}] {doc['title']}: "
                f"{len(doc['extract'].split())} words"
            )
            await asyncio.sleep(0.2)

    # Tolerating individual failures is right; silently accepting a total
    # failure is not. Without this, a blanket 403 caches an empty list and every
    # later run "succeeds" with a corpus of zero articles.
    if not docs:
        raise RuntimeError(
            f"Wikipedia returned no usable articles ({failures} failures). "
            "Nothing cached. Check the User-Agent policy and connectivity."
        )
    if failures > len(ARTICLES) // 2:
        print(f"  WARNING: {failures}/{len(ARTICLES)} articles failed to fetch")

    cache.write_text(json.dumps(docs, ensure_ascii=False), encoding="utf-8")
    return docs
