import asyncio
import logging

from aiogram import Bot, Dispatcher
from sqlalchemy import text

from app.bot.router import routers
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db.session import get_session

logger = logging.getLogger(__name__)


async def _check_db_connection() -> None:
    async with get_session() as session:
        await session.execute(text("SELECT 1"))
    logger.info("DB connected OK")


async def main() -> None:
    setup_logging()
    settings = get_settings()

    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    for router in routers:
        dp.include_router(router)

    await _check_db_connection()

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
