# REPO: knowledge base documents and chunks. Only SQL here.


def delete_documents_named(conn, tenant_id, file_name):
    """Re-ingesting a file replaces it (chunks go too: on delete cascade)."""
    conn.execute("delete from kb_documents where tenant_id = %s and file_name = %s", (tenant_id, file_name))


def insert_document(conn, tenant_id, file_name, source, storage_path=None):
    row = conn.execute(
        """insert into kb_documents (tenant_id, file_name, source, storage_path, status)
           values (%s, %s, %s, %s, 'processing') returning id::text""",
        (tenant_id, file_name, source, storage_path),
    ).fetchone()
    return row["id"]


def get_document(conn, document_id):
    return conn.execute(
        "select id::text, tenant_id::text, file_name, source, storage_path from kb_documents where id = %s",
        (document_id,),
    ).fetchone()


def insert_chunks(conn, tenant_id, document_id, doc_name, chunks, vectors):
    """chunks = [{"section": ..., "content": ...}], vectors = pgvector strings in the same order"""
    with conn.cursor() as cur:
        cur.executemany(
            """insert into kb_chunks (tenant_id, document_id, doc_name, section, content, embedding)
               values (%s, %s, %s, %s, %s, %s::vector)""",
            [(tenant_id, document_id, doc_name, c["section"], c["content"], v) for c, v in zip(chunks, vectors)],
        )


def set_status(conn, document_id, status, chunk_count=0, error=None):
    conn.execute(
        "update kb_documents set status = %s, chunk_count = %s, error = %s where id = %s",
        (status, chunk_count, error, document_id),
    )


def mark_tenant_ready(conn, tenant_id):
    conn.execute("update tenants set onboarding_status = 'ready' where id = %s", (tenant_id,))


def hybrid_search(conn, tenant_id, query_text, query_vector, k):
    """query_vector=None -> keyword-only search (see supabase/schema.sql)."""
    return conn.execute(
        "select id, section, content, doc_name, score from hybrid_search(%s, %s, %s::vector, %s)",
        (tenant_id, query_text, query_vector, k),
    ).fetchall()
