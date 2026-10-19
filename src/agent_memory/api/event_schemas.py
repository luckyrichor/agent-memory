from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_memory.api.schemas import ScopeRequest


class ToolResultPayloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=255)
    exit_code: int
    summary: str = Field(min_length=1, max_length=60_000)
    error_code: str | None = Field(default=None, max_length=255)


class ConversationPayloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    # Bounded single-message text, using the extractor's existing untrusted summary input.
    summary: str = Field(min_length=1, max_length=4000)


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    session_id: str = Field(min_length=1, max_length=255)
    sequence_number: int = Field(ge=1)
    event_type: Literal["tool.result", "conversation.message"]
    agent_id: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    scope: ScopeRequest
    payload: ToolResultPayloadRequest | ConversationPayloadRequest

    @model_validator(mode="after")
    def payload_matches_event_type(self) -> Self:
        if (self.event_type == "tool.result") != isinstance(self.payload, ToolResultPayloadRequest):
            raise ValueError("payload does not match event type")
        return self


class EventBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    events: list[EventRequest] = Field(min_length=1, max_length=100)


class EventIngestionItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    idempotency_key: str
    disposition: Literal["accepted", "duplicate"]


class EventBatchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[EventIngestionItemResponse]
