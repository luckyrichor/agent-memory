from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from agent_memory.api.schemas import ScopeRequest


class ToolResultPayloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=1, max_length=255)
    exit_code: int
    summary: str = Field(min_length=1, max_length=60_000)
    error_code: str | None = Field(default=None, max_length=255)


class EventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    idempotency_key: str = Field(min_length=1, max_length=255)
    session_id: str = Field(min_length=1, max_length=255)
    sequence_number: int = Field(ge=1)
    event_type: Literal["tool.result"]
    agent_id: str = Field(min_length=1, max_length=255)
    occurred_at: datetime
    scope: ScopeRequest
    payload: ToolResultPayloadRequest


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
