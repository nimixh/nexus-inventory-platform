from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.config import get_settings
from app.database import AdminSessionDep
from app.dependencies.auth import CurrentUser, RequireRole
from app.models.enums import UserRole
from app.redis import RedisDep
from app.schemas.auth import CreateUserRequest, TokenResponse
from app.schemas.user import UserResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    settings = get_settings()
    max_age = settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS * 86400
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=max_age,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE,
        httponly=True,
        secure=get_settings().COOKIE_SECURE,
        samesite="lax",
        path="/api/v1/auth",
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a viewer in the authenticated user's tenant",
    dependencies=[Depends(RequireRole(UserRole.OWNER, UserRole.ADMIN))],
)
async def create_tenant_user(
    body: CreateUserRequest,
    current_user: CurrentUser,
    db: AdminSessionDep,
) -> UserResponse:
    user = await auth_service.create_viewer(
        db,
        email=body.email,
        password=body.password,
        tenant_id=current_user.tenant_id,
    )
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login with email and password",
    description="Authenticate with an email/password pair to receive an access token.",
    openapi_extra={
        "requestBody": {
            "content": {
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "required": ["username", "password"],
                        "properties": {
                            "username": {
                                "type": "string",
                                "example": "user@example.com",
                                "description": "Registered email address",
                            },
                            "password": {
                                "type": "string",
                                "example": "StrongPass123!",
                                "description": "Account password",
                            },
                        },
                    }
                }
            }
        }
    },
)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: AdminSessionDep,
    redis: RedisDep,
    response: Response,
) -> TokenResponse:
    tokens = await auth_service.authenticate(
        db, redis, username=form_data.username, password=form_data.password
    )
    _set_refresh_cookie(response, tokens.pop("refresh_token"))
    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    db: AdminSessionDep,
    redis: RedisDep,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )
    tokens = await auth_service.refresh_tokens(db, redis, token=refresh_token)
    _set_refresh_cookie(response, tokens.pop("refresh_token"))
    return TokenResponse(**tokens)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    redis: RedisDep,
    response: Response,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> None:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token missing",
        )
    await auth_service.logout(redis, token=refresh_token)
    _clear_refresh_cookie(response)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(current_user)
