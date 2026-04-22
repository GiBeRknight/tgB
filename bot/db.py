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
        "ALTER TABLE regions ADD COLUMN IF NOT EXISTS scheme_photo_id VARCHAR(500) DEFAULT NULL",
        "ALTER TABLE regions ADD COLUMN IF NOT EXISTS link_doc VARCHAR(500) DEFAULT NULL",
        "ALTER TABLE regions ADD COLUMN IF NOT EXISTS group_id INTEGER REFERENCES region_groups(id) ON DELETE SET NULL",
        "ALTER TABLE region_groups ALTER COLUMN prefix DROP NOT NULL",
        "ALTER TABLE regions ALTER COLUMN size TYPE NUMERIC(10, 2) USING size::numeric",
        "ALTER TABLE regions ADD COLUMN IF NOT EXISTS doc_file_id VARCHAR(500) DEFAULT NULL",
        "ALTER TABLE regions ADD COLUMN IF NOT EXISTS doc_etag VARCHAR(255) DEFAULT NULL",
        # Allow nullable user references on logs / realtor credentials before adding FKs
        "ALTER TABLE action_logs ALTER COLUMN user_id DROP NOT NULL",
        "ALTER TABLE realtors ALTER COLUMN created_by DROP NOT NULL",
        # Orphan cleanup so FK creation can succeed
        "UPDATE action_logs SET user_id = NULL "
        "WHERE user_id IS NOT NULL AND user_id NOT IN (SELECT id FROM users)",
        "UPDATE realtors SET created_by = NULL "
        "WHERE created_by IS NOT NULL AND created_by NOT IN (SELECT id FROM users)",
        # Add FK constraints (idempotent via exception block, duplicates are ignored)
        "DO $$ BEGIN "
        "ALTER TABLE action_logs ADD CONSTRAINT fk_action_logs_user_id "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL; "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$",
        "DO $$ BEGIN "
        "ALTER TABLE realtors ADD CONSTRAINT fk_realtors_created_by "
        "FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL; "
        "EXCEPTION WHEN duplicate_object THEN NULL; END $$",
    ]
    for stmt in alter_statements:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
        except Exception as exc:
            logger.warning("ALTER failed: %s — %s", stmt, exc)
    # Create indexes for fast lookups
    index_statements = [
        "CREATE INDEX IF NOT EXISTS idx_regions_name ON regions(name)",
        "CREATE INDEX IF NOT EXISTS idx_regions_group_id ON regions(group_id)",
        "CREATE INDEX IF NOT EXISTS idx_region_photos_region_id ON region_photos(region_id)",
    ]
    for stmt in index_statements:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(stmt))
        except Exception as exc:
            logger.warning("Index creation failed: %s — %s", stmt, exc)

    # One-time migration: populate group_id from legacy name prefixes
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "UPDATE regions r SET group_id = g.id "
                "FROM region_groups g "
                "WHERE r.group_id IS NULL "
                "  AND g.prefix IS NOT NULL "
                "  AND r.name LIKE g.prefix || '%'"
            ))
            if result.rowcount:
                logger.info("Backfilled group_id for %d regions", result.rowcount)
    except Exception as exc:
        logger.warning("group_id backfill skipped: %s", exc)

    # Seed default region groups if table is empty
    try:
        from bot.models import RegionGroup
        async with async_session() as session:
            count = (await session.execute(text("SELECT count(*) FROM region_groups"))).scalar()
            if count == 0:
                session.add(RegionGroup(label="Грюнсдорф"))
                await session.commit()
                logger.info("Seeded default region group 'Грюнсдорф'")
    except Exception as exc:
        logger.warning("Region group seeding skipped: %s", exc)

    logger.info("Schema migrations applied")
