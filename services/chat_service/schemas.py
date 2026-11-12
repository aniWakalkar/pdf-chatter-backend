import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _dedupe(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(ids))


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("document_ids")
    @classmethod
    def unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return _dedupe(value)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    document_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    document_ids: list[uuid.UUID]
    created_at: datetime
    updated_at: datetime


class CitationOut(BaseModel):
    document_id: uuid.UUID | None
    chunk_id: uuid.UUID | None
    filename: str
    page_number: int
    snippet: str
    relevance_score: float


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    created_at: datetime
    citations: list[CitationOut] = []


class ChatRequest(BaseModel):
    conversation_id: uuid.UUID | None = None
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
    question: str = Field(min_length=1, max_length=2000)

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question is required")
        return value

    @field_validator("document_ids")
    @classmethod
    def unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return _dedupe(value)


class ChatResponse(BaseModel):
    conversation: ConversationOut
    user_message: MessageOut
    assistant_message: MessageOut
