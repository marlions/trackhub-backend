from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import auth, comments, likes, playlists, tracks
from app.utils import ensure_upload_dir

app = FastAPI(
    title="TrackHub API",
    description="Backend API for Android music service MVP",
    version="0.1.0",
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


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


app.include_router(auth.router)
app.include_router(tracks.router)
app.include_router(likes.router)
app.include_router(comments.router)
app.include_router(playlists.router)
