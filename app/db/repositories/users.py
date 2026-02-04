from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


class UsersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_user(
        self, username: str, password_hash: str, is_admin: bool = False
    ) -> User:
        user = User(username=username, password_hash=password_hash, is_admin=is_admin)
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def get_by_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def bind_telegram_id(self, user_id: int, telegram_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        user.telegram_id = telegram_id
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def unbind_telegram_id(self, telegram_id: int) -> User | None:
        result = await self._session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            return None
        user.telegram_id = None
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def update_last_login(self, user_id: int) -> User | None:
        result = await self._session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            return None
        user.last_login_at = datetime.utcnow()
        await self._session.commit()
        await self._session.refresh(user)
        return user
