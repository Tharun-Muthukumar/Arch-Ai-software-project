from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    SESSION_COOKIE_NAME,
    get_account_repository,
    get_auth_service,
    get_db,
    require_current_user,
)
from app.core.config import get_settings
from app.models.account import User
from app.repositories.account_repository import AccountRepository
from app.schemas.account import (
    AuthResponse,
    ProfileUpdateRequest,
    SignInRequest,
    SignUpRequest,
    UserLookup,
    UserPublic,
)
from app.services.auth_service import AuthService, DuplicateAccountError


router = APIRouter(prefix="/auth", tags=["authentication"])
users_router = APIRouter(prefix="/users", tags=["users"])


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.auth_session_hours * 60 * 60,
        httponly=True,
        secure=settings.environment.casefold() not in {"development", "test"},
        samesite="lax",
        path="/",
    )


@router.post("/signup", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def signup(
    payload: SignUpRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    try:
        user = auth_service.register(payload)
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return AuthResponse(user=UserPublic.model_validate(user))


@router.post("/login", response_model=AuthResponse)
def login(
    payload: SignInRequest,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    user = auth_service.verify_credentials(payload.identifier, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect username, email, or password")
    token, _expires_at = auth_service.create_session(user)
    set_session_cookie(response, token)
    return AuthResponse(user=UserPublic.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    settings = get_settings()
    auth_service.logout(request.cookies.get(SESSION_COOKIE_NAME))
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=settings.environment.casefold() not in {"development", "test"},
        httponly=True,
        samesite="lax",
    )


@router.get("/me", response_model=AuthResponse)
def me(user: User = Depends(require_current_user)) -> AuthResponse:
    return AuthResponse(user=UserPublic.model_validate(user))


@router.patch("/profile", response_model=AuthResponse)
def update_profile(
    payload: ProfileUpdateRequest,
    user: User = Depends(require_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    updated = auth_service.update_profile(user, payload)
    return AuthResponse(user=UserPublic.model_validate(updated))


@users_router.get("/search", response_model=list[UserLookup])
def search_users(
    q: str = Query(min_length=2, max_length=320),
    user: User = Depends(require_current_user),
    repository: AccountRepository = Depends(get_account_repository),
) -> list[UserLookup]:
    return [
        UserLookup(id=item.id, username=item.username, email=item.email)
        for item in repository.search_users(q, user.id)
    ]
