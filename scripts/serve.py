"""Run the API server.

Why this exists instead of plain `uvicorn app.api:app`:

uvicorn hard-codes `ProactorEventLoop` on Windows (see
`uvicorn/loops/asyncio.py`), which psycopg's async mode refuses to run on. It
does that *after* import, so the policy set in `app/__init__.py` is overridden
and `/health` fails with an InterfaceError at request time rather than at boot.

The fix is to own the loop: `loop="none"` stops uvicorn installing its own, and
`asyncio.run(..., loop_factory=...)` supplies a selector loop on every platform.
On Linux uvicorn already chooses `SelectorEventLoop`, so the deployed container
is unaffected either way — this matters for local development on Windows.

    python -m scripts.serve --reload
"""

from __future__ import annotations

import argparse
import asyncio

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Support RAG API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    config = uvicorn.Config(
        "app.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        loop="none",  # we install the loop below
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)


if __name__ == "__main__":
    main()
