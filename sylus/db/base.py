from typing import AsyncGenerator
from sqlalchemy.pool import NullPool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None

def get_engine(db_url: str | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        if db_url is None:
            from sylus.config import config
            db_url = config.database_url

        engine_kwargs = {"echo": False}
        if "sqlite" not in db_url:
            engine_kwargs["poolclass"] = NullPool

        _engine = create_async_engine(db_url, **engine_kwargs)
    return _engine

def get_session_factory(engine: AsyncEngine | None = None) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        if engine is None:
            engine = get_engine()
        _sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    return _sessionmaker

def get_session() -> AsyncSession:
    factory = get_session_factory()
    return factory()

async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session
