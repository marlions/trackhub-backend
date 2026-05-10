from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


def _engine_kwargs() -> dict:
    """Reasonable defaults for the MVP backend.

    PostgreSQL benefits from a small connection pool. SQLite does not accept the
    same pool arguments, so keep this conditional for local experiments/tests.
    """
    kwargs: dict = {
        "pool_pre_ping": True,
    }

    database_url = make_url(settings.database_url)
    if database_url.get_backend_name() != "sqlite":
        kwargs.update(
            pool_size=10,
            max_overflow=20,
            pool_recycle=1800,
        )

    return kwargs


engine = create_engine(settings.database_url, **_engine_kwargs())
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
