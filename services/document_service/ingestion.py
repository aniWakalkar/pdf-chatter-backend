import logging
import uuid

import openai
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from services.document_service.chunker import chunk_pages
from services.document_service.pdf_parser import PdfExtractionError, extract_pages
from shared.ai import AIConfigurationError, embed_texts
from shared.config import get_settings
from shared.database import SessionLocal
from shared.models import Document, DocumentChunk, DocumentFile, DocumentStatus

logger = logging.getLogger("document-service.ingestion")

MAX_CHUNKS_PER_DOCUMENT = 2000


def _set_status(db: Session, document: Document, status: str) -> None:
    document.status = status
    document.error_message = None
    db.commit()


def _fail(db: Session, document_id: uuid.UUID, message: str) -> None:
    db.rollback()
    document = db.get(Document, document_id)
    if document is None:
        return
    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    document.status = DocumentStatus.FAILED
    document.chunk_count = 0
    document.error_message = message
    db.commit()


def process_document(document_id: uuid.UUID) -> None:
    settings = get_settings()
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if document is None:
            return
        try:
            _set_status(db, document, DocumentStatus.EXTRACTING)
            content = db.scalar(select(DocumentFile.content).where(DocumentFile.document_id == document.id))
            if content is None:
                raise PdfExtractionError("The original file is missing. Please delete and upload it again.")
            page_count, pages = extract_pages(content)
            document.page_count = page_count
            if not pages:
                raise PdfExtractionError(
                    "No selectable text was found. Scanned PDFs need OCR, which is not supported yet."
                )

            chunks = chunk_pages(pages, settings.chunk_size_chars, settings.chunk_overlap_chars)
            if not chunks:
                raise PdfExtractionError("The document does not contain enough text to index.")
            if len(chunks) > MAX_CHUNKS_PER_DOCUMENT:
                raise PdfExtractionError("The document is too large to index.")

            _set_status(db, document, DocumentStatus.INDEXING)
            vectors = embed_texts([chunk.content for chunk in chunks])

            db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document.id))
            db.add_all(
                DocumentChunk(
                    document_id=document.id,
                    user_id=document.user_id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    content=chunk.content,
                    embedding=vector,
                )
                for chunk, vector in zip(chunks, vectors, strict=True)
            )
            document.chunk_count = len(chunks)
            document.status = DocumentStatus.READY
            document.error_message = None
            db.commit()
            logger.info("Indexed document %s with %s chunks", document_id, len(chunks))
        except PdfExtractionError as exc:
            _fail(db, document_id, str(exc))
        except AIConfigurationError:
            _fail(db, document_id, "The AI service is not configured. Add AI_API_KEY and retry.")
        except openai.RateLimitError:
            logger.warning("Embedding quota exhausted for document %s", document_id)
            _fail(db, document_id, "The AI usage limit has been reached. Please retry in a few minutes.")
        except openai.OpenAIError:
            logger.exception("Embedding failed for document %s", document_id)
            _fail(db, document_id, "The embedding service failed. Please retry.")
        except Exception:
            logger.exception("Processing failed for document %s", document_id)
            _fail(db, document_id, "Processing failed. Please retry.")


def fail_interrupted_documents() -> None:
    with SessionLocal() as db:
        db.execute(
            update(Document)
            .where(Document.status.in_(DocumentStatus.PROCESSING))
            .values(status=DocumentStatus.FAILED, error_message="Processing was interrupted. Please retry.")
        )
        db.commit()
