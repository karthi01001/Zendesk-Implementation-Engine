"""Reader for Zendesk groups: the first configuration area, used to prove the end-to-end path."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from zie.zendesk.client import ZendeskClient


class Group(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str
    description: str | None = None
    default: bool = False
    deleted: bool = False
    is_public: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


async def read_groups(client: ZendeskClient) -> list[Group]:
    """Return every group in the instance, following pagination."""
    return [
        Group.model_validate(item) async for item in client.paginate("/api/v2/groups", "groups")
    ]
