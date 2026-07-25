"""Manual retrieval probe.

    python -m scripts.search "Kimetsu no Yaiba"
    python -m scripts.search "completed romance manhwa under 100 chapters"
    python -m scripts.search --compare "Solo Leveling"
    python -m scripts.search --route industry "how does Naver Webtoon make money"

`--compare` shows trigram, vector and fused side by side, which is how you tell
*why* a query failed: a hit that trigram finds and vector misses is an alias
problem; the reverse is a paraphrase problem.
"""

from __future__ import annotations

import argparse
import asyncio

from app.db import session_scope
from app.retrieval.catalogue import CatalogueRetriever
from app.retrieval.documents import DocumentRetriever
from app.retrieval.filters import extract_filters, strip_filter_terms


def _show(title: str, hits: list) -> None:
    print(f"\n=== {title} ===")
    if not hits:
        print("  (no hits)")
        return
    for i, h in enumerate(hits, 1):
        meta = h.meta
        if h.kind == "series":
            facts = " · ".join(
                str(x)
                for x in [
                    meta.get("country"),
                    meta.get("status"),
                    f"{meta.get('chapters')} ch" if meta.get("chapters") else None,
                    meta.get("start_year"),
                ]
                if x
            )
            print(f"  {i}. [{h.score:.4f}] {h.title}   ({facts})")
            print(f"       genres: {', '.join(meta.get('genres') or [])}")
        else:
            preview = " ".join(h.text.split())[:110]
            print(f"  {i}. [{h.score:.4f}] {h.label}")
            print(f"       {preview}...")


async def main_async(query: str, route: str, k: int, compare: bool) -> None:
    filters = extract_filters(query)
    semantic = strip_filter_terms(query)

    async with session_scope() as session:
        catalogue = CatalogueRetriever(session)
        documents = DocumentRetriever(session)
        print(f'query    : "{query}"')
        print(f"filters  : {filters.describe() or '(none)'}")
        print(f"semantic : {semantic!r}")
        print(f"corpus   : {await catalogue.count()} series, {await documents.count()} chunks")

        if route == "industry":
            _show("industry: vector", await documents.by_vector(query, k=k))
            _show("industry: lexical", await documents.by_lexical(query, k=k))
            _show("industry: fused", await documents.search(query, k=k))
            return

        if compare:
            _show("trigram (titles)", await catalogue.by_title(query, filters, k=k))
            if semantic:
                _show("vector (cards)", await catalogue.by_vector(semantic, filters, k=k))
            _show("filters only", await catalogue.by_filters_only(filters, k=k))
            _show("combined", await catalogue.search(query, semantic, filters, k=k))
            return

        _show("catalogue", await catalogue.search(query, semantic, filters, k=k))


def main() -> None:
    parser = argparse.ArgumentParser(description="Probe retrieval.")
    parser.add_argument("query")
    parser.add_argument("--route", choices=["catalogue", "industry"], default="catalogue")
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--compare", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args.query, args.route, args.k, args.compare))


if __name__ == "__main__":
    main()
