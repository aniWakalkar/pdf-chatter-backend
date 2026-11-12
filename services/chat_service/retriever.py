import uuid
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from shared.models import Document, DocumentChunk, DocumentStatus


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    filename: str
    page_number: int
    content: str
    score: float


def retrieve_chunks(
    db: Session,
    user_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    query_vector: list[float],
    top_k: int,
    min_score: float,
) -> list[RetrievedChunk]:
    db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
    distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.page_number,
            DocumentChunk.content,
            Document.filename,
            distance,
        )
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(
            DocumentChunk.user_id == user_id,
            Document.user_id == user_id,
            Document.status == DocumentStatus.READY,
            DocumentChunk.document_id.in_(document_ids),
        )
        .order_by(distance)
        .limit(top_k)
    )
    results = []
    for row in db.execute(stmt):
        score = 1.0 - float(row.distance)
        if score >= min_score:
            results.append(
                RetrievedChunk(
                    chunk_id=row.id,
                    document_id=row.document_id,
                    filename=row.filename,
                    page_number=row.page_number,
                    content=row.content,
                    score=round(score, 4),
                )
            )
    return results
