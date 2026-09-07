import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.schemas.domain import WorkspaceResponse


USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,49}$")
PHONE_ALLOWED_PATTERN = re.compile(r"^[+()\-\s0-9]+$")


def validate_phone(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    digits = "".join(character for character in cleaned if character.isdigit())
    if not PHONE_ALLOWED_PATTERN.fullmatch(cleaned) or not 7 <= len(digits) <= 15:
        raise ValueError("Enter a valid phone number containing 7 to 15 digits")
    return cleaned


class SignUpRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    phone_number: str = Field(min_length=7, max_length=32)
    password: str = Field(min_length=8, max_length=128)
    password_confirmation: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        cleaned = value.strip()
        if not USERNAME_PATTERN.fullmatch(cleaned):
            raise ValueError(
                "Username must start with a letter or number and use only letters, numbers, underscores, or hyphens"
            )
        return cleaned

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        return validate_phone(value)

    @model_validator(mode="after")
    def passwords_match(self) -> "SignUpRequest":
        if self.password != self.password_confirmation:
            raise ValueError("Passwords do not match")
        return self


class SignInRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class ProfileUpdateRequest(BaseModel):
    phone_number: str = Field(min_length=7, max_length=32)

    @field_validator("phone_number")
    @classmethod
    def validate_phone_number(cls, value: str) -> str:
        return validate_phone(value)


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    username: str
    email: EmailStr
    phone_number: str
    created_at: datetime


class UserLookup(BaseModel):
    id: str
    username: str
    email: EmailStr


class AuthResponse(BaseModel):
    user: UserPublic


class AuthSessionResponse(BaseModel):
    authenticated: bool
    user: UserPublic | None = None


class ConversationMessageResponse(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    result_reference: str | None = None
    created_at: datetime


class ConversationShareResponse(BaseModel):
    recipient: UserLookup
    permission: Literal["VIEW"]
    created_at: datetime


class ConversationSummary(BaseModel):
    id: str
    workspace_id: str
    title: str
    preview: str
    owner: UserLookup
    permission: Literal["OWNER", "VIEW"]
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationSummary):
    messages: list[ConversationMessageResponse]
    shares: list[ConversationShareResponse]
    workspace: WorkspaceResponse


class ShareConversationRequest(BaseModel):
    recipient_id: str = Field(min_length=1)
    permission: Literal["VIEW"] = "VIEW"


class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def clean_title(cls, value: str) -> str:
        return " ".join(value.split())
