import re

from pydantic import BaseModel, EmailStr, Field, field_validator


class CreateUserRequest(BaseModel):
    model_config = {"extra": "forbid"}

    email: EmailStr = Field(
        examples=["user@example.com"],
        description="Email address for the new user account.",
    )
    password: str = Field(
        min_length=8,
        max_length=128,
        examples=["StrongPass123!"],
        description=(
            "Must contain: uppercase letter, lowercase letter, "
            "a digit, and a special character."
        ),
    )

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        errors: list[str] = []
        if not re.search(r"[A-Z]", v):
            errors.append("at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            errors.append("at least one lowercase letter")
        if not re.search(r"\d", v):
            errors.append("at least one digit")
        if not re.search(r"[^A-Za-z0-9]", v):
            errors.append("at least one special character")
        if errors:
            raise ValueError("Password must contain " + ", ".join(errors))
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
