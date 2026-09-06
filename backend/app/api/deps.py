from collections.abc import Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.account import User
from app.repositories.account_repository import AccountRepository
from app.services.auth_service import AuthService


SESSION_COOKIE_NAME = "archai_session"


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_account_repository(db: Session = Depends(get_db)) -> AccountRepository:
    return AccountRepository(db)


def get_auth_service(
    repository: AccountRepository = Depends(get_account_repository),
) -> AuthService:
    return AuthService(repository, get_settings().auth_session_hours)


def get_optional_current_user(
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
) -> User | None:
    return auth_service.user_from_token(request.cookies.get(SESSION_COOKIE_NAME))


def require_current_user(
    user: User | None = Depends(get_optional_current_user),
) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

