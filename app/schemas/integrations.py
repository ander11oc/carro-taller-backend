from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IntegrationWebhookRequest(BaseModel):
    records: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "webhook"


class IntegrationEventOut(BaseModel):
    id: int
    run_id: int | None = None
    system: str
    event_type: str
    entity_type: str = ""
    entity_id: int | None = None
    status: str
    message: str
    payload: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class IntegrationRunOut(BaseModel):
    id: int
    system: str
    source: str
    status: str
    total_records: int
    processed_records: int
    failed_records: int
    errors: list[Any] | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    class Config:
        from_attributes = True
