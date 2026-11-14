# Small English embedding model (bge-small-en-v1.5, 384 numbers per text) via fastembed (ONNX, no torch).
# The same model must embed the document chunks AND the search queries.

from functools import lru_cache

from app.core.config import REPO_ROOT, settings

# BGE models search better when short queries get this instruction in front (documents don't get it).
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_model = None


def get_model():
    """Load the model once per process (about 1 second, ~130 MB download the first time)."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(settings.EMBED_MODEL, cache_dir=str(REPO_ROOT / ".cache" / "fastembed"))
    return _model


def to_pgvector(vector):
    """Postgres pgvector wants text like '[0.1,0.2,...]'."""
    return "[" + ",".join(f"{x:.6f}" for x in vector) + "]"


def embed_documents(texts):
    """List of chunk texts -> list of pgvector strings."""
    return [to_pgvector(v) for v in get_model().embed(list(texts), batch_size=32)]


@lru_cache(maxsize=512)
def embed_query(query):
    """One search query -> pgvector string. Cached, so repeated questions cost nothing."""
    vector = next(iter(get_model().embed([QUERY_PREFIX + query])))
    return to_pgvector(vector)
