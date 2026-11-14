# Celery app. Milestone 2 only needs the ingest task; the call queue, beat schedule
# and post-call tasks are added in Milestones 6 and 7.
#
# From backend/:  celery -A worker.celery_app worker -Q postcall -c 1 -n postcall@%h --pool=solo

from celery import Celery

from app.core.config import settings

celery_app = Celery("voice_agent", broker=settings.REDIS_URL, backend=settings.REDIS_URL, include=["worker.tasks"])

celery_app.conf.update(
    timezone=settings.TIMEZONE,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={"worker.tasks.ingest_document": {"queue": "postcall"}},
)
