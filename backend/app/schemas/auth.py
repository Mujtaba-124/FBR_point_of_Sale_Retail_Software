import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import AccessCategory, User

Workspace = Literal["super_admin", "company"]


def workspace_for(category: AccessCategory) -> Workspace:
    return "super_admin" if category == AccessCategory.SUPER_ADMIN else "company"


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    # Upper bound protects the password hasher from oversized input.
    password: str = Field(min_length=1, max_length=1024)


class CurrentUser(BaseModel):
    """The only user fields ever sent to the client."""

    id: uuid.UUID
    email: str
    full_name: str
    access_category: AccessCategory
    workspace: Workspace

    @classmethod
    def from_user(cls, user: User) -> "CurrentUser":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            access_category=user.access_category,
            workspace=workspace_for(user.access_category),
        )


class CompanyAccessOut(BaseModel):
    """Whether Company Workspace operations are currently allowed (no dates exposed)."""

    allowed: bool
    code: str | None


class MeResponse(CurrentUser):
    # null for the Super Admin, whose access never depends on the subscription.
    company_access: CompanyAccessOut | None = None
    # Effective Company capabilities (empty for the Super Admin). Display only:
    # the backend re-evaluates them on every request.
    permissions: list[str] = []


class LoginResponse(BaseModel):
    user: CurrentUser


class WorkspaceResponse(BaseModel):
    workspace: Workspace
    user: CurrentUser
    permissions: list[str] = []
    # Company Workspace: whether this account uses the All Shops / shop selector.
    shop_context_enabled: bool = False


class SetupLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=200)


class CompleteSetupRequest(SetupLinkRequest):
    password: str = Field(min_length=1, max_length=1024)


class SetupLinkOut(BaseModel):
    full_name: str
    email: str  # masked
    expires_at: datetime
