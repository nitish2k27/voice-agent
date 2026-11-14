"""Start the API with an event loop that async psycopg can use on Windows.

psycopg's async mode can't run on Windows' ProactorEventLoop. uvicorn picks Proactor on Windows
*without* --reload and SelectorEventLoop *with* --reload, so:

    python -m app             # Selector loop, no reload (works on Windows)
    python -m app --reload    # uvicorn --reload (Selector in the reload subprocess)
    uvicorn app.main:app --reload --port 8000   # also fine
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the FastAPI app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    if args.reload:
        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=True)
        return

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=args.host, port=args.port))
    asyncio.run(server.serve())


if __name__ == "__main__":
    main()
