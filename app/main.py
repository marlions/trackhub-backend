from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from app.database import Base, engine
from app.routers import auth, comments, likes, playlists, tracks, users
from app.utils import ensure_upload_dir

app = FastAPI(
    title="TrackHub API",
    description="Backend API for Android music service MVP",
    version="0.2.0",
)


def _table_columns(inspector, table_name: str) -> set[str]:
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def ensure_database_columns() -> None:
    inspector = inspect(engine)

    with engine.begin() as connection:
        track_columns = _table_columns(inspector, "tracks")
        if track_columns:
            if "duration_seconds" not in track_columns:
                connection.execute(text("ALTER TABLE tracks ADD COLUMN duration_seconds INTEGER NOT NULL DEFAULT 0"))
            if "likes_count" not in track_columns:
                connection.execute(text("ALTER TABLE tracks ADD COLUMN likes_count INTEGER NOT NULL DEFAULT 0"))
            if "comments_count" not in track_columns:
                connection.execute(text("ALTER TABLE tracks ADD COLUMN comments_count INTEGER NOT NULL DEFAULT 0"))
            if "play_count" not in track_columns:
                connection.execute(text("ALTER TABLE tracks ADD COLUMN play_count INTEGER NOT NULL DEFAULT 0"))

        user_columns = _table_columns(inspector, "users")
        if user_columns:
            if "followers_count" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN followers_count INTEGER NOT NULL DEFAULT 0"))
            if "following_count" not in user_columns:
                connection.execute(text("ALTER TABLE users ADD COLUMN following_count INTEGER NOT NULL DEFAULT 0"))

        playlist_columns = _table_columns(inspector, "playlists")
        if playlist_columns:
            if "tracks_count" not in playlist_columns:
                connection.execute(text("ALTER TABLE playlists ADD COLUMN tracks_count INTEGER NOT NULL DEFAULT 0"))


def backfill_denormalized_counters() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    with engine.begin() as connection:
        if {"tracks", "likes"}.issubset(table_names):
            connection.execute(
                text(
                    """
                    UPDATE tracks
                    SET likes_count = COALESCE((
                        SELECT COUNT(*) FROM likes WHERE likes.track_id = tracks.id
                    ), 0)
                    """
                )
            )

        if {"tracks", "comments"}.issubset(table_names):
            connection.execute(
                text(
                    """
                    UPDATE tracks
                    SET comments_count = COALESCE((
                        SELECT COUNT(*) FROM comments WHERE comments.track_id = tracks.id
                    ), 0)
                    """
                )
            )

        if {"playlists", "playlist_tracks", "tracks"}.issubset(table_names):
            connection.execute(
                text(
                    """
                    UPDATE playlists
                    SET tracks_count = COALESCE((
                        SELECT COUNT(*)
                        FROM playlist_tracks
                        JOIN tracks ON tracks.id = playlist_tracks.track_id
                        WHERE playlist_tracks.playlist_id = playlists.id
                          AND tracks.is_deleted = false
                    ), 0)
                    """
                )
            )

        if {"users", "follows"}.issubset(table_names):
            connection.execute(
                text(
                    """
                    UPDATE users
                    SET followers_count = COALESCE((
                        SELECT COUNT(*) FROM follows WHERE follows.following_id = users.id
                    ), 0)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE users
                    SET following_count = COALESCE((
                        SELECT COUNT(*) FROM follows WHERE follows.follower_id = users.id
                    ), 0)
                    """
                )
            )


def ensure_database_indexes() -> None:
    """
    Создаёт индексы под основные сценарии приложения.
    Простые btree-индексы обязательные. pg_trgm-индексы создаются только если БД PostgreSQL
    разрешает расширение pg_trgm.
    """
    index_statements = [
        "CREATE INDEX IF NOT EXISTS ix_tracks_visible_created ON tracks (is_deleted, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_tracks_owner_visible_created ON tracks (uploaded_by_id, is_deleted, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_likes_user_track ON likes (user_id, track_id)",
        "CREATE INDEX IF NOT EXISTS ix_likes_track_id ON likes (track_id)",
        "CREATE INDEX IF NOT EXISTS ix_comments_track_created ON comments (track_id, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_playlist_tracks_playlist_created ON playlist_tracks (playlist_id, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_playlist_tracks_track_id ON playlist_tracks (track_id)",
        "CREATE INDEX IF NOT EXISTS ix_playlists_owner_created ON playlists (owner_id, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_follows_follower_created ON follows (follower_id, created_at DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS ix_follows_following_id ON follows (following_id)",
    ]

    with engine.begin() as connection:
        for statement in index_statements:
            try:
                connection.execute(text(statement))
            except Exception:
                # Индексы ускоряют работу, но их ошибка не должна ломать запуск MVP.
                pass

    # PostgreSQL-only оптимизация поиска по подстроке.
    if not engine.url.get_backend_name().startswith("postgresql"):
        return

    trigram_statements = [
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
        "CREATE INDEX IF NOT EXISTS ix_tracks_title_trgm ON tracks USING gin (lower(title) gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_tracks_author_trgm ON tracks USING gin (lower(author) gin_trgm_ops)",
        "CREATE INDEX IF NOT EXISTS ix_users_username_trgm ON users USING gin (lower(username) gin_trgm_ops)",
    ]

    for statement in trigram_statements:
        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except Exception:
            pass


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    ensure_upload_dir()
    Base.metadata.create_all(bind=engine)
    ensure_database_columns()
    backfill_denormalized_counters()
    ensure_database_indexes()


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(tracks.router)
app.include_router(likes.router)
app.include_router(comments.router)
app.include_router(playlists.router)
app.include_router(users.router)
