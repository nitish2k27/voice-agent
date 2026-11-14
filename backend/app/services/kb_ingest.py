# Knowledge base ingest: read a document -> cut it into chunks -> embed -> save in kb_chunks.
# This is the only place where document embeddings are made (company onboarding / document upload).
#
# v1 scope: clean markdown + plain typed PDF/DOCX/TXT. No OCR, no translation (that is v2).
#
# CLI, from backend/:
#     python -m app.services.kb_ingest ../docs/knowledge_base.md

import argparse
import io
import logging
import re
from pathlib import Path

from app.core.config import settings
from app.db.session import get_sync_conn
from app.repos import kb_repo
from app.services import embedder

log = logging.getLogger("kb_ingest")

MAX_TOKENS = 400      # split sections bigger than this
TARGET_TOKENS = 300   # ...into pieces of about this size


def rough_tokens(text):
    # good enough for English: about 1.3 tokens per word
    return int(len(text.split()) * 1.3)


# ---------------------------------------------------------------- reading files
def read_file(file_name, data):
    """bytes of a .md/.txt/.pdf/.docx file -> markdown-ish text"""
    ext = Path(file_name).suffix.lower()
    if ext in (".md", ".txt"):
        return data.decode("utf-8")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    if ext == ".docx":
        import docx
        lines = []
        for p in docx.Document(io.BytesIO(data)).paragraphs:
            style = p.style.name if p.style is not None else ""
            if style.startswith("Heading") and style[-1].isdigit():
                lines.append("#" * int(style[-1]) + " " + p.text)   # Word headings -> markdown headings
            else:
                lines.append(p.text)
        return "\n".join(lines)
    raise ValueError(f"unsupported file type: {ext} (use .md, .txt, .pdf or .docx)")


# ---------------------------------------------------------------- chunking
def split_into_sections(text):
    """Cut markdown at headings. Returns [(heading path, body text)]"""
    sections = []
    headings = []        # current heading at each level, e.g. ["Amrith Sagar KB", "FAQs", "Booking"]
    body_lines = []

    def save_section():
        body = "\n".join(body_lines).strip()
        if body:
            path = " > ".join(headings[1:]) or (headings[0] if headings else "")   # skip the document title
            sections.append((path, body))
        body_lines.clear()

    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", line)
        if m:
            save_section()
            level = len(m.group(1))
            headings = headings[: level - 1] + [m.group(2).strip()]
        else:
            body_lines.append(line)
    save_section()
    return sections


def split_big_table(table):
    """A markdown table bigger than TARGET_TOKENS -> several smaller tables, each with the header rows."""
    lines = table.splitlines()
    header, rows = lines[:2], lines[2:]          # header line + |---| line
    pieces, current = [], []
    for row in rows:
        if current and rough_tokens("\n".join(header + current + [row])) > TARGET_TOKENS:
            pieces.append("\n".join(header + current))
            current = []
        current.append(row)
    if current:
        pieces.append("\n".join(header + current))
    return pieces


def split_paragraphs(body):
    # a paragraph = lines between blank lines (a markdown table stays together, unless it is too big)
    paragraphs = []
    for p in re.split(r"\n\s*\n", body):
        p = p.strip()
        if not p:
            continue
        if p.startswith("|") and rough_tokens(p) > TARGET_TOKENS:
            paragraphs.extend(split_big_table(p))
        else:
            paragraphs.append(p)
    return paragraphs


def make_chunks(text):
    """Returns [{"section": path, "content": "path:\\nbody"}]"""
    chunks = []

    def add(path, body):
        if len(body.split()) >= 5:          # skip tiny leftovers
            chunks.append({"section": path, "content": f"{path}:\n{body}" if path else body})

    for path, body in split_into_sections(text):
        paragraphs = split_paragraphs(body)

        # FAQ sections: one chunk per question ("**Question?** answer")
        if "FAQ" in path.upper():
            for p in paragraphs:
                add(path, p)
            continue

        # normal section: keep whole if small, otherwise group paragraphs into ~300-token pieces
        if rough_tokens(body) <= MAX_TOKENS:
            add(path, body)
            continue
        piece = []
        for p in paragraphs:
            if piece and rough_tokens("\n\n".join(piece + [p])) > TARGET_TOKENS:
                add(path, "\n\n".join(piece))
                piece = []
            piece.append(p)
        if piece:
            add(path, "\n\n".join(piece))
    return chunks


# ---------------------------------------------------------------- saving
def ingest_into_document(document_id, tenant_id, file_name, text):
    """Chunk + embed + save for an existing kb_documents row."""
    try:
        chunks = make_chunks(text)
        if not chunks:
            raise ValueError("no text found in the document")
        vectors = embedder.embed_documents(c["content"] for c in chunks)
        with get_sync_conn() as conn:
            kb_repo.insert_chunks(conn, tenant_id, document_id, file_name, chunks, vectors)
            kb_repo.set_status(conn, document_id, "indexed", chunk_count=len(chunks))
            kb_repo.mark_tenant_ready(conn, tenant_id)
        log.info("indexed %s: %d chunks", file_name, len(chunks))
        return len(chunks)
    except Exception as e:
        with get_sync_conn() as conn:
            kb_repo.set_status(conn, document_id, "failed", error=str(e)[:500])
        raise


def ingest_file(path, tenant_id=None, source="seed"):
    """Used by the CLI: replaces any older document with the same file name."""
    tenant_id = tenant_id or settings.TENANT_ID
    path = Path(path)
    text = read_file(path.name, path.read_bytes())
    with get_sync_conn() as conn:
        kb_repo.delete_documents_named(conn, tenant_id, path.name)
        document_id = kb_repo.insert_document(conn, tenant_id, path.name, source)
    return document_id, ingest_into_document(document_id, tenant_id, path.name, text)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ingest a document into the knowledge base")
    parser.add_argument("path")
    parser.add_argument("--tenant", default=None)
    parser.add_argument("--dry-run", action="store_true", help="only print the chunks, don't embed or save")
    args = parser.parse_args()

    if args.dry_run:
        for i, c in enumerate(make_chunks(Path(args.path).read_text(encoding="utf-8")), 1):
            print(f"--- chunk {i} ({rough_tokens(c['content'])} tokens) | {c['section']}")
            print(c["content"][:200].replace("\n", " "), "...\n")
    else:
        doc_id, count = ingest_file(args.path, args.tenant)
        print(f"Done: document {doc_id}, {count} chunks")
