import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError

from app.models.account import AuthSession, User
from app.repositories.account_repository import AccountRepository
from app.schemas.account import ProfileUpdateRequest, SignUpRequest


class DuplicateAccountError(ValueError):
    pass


class AuthService:
    def __init__(self, repository: AccountRepository, session_hours: int) -> None:
        self.repository = repository
        self.session_hours = session_hours
        self.password_hash = PasswordHash.recommended()

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def register(self, payload: SignUpRequest) -> User:
        username_key = payload.username.casefold()
        email = str(payload.email).strip()
        email_key = email.casefold()

        if self.repository.get_user_by_username(username_key):
            raise DuplicateAccountError("Username is already registered")
        if self.repository.get_user_by_email(email_key):
            raise DuplicateAccountError("Email address is already registered")

        user = User(
            username=payload.username,
            username_key=username_key,
            email=email,
            email_key=email_key,
            phone_number=payload.phone_number,
            password_hash=self.password_hash.hash(payload.password),
        )
        try:
            return self.repository.add_user(user)
        except IntegrityError as exc:
            raise DuplicateAccountError("Username or email address is already registered") from exc

    def verify_credentials(self, identifier: str, password: str) -> User | None:
        user = self.repository.get_user_by_identifier(identifier)
        if user is None or not self.password_hash.verify(password, user.password_hash):
            return None
        return user

    def create_session(self, user: User) -> tuple[str, datetime]:
        token = secrets.token_urlsafe(48)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=self.session_hours)
        self.repository.add_session(
            AuthSession(
                user_id=user.id,
                token_hash=self.token_hash(token),
                expires_at=expires_at,
            )
        )
        return token, expires_at

    def user_from_token(self, token: str | None) -> User | None:
        if not token:
            return None
        session = self.repository.get_session_by_hash(self.token_hash(token))
        if session is None:
            return None

        expires_at = session.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            self.repository.delete_session_by_hash(session.token_hash)
            return None
        return session.user

    def logout(self, token: str | None) -> None:
        if token:
            self.repository.delete_session_by_hash(self.token_hash(token))

    def update_profile(self, user: User, payload: ProfileUpdateRequest) -> User:
        user.phone_number = payload.phone_number
        return self.repository.save_user(user)
