"""Support-RAG application package.

On Windows, asyncio defaults to ProactorEventLoop, which psycopg's async mode
cannot use ("Psycopg cannot use the 'ProactorEventLoop' to run in async mode").
The selector policy has to be installed before any event loop is created, so it
happens here at package import — the one choke point every entry point (alembic,
uvicorn, the CLI scripts, pytest) passes through. This is an application, not a
library, so setting a global policy here is safe.

Python 3.14 deprecates `set_event_loop_policy` (removal in 3.16) in favour of
passing `loop_factory` to `asyncio.run`. That replacement does not cover the
servers and tools we do not call `asyncio.run` for ourselves — uvicorn, alembic,
pytest-asyncio — so the policy remains the only single-point fix today. The
warning is silenced here rather than at each call site; revisit when uvicorn and
pytest-asyncio expose loop-factory configuration.
"""

import asyncio
import sys
import warnings

if sys.platform == "win32":
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", category=DeprecationWarning, module="app"
        )
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
