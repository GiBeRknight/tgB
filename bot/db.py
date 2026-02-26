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

    # Add missing columns (create_all won't alter existing tables)
    alter_statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_realtor BOOLEAN DEFAULT FALSE",
        "ALTER TABLE regions ADD COLUMN IF NOT EXISTS size INTEGER DEFAULT 5",
        "ALTER TABLE regions ADD COLUMN IF NOT EXISTS photo_file_id VARCHAR(500) DEFAULT NULL",
        "ALTER TABLE region_photos ADD COLUMN IF NOT EXISTS file_type VARCHAR(20) DEFAULT 'photo'",
    ]
    for stmt in alter_statements:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
        except Exception as exc:
            logger.warning("ALTER failed: %s — %s", stmt, exc)
    # Create index for fast region name lookups
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("CREATE INDEX IF NOT EXISTS idx_regions_name ON regions(name)")
            )
        logger.info("Index idx_regions_name ensured")
    except Exception as exc:
        logger.warning("Index creation failed: %s", exc)

    logger.info("Schema migrations applied")
