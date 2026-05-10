from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import auth, comments, likes, playlists, tracks
from app.routers import users
from app.utils import ensure_upload_dir
from sqlalchemy import inspect, text

app = FastAPI(
    title="TrackHub API",
    description="Backend API for Android music service MVP",
    version="0.1.0",
)

def ensure_database_columns():
    inspector = inspect(engine)

    if "tracks" not in inspector.get_table_names():
        return

    track_columns = {column["name"] for column in inspector.get_columns("tracks")}

    if "duration_seconds" not in track_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE tracks ADD COLUMN duration_seconds INTEGER NOT NULL DEFAULT 0")
            )

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


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(tracks.router)
app.include_router(likes.router)
app.include_router(comments.router)
app.include_router(playlists.router)
app.include_router(users.router)
