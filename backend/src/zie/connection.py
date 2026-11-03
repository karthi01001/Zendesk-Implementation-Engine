"""Connection check: who are we connected as, and can that identity read configuration?"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from zie.zendesk.client import ZendeskClient


class ConnectionInfo(BaseModel):
    subdomain: str
    auth_type: Literal["oauth", "api_token"]
    user_name: str
    user_email: str | None = None
    role: str
    is_admin: bool
    granted_scope: str | None = None
    warnings: list[str] = []


async def check_connection(client: ZendeskClient) -> ConnectionInfo:
    """Authenticate, identify the acting user and flag anything that will block reading config."""
    me = await client.me()
    role = str(me.get("role") or "unknown")
    is_admin = role == "admin"
    warnings: list[str] = []
    if not is_admin:
        warnings.append(
            f"Connected as a user with role '{role}'. Reading every configuration area "
            "needs an admin; create the OAuth client from a service-account admin."
        )
    if client.credentials.auth_type == "api_token":
        warnings.append(
            "API tokens stop working on 30 Apr 2027. Switch this connection to an OAuth client."
        )
    return ConnectionInfo(
        subdomain=client.credentials.subdomain,
        auth_type=client.credentials.auth_type,
        user_name=str(me.get("name") or ""),
        user_email=me.get("email"),
        role=role,
        is_admin=is_admin,
        granted_scope=client.granted_scope,
        warnings=warnings,
    )
