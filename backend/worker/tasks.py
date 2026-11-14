# Celery tasks. More tasks (dial_call, postcall, ...) come in later milestones.

import httpx

from app.core.config import settings
from app.db.session import get_sync_conn
from app.repos import kb_repo
from app.services import kb_ingest
from worker.celery_app import celery_app


def download_from_storage(path):
    """Download a file from the private kb-docs bucket with the service key."""
    key = settings.SUPABASE_SERVICE_KEY
    headers = {"apikey": key}
    if key.count(".") == 2:  # old JWT-style keys also need the Authorization header
        headers["Authorization"] = f"Bearer {key}"
    r = httpx.get(f"{settings.SUPABASE_URL}/storage/v1/object/{settings.KB_BUCKET}/{path}", headers=headers, timeout=60)
    r.raise_for_status()
    return r.content


@celery_app.task(name="worker.tasks.ingest_document")
def ingest_document(document_id, text=None):
    """Chunk + embed one kb_documents row. Pasted onboarding text comes in `text`; uploads are read from Storage."""
    with get_sync_conn() as conn:
        doc = kb_repo.get_document(conn, document_id)
    if doc is None:
        return {"ok": False, "error": "document not found"}
    if text is None:
        text = kb_ingest.read_file(doc["file_name"], download_from_storage(doc["storage_path"]))
    count = kb_ingest.ingest_into_document(document_id, doc["tenant_id"], doc["file_name"], text)
    return {"ok": True, "chunks": count}
