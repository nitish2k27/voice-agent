# Try the knowledge base search from the terminal.
#
# From backend/:
#     python scripts/test_search.py "jain food price"
#     python scripts/test_search.py "jain food price" --mode keyword
#     python scripts/test_search.py --checks          (runs the Milestone 2 acceptance queries)

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import settings  # noqa: E402
from app.services import embedder, search  # noqa: E402

# query -> a word that must appear in one of the top 3 results (the agent reads the top 5)
CHECKS = [
    ("jain food price", "jain"),
    ("food without onion garlic", "jain"),
    ("veg guests who don't eat onion garlic", "jain"),   # known miss: "veg" pulls the packages table up
    ("cancel charge refund", "cancel"),
    ("can I pay advance on this call", "pay"),
    ("alcohol at temple function", "alcohol"),
    ("minimum guests japanese", "japanese"),
]


def show(query, mode):
    start = time.time()
    rows = search.search(settings.TENANT_ID, query, k=5, mode=mode)
    ms = (time.time() - start) * 1000
    print(f"\n[{mode}] {query!r}  ({ms:.0f} ms)")
    for i, r in enumerate(rows, 1):
        print(f"  {i}. {r['score']:.4f}  {r['section']}  |  {r['content'][len(r['section']) + 2:][:90]!r}")
    return rows, ms


def run_checks():
    search.search(settings.TENANT_ID, "warm up")   # first call loads the model + opens the DB pool; not counted
    passed = 0
    for query, must in CHECKS:
        rows, ms = show(query, "hybrid")
        top3 = " ".join(r["section"] + " " + r["content"] for r in rows[:3]).lower()
        ok = must in top3 and ms < 150
        passed += ok
        print(f"  -> {'PASS' if ok else 'FAIL'} (top 3 mention '{must}': {must in top3}, {ms:.0f} ms)")
    print(f"\n{passed}/{len(CHECKS)} checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?")
    parser.add_argument("--mode", default=settings.SEARCH_MODE, choices=["hybrid", "keyword"])
    parser.add_argument("--checks", action="store_true")
    args = parser.parse_args()
    if args.checks or not args.query:
        run_checks()
    else:
        show(args.query, args.mode)
