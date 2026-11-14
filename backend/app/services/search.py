# Knowledge base search used by the agent's search_knowledge_base tool.
# hybrid = vector (bge-small) + keyword (Postgres full-text), combined in SQL hybrid_search().
# keyword = full-text only (fallback, and for the keyword-vs-hybrid comparison in evals).

from app.core.config import settings
from app.db.session import get_sync_conn
from app.repos import kb_repo
from app.services import embedder


def search(tenant_id, query, k=5, mode=None):
    mode = mode or settings.SEARCH_MODE
    vector = embedder.embed_query(query) if mode == "hybrid" else None
    with get_sync_conn() as conn:
        return kb_repo.hybrid_search(conn, tenant_id, query, vector, k)


def results_for_llm(rows):
    """Compact text for the LLM: one block per chunk."""
    if not rows:
        return "No matching information found in the knowledge base. Say our team will confirm, or offer a callback."
    return "\n\n".join(r["content"] for r in rows)
