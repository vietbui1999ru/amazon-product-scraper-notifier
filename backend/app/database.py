from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from app.config import get_settings

Base = declarative_base()


def _make_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        echo=False,
    )


engine = _make_engine()

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def wait_for_db(retries: int = 10, delay: float = 2.0) -> None:
    """Wait for Postgres to accept connections. Schema is managed by Alembic."""
    import asyncio
    from sqlalchemy.exc import OperationalError
    from sqlalchemy import text

    for attempt in range(1, retries + 1):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            if attempt == retries:
                raise
            await asyncio.sleep(delay)


def run_migrations() -> None:
    """Run Alembic migrations to head. Safe to call on every startup."""
    import logging
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    ini_path = Path(__file__).parent.parent / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)

    logging.getLogger("alembic").setLevel(logging.INFO)
    command.upgrade(cfg, "head")


async def seed_products() -> None:
    """Insert config.yaml products that don't exist yet. Idempotent."""
    from app.config import get_settings
    from app.storage.repository import ProductRepository

    products = get_settings().products
    if not products:
        return

    async with AsyncSessionLocal() as session:
        repo = ProductRepository(session)
        for p in products:
            _, created = await repo.get_or_create_product(url=p.url, name=p.name)
            if created:
                await session.commit()
