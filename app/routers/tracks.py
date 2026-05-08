import os
import re
from fastapi.responses import FileResponse
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Comment, Like, Track, User
from app.schemas import TrackOut
from app.security import get_current_user
from app.utils import ensure_upload_dir, make_safe_audio_filename, validate_audio_file

router = APIRouter(prefix="/api/tracks", tags=["tracks"])

def safe_download_filename(filename: str | None) -> str:
    if not filename:
        return "track.mp3"

    name = os.path.basename(filename)

    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)

    if not name:
        return "track.mp3"

    return name

def to_track_out(track: Track, db: Session) -> TrackOut:
    likes_count = db.query(func.count(Like.id)).filter(Like.track_id == track.id).scalar() or 0
    comments_count = db.query(func.count(Comment.id)).filter(Comment.track_id == track.id).scalar() or 0
    return TrackOut(
        id=track.id,
        title=track.title,
        author=track.author,
        original_filename=track.original_filename,
        content_type=track.content_type,
        file_size_bytes=track.file_size_bytes,
        play_count=track.play_count,
        uploaded_by_id=track.uploaded_by_id,
        created_at=track.created_at,
        stream_url=f"/api/tracks/{track.id}/stream",
        likes_count=likes_count,
        comments_count=comments_count,
    )


@router.post("/upload", response_model=TrackOut, status_code=status.HTTP_201_CREATED)
async def upload_track(
    title: str = Form(..., min_length=1, max_length=255),
    author: str = Form(..., min_length=1, max_length=255),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content = await file.read()
    extension = validate_audio_file(file, content)
    upload_dir = ensure_upload_dir()
    filename = make_safe_audio_filename(extension)
    file_path = upload_dir / filename
    file_path.write_bytes(content)

    track = Track(
        title=title.strip(),
        author=author.strip(),
        filename=filename,
        original_filename=file.filename or filename,
        content_type=file.content_type or "audio/mpeg",
        file_size_bytes=len(content),
        uploaded_by_id=current_user.id,
    )
    db.add(track)
    db.commit()
    db.refresh(track)
    return to_track_out(track, db)


@router.get("", response_model=list[TrackOut])
def list_tracks(db: Session = Depends(get_db), limit: int = 50, offset: int = 0):
    tracks = (
        db.query(Track)
        .filter(Track.is_deleted == False)  # noqa: E712
        .order_by(Track.created_at.desc())
        .offset(offset)
        .limit(min(limit, 100))
        .all()
    )
    return [to_track_out(track, db) for track in tracks]


@router.get("/my", response_model=list[TrackOut])
def list_my_tracks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    tracks = (
        db.query(Track)
        .filter(Track.uploaded_by_id == current_user.id, Track.is_deleted == False)  # noqa: E712
        .order_by(Track.created_at.desc())
        .all()
    )
    return [to_track_out(track, db) for track in tracks]


@router.get("/search", response_model=list[TrackOut])
def search_tracks(query: str, db: Session = Depends(get_db)):
    normalized = f"%{query.strip().lower()}%"
    tracks = (
        db.query(Track)
        .filter(
            Track.is_deleted == False,  # noqa: E712
            or_(func.lower(Track.title).like(normalized), func.lower(Track.author).like(normalized)),
        )
        .order_by(Track.created_at.desc())
        .limit(50)
        .all()
    )
    return [to_track_out(track, db) for track in tracks]


@router.get("/{track_id}", response_model=TrackOut)
def get_track(track_id: int, db: Session = Depends(get_db)):
    track = db.query(Track).filter(Track.id == track_id, Track.is_deleted == False).first()  # noqa: E712
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")
    return to_track_out(track, db)


@router.get("/{track_id}/stream")
def stream_track(
    track_id: int,
    db: Session = Depends(get_db),
):
    track = db.query(Track).filter(
        Track.id == track_id,
        Track.is_deleted == False
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found"
        )

    if not os.path.exists(track.file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found"
        )

    track.play_count += 1
    db.commit()

    safe_filename = safe_download_filename(track.original_filename)

    media_type = track.content_type or "audio/mpeg"

    return FileResponse(
        path=track.file_path,
        media_type=media_type,
        filename=safe_filename
    )


@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(Track).filter(Track.id == track_id, Track.uploaded_by_id == current_user.id).first()
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    track.is_deleted = True
    db.commit()
    return None
