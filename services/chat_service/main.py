import logging
import uuid
from datetime import UTC, datetime, timedelta

import openai
from fastapi import Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.chat_service.rag import generate_answer
from services.chat_service.retriever import retrieve_chunks
from services.chat_service.schemas import (
    ChatRequest,
    ChatResponse,
    CitationOut,
    ConversationCreate,
    ConversationOut,
    ConversationUpdate,
    MessageOut,
)
from shared.ai import AIConfigurationError, embed_query
from shared.app_factory import create_service_app
from shared.config import get_settings
from shared.database import get_db
from shared.models import Conversation, Document, DocumentStatus, Message, MessageSource
from shared.security import get_current_user_id

logger = logging.getLogger("chat-service")
app = create_service_app("chat-service")

SNIPPET_CHARS = 400


def _message_out(message: Message) -> MessageOut:
    return MessageOut(
        id=message.id,
        role=message.role,
        content=message.content,
        created_at=message.created_at,
        citations=[
            CitationOut(
                document_id=s.document_id,
                chunk_id=s.chunk_id,
                filename=s.filename,
                page_number=s.page_number,
                snippet=s.snippet,
                relevance_score=s.relevance_score,
            )
            for s in message.sources
        ],
    )


def _get_owned_conversation(db: Session, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(Conversation.id == conversation_id, Conversation.user_id == user_id)
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conversation


def _owned_documents(db: Session, user_id: uuid.UUID, document_ids: list[uuid.UUID]) -> list[Document]:
    if not document_ids:
        return []
    documents = db.scalars(
        select(Document).where(Document.user_id == user_id, Document.id.in_(document_ids))
    ).all()
    if len(documents) != len(set(document_ids)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more documents were not found")
    return list(documents)


@app.get("/api/conversations", response_model=list[ConversationOut])
def list_conversations(user_id: uuid.UUID = Depends(get_current_user_id), db: Session = Depends(get_db)):
    return db.scalars(
        select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.updated_at.desc())
    ).all()


@app.post("/api/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def create_conversation(
    payload: ConversationCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    _owned_documents(db, user_id, payload.document_ids)
    conversation = Conversation(
        user_id=user_id,
        title=(payload.title or "New conversation").strip() or "New conversation",
        document_ids=payload.document_ids,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    return _get_owned_conversation(db, conversation_id, user_id)


@app.patch("/api/conversations/{conversation_id}", response_model=ConversationOut)
def update_conversation(
    conversation_id: uuid.UUID,
    payload: ConversationUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    conversation = _get_owned_conversation(db, conversation_id, user_id)
    if payload.title is not None:
        conversation.title = payload.title.strip() or conversation.title
    if payload.document_ids is not None:
        ids = list(dict.fromkeys(payload.document_ids))
        _owned_documents(db, user_id, ids)
        conversation.document_ids = ids
    db.commit()
    db.refresh(conversation)
    return conversation


@app.delete("/api/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    db.delete(_get_owned_conversation(db, conversation_id, user_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def list_messages(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    conversation = _get_owned_conversation(db, conversation_id, user_id)
    messages = db.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at, Message.id)
    ).all()
    return [_message_out(m) for m in messages]


@app.post("/api/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, user_id: uuid.UUID = Depends(get_current_user_id), db: Session = Depends(get_db)):
    settings = get_settings()
    documents = _owned_documents(db, user_id, payload.document_ids)
    ready_ids = [d.id for d in documents if d.status == DocumentStatus.READY]
    if not ready_ids:
        raise HTTPException(status.HTTP_409_CONFLICT, "None of the selected documents are ready yet.")

    history: list[tuple[str, str]] = []
    if payload.conversation_id:
        conversation = _get_owned_conversation(db, payload.conversation_id, user_id)
        recent = db.scalars(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.desc())
            .limit(settings.history_messages)
        ).all()
        history = [(m.role, m.content) for m in reversed(recent)]
    else:
        conversation = Conversation(user_id=user_id, title=payload.question[:80])

    try:
        query_vector = embed_query(payload.question)
        chunks = retrieve_chunks(
            db, user_id, ready_ids, query_vector, settings.retrieval_top_k, settings.min_relevance_score
        )
        result = generate_answer(payload.question, chunks, history)
    except AIConfigurationError:
        db.rollback()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI service is not configured.")
    except openai.OpenAIError:
        db.rollback()
        logger.exception("AI request failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "The AI service failed to respond. Please try again.")

    asked_at = datetime.now(UTC)
    conversation.document_ids = payload.document_ids
    conversation.updated_at = asked_at
    if not payload.conversation_id:
        conversation.id = uuid.uuid4()
        conversation.created_at = asked_at
        db.add(conversation)

    user_message = Message(
        id=uuid.uuid4(), conversation_id=conversation.id, role="user", content=payload.question, created_at=asked_at
    )
    user_message.sources = []
    assistant_message = Message(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        role="assistant",
        content=result.answer,
        created_at=asked_at + timedelta(milliseconds=1),
    )
    db.add(user_message)
    assistant_message.sources = [
        MessageSource(
            chunk_id=s.chunk_id,
            document_id=s.document_id,
            filename=s.filename,
            page_number=s.page_number,
            snippet=s.content[:SNIPPET_CHARS],
            relevance_score=s.score,
        )
        for s in result.sources
    ]
    db.add(assistant_message)
    db.commit()

    return ChatResponse(
        conversation=ConversationOut.model_validate(conversation),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant_message),
    )
