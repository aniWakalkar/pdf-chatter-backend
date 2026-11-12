import re
import uuid
from contextlib import asynccontextmanager
from pathlib import PurePath
from urllib.parse import quote

from fastapi import BackgroundTasks, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.document_service.ingestion import fail_interrupted_documents, process_document
from services.document_service.schemas import DocumentOut
from shared.app_factory import create_service_app
from shared.config import get_settings
from shared.database import get_db
from shared.models import Document, DocumentFile, DocumentStatus
from shared.security import get_current_user_id

ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream", ""}


@asynccontextmanager
async def lifespan(_app):
    fail_interrupted_documents()
    yield


app = create_service_app("document-service", lifespan=lifespan)


def _safe_filename(name: str | None) -> str:
    base = PurePath((name or "").replace("\\", "/")).name
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return (base or "document.pdf")[:255]


def _get_owned_document(db: Session, document_id: uuid.UUID, user_id: uuid.UUID) -> Document:
    document = db.scalar(select(Document).where(Document.id == document_id, Document.user_id == user_id))
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


@app.post("/api/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    filename = _safe_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files are accepted.")
    if (file.content_type or "").lower() not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only PDF files are accepted.")

    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File is larger than {settings.max_upload_mb} MB."
        )
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is empty.")
    if not data.lstrip()[:5] == b"%PDF-":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "The file is not a valid PDF.")

    document = Document(
        id=uuid.uuid4(),
        user_id=user_id,
        filename=filename,
        size_bytes=len(data),
        status=DocumentStatus.UPLOADED,
    )
    document.file = DocumentFile(content=data)
    db.add(document)
    db.commit()
    db.refresh(document)
    background_tasks.add_task(process_document, document.id)
    return document


@app.get("/api/documents", response_model=list[DocumentOut])
def list_documents(user_id: uuid.UUID = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.scalars(
        select(Document).where(Document.user_id == user_id).order_by(Document.created_at.desc())
    ).all()


@app.get("/api/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return _get_owned_document(db, document_id, user_id)


@app.get("/api/documents/{document_id}/file")
def download_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    document = _get_owned_document(db, document_id, user_id)
    content = db.scalar(select(DocumentFile.content).where(DocumentFile.document_id == document.id))
    if content is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(document.filename)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/documents/{document_id}/retry", response_model=DocumentOut)
def retry_document(
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    document = _get_owned_document(db, document_id, user_id)
    if document.status != DocumentStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed documents can be retried.")
    document.status = DocumentStatus.UPLOADED
    document.error_message = None
    db.commit()
    db.refresh(document)
    background_tasks.add_task(process_document, document.id)
    return document


@app.delete("/api/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    db.delete(_get_owned_document(db, document_id, user_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
