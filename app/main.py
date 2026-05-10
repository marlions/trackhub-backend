from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.database import Base, engine
from app.routers import auth, comments, likes, playlists, tracks, users
from app.utils import ensure_upload_dir

app = FastAPI(
    title="TrackHub API",
    description="Backend API for Android music service MVP",
    version="0.2.0-optimized",
)


INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_tracks_visible_created ON tracks (is_deleted, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_tracks_owner_visible_created ON tracks (uploaded_by_id, is_deleted, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_likes_track_id ON likes (track_id)",
    "CREATE INDEX IF NOT EXISTS ix_comments_track_created ON comments (track_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_playlist_tracks_playlist_created ON playlist_tracks (playlist_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_playlist_tracks_track_id ON playlist_tracks (track_id)",
    "CREATE INDEX IF NOT EXISTS ix_playlists_owner_created ON playlists (owner_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_follows_follower_created ON follows (follower_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_follows_following_id ON follows (following_id)",
]

POSTGRES_TRGM_INDEX_STATEMENTS = [
    "CREATE INDEX IF NOT EXISTS ix_tracks_title_trgm ON tracks USING gin (lower(title) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_tracks_author_trgm ON tracks USING gin (lower(author) gin_trgm_ops)",
    "CREATE INDEX IF NOT EXISTS ix_users_username_trgm ON users USING gin (lower(username) gin_trgm_ops)",
]


def ensure_database_columns() -> None:
    inspector = inspect(engine)

    if "tracks" not in inspector.get_table_names():
        return

    track_columns = {column["name"] for column in inspector.get_columns("tracks")}

    if "duration_seconds" not in track_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE tracks ADD COLUMN duration_seconds INTEGER NOT NULL DEFAULT 0")
            )


def ensure_database_indexes() -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    required_tables = {"tracks", "likes", "comments", "playlist_tracks", "playlists", "follows", "users"}
    if not required_tables.issubset(table_names):
        return

    with engine.begin() as connection:
        for statement in INDEX_STATEMENTS:
            connection.execute(text(statement))

        if engine.dialect.name == "postgresql":
            try:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
                for statement in POSTGRES_TRGM_INDEX_STATEMENTS:
                    connection.execute(text(statement))
            except SQLAlchemyError:
                # pg_trgm ускоряет поиск по подстроке, но приложение должно запускаться
                # даже если у пользователя БД нет прав на CREATE EXTENSION.
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
