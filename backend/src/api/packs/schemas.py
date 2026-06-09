"""Pydantic boundary models for the packs API (TASK-038).

CONVENTIONS: validate at the API boundary; Pydantic schemas are the ONLY
thing that crosses the HTTP boundary. Internal service functions receive/return
plain Python types or domain objects.
"""

from pydantic import BaseModel, ConfigDict


class PackRead(BaseModel):
    """Catalog entry returned by GET /packs."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    title: str
    topic: str
    channels_count: int


class SubscribeResult(BaseModel):
    """Result of POST /packs/{slug}/subscribe."""

    model_config = ConfigDict(extra="forbid")

    created: int
    skipped: int


class UnsubscribeResult(BaseModel):
    """Result of DELETE /packs/{slug}/subscribe."""

    model_config = ConfigDict(extra="forbid")

    deleted: int
