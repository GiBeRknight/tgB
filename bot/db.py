from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bot.config import DATABASE_URL

engine = create_async_engine(DATABASE_URL)
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db():
    from bot.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
