import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.config import DATABASE_URL

logger = logging.getLogger(__name__)

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    from bot.models import Base

    # Retry DB connection (container may start before postgres is ready)
    for attempt in range(1, 6):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables ensured")
            break
        except Exception as exc:
            logger.warning("DB connect attempt %d/5 failed: %s", attempt, exc)
            if attempt == 5:
                raise
            await asyncio.sleep(2)

    # Add is_admin column if missing (create_all won't alter existing tables)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(
                "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"
            ))
        logger.info("is_admin column ensured")
    except Exception as exc:
        logger.warning("Could not add is_admin column: %s", exc)
