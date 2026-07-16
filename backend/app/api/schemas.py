from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[\w.@+-]+$")
    password: SecretStr = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=256)


class IngestRequest(BaseModel):
    categories: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    max_results: int = Field(default=10, ge=1, le=50)


class SourceIngestRequest(IngestRequest):
    venue: str = Field(default="", max_length=80)
    year: int = Field(default_factory=lambda: date.today().year, ge=2000, le=2100)
    proceedings_url: str = Field(default="", max_length=2_048)


class FavoriteRequest(BaseModel):
    paper_id: int
    favorite: bool = True


class UploadVisibilityRequest(BaseModel):
    visibility: Literal["private", "public"]


class NoteRequest(BaseModel):
    paper_id: int
    note: str = Field(min_length=1, max_length=20_000)
    comment: str = Field(default="", max_length=2_000)


class SubscriptionRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=120)


class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    paper_ids: list[int] = Field(default_factory=list)
    mode: Literal["agentic", "classic"] = "agentic"

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("question must not be blank")
        return cleaned

    @field_validator("paper_ids")
    @classmethod
    def validate_paper_ids(cls, value: list[int]) -> list[int]:
        if len(value) > 20 or any(item <= 0 for item in value):
            raise ValueError("paper_ids must contain at most 20 positive IDs")
        return list(dict.fromkeys(value))


class FolderRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    parent_id: int | None = None
    description: str = Field(default="", max_length=300)


class MoveLibraryItemRequest(BaseModel):
    folder_id: int


class ThreadCreateRequest(BaseModel):
    title: str = Field(default="新对话", max_length=100)


class ThreadHeadRequest(BaseModel):
    head_id: str | None = None


class ChatUserMessage(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    parent_id: str | None = None
    source_message_id: str | None = None
    content: str = Field(min_length=1, max_length=20_000)


class ChatRunRequest(BaseModel):
    thread_id: str
    operation: str = Field(default="append", pattern="^(append|edit|regenerate)$")
    user_message: ChatUserMessage | None = None
    parent_message_id: str | None = None
    source_message_id: str | None = None
    assistant_message_id: str = Field(min_length=1, max_length=100)
    message_token_limit: int = Field(default=12000, ge=0, le=100000)


class ResearchRunCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=20_000)
    thread_id: str | None = Field(default=None, max_length=100)

    @field_validator("title", "goal")
    @classmethod
    def validate_research_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank")
        return cleaned


class ResearchDecisionResolveRequest(BaseModel):
    option_id: str = Field(min_length=1, max_length=100)
