import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sylus.db.base import Base

@pytest_asyncio.fixture
async def async_engine(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    monkeypatch.setattr("sylus.db.base._engine", engine)
    monkeypatch.setattr("sylus.db.base._sessionmaker", session_factory)

    yield engine
    await engine.dispose()

@pytest_asyncio.fixture
async def db_session(async_engine):
    session_factory = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        yield session
