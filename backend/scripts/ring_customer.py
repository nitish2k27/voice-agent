# Make a test customer's call page ring, to try the incoming-call page before Milestone 6's campaigns exist.
#
# From backend/ (venv active), with the agent running (python -m agent.agent dev) and the frontend running:
#     python scripts/ring_customer.py              -> uses C001 from sample_customers.csv, prints the page link
#     python scripts/ring_customer.py --customer C002 --call-type post_event_feedback
#
# Open the printed link first, then run the script again with --ring-now to make it ring.
# The page rings for 30 s; Accept to talk to Amrutha (the agent waits up to 45 s for you).

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.agent import sample_customer  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db.session import get_sync_conn  # noqa: E402
from app.repos import customers_repo  # noqa: E402
from app.services import campaign_types, livekit_service  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--customer", default="C001")
    parser.add_argument("--call-type", default=None, help="defaults to the customer's campaign in the CSV")
    parser.add_argument("--ring-now", action="store_true", help="make the page ring now")
    parser.add_argument("--frontend", default="http://localhost:5173")
    args = parser.parse_args()

    row = sample_customer(args.customer)
    call_type = args.call_type or row["campaign"]
    with get_sync_conn() as conn:
        # test customers get a "test-" phone so they never collide with real ones
        c = customers_repo.upsert_customer(conn, settings.TENANT_ID, row["customer_id"], row["name"],
                                           f"test-{row['phone']}", row["language"], is_test=True)
    print(f"\nCustomer page for {row['name']}:\n   {args.frontend}/c/{c['token']}\n")
    if not args.ring_now:
        print("Open that link, then run again with --ring-now to make it ring.")
        return

    room = f"out-test-{uuid.uuid4().hex[:8]}"
    await livekit_service.create_room(room, empty_timeout=120)
    with get_sync_conn() as conn:
        job_id = customers_repo.create_ringing_job(conn, settings.TENANT_ID, c["id"], row, room, is_test=True)
    await livekit_service.dispatch_agent(room, {
        "tenant_id": settings.TENANT_ID, "direction": "outbound", "call_type": call_type,
        "job_id": job_id, "customer_id": c["id"], "customer": row,
        "questions": campaign_types.questions(call_type), "is_test": True,
    })
    print(f"Ringing now ({call_type}, room {room}). You have {settings.RING_TIMEOUT_SECONDS} s to press Accept.")


if __name__ == "__main__":
    asyncio.run(main())
