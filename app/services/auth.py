from __future__ import annotations

import re

from passlib.context import CryptContext

from app.db.models import User
from app.db.repositories.users import UsersRepository

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


class UserAlreadyExists(Exception):
    pass


class InvalidCredentials(Exception):
    pass


class ValidationError(Exception):
    pass


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def _validate_credentials(username: str, password: str) -> None:
    if not USERNAME_RE.match(username):
        raise ValidationError(
            "Username должен быть 3-32 символа и содержать только латиницу, цифры и _. "
            "Пример: user_123"
        )
    if len(password) < 8:
        raise ValidationError("Пароль должен быть не короче 8 символов.")


async def register(
    repo: UsersRepository, username: str, password: str
) -> User:
    _validate_credentials(username, password)
    existing = await repo.get_by_username(username)
    if existing is not None:
        raise UserAlreadyExists("Пользователь уже существует.")

    password_hash = hash_password(password)
    return await repo.create_user(username=username, password_hash=password_hash)


async def login(
    repo: UsersRepository, username: str, password: str, telegram_id: int
) -> User:
    user = await repo.get_by_username(username)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentials("Неверный логин или пароль.")

    bound = await repo.bind_telegram_id(user.id, telegram_id)
    if bound is None:
        raise InvalidCredentials("Не удалось привязать Telegram ID.")

    updated = await repo.update_last_login(user.id)
    if updated is None:
        raise InvalidCredentials("Не удалось обновить данные входа.")
    return updated
