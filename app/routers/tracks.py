import os
import re
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import exists, func, literal, or_, update
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import Like, Playlist, PlaylistTrack, Track, User
from app.schemas import TrackOut
from app.security import get_current_user, get_optional_current_user
from app.utils import (
    detect_audio_duration_seconds,
    ensure_upload_dir,
    make_safe_audio_filename,
    validate_audio_file,
    validate_audio_size,
)

router = APIRouter(prefix="/api/tracks", tags=["tracks"])
UPLOAD_CHUNK_SIZE = 1024 * 1024


def safe_download_filename(filename: str | None) -> str:
    if not filename:
        return "track.mp3"

    name = os.path.basename(filename)
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)

    if not name:
        return "track.mp3"

    return name


def track_to_out(track: Track, is_liked: bool = False) -> TrackOut:
    return TrackOut(
        id=track.id,
        title=track.title,
        author=track.author,
        original_filename=track.original_filename,
        content_type=track.content_type,
        file_size_bytes=track.file_size_bytes,
        duration_seconds=track.duration_seconds,
        play_count=track.play_count,
        uploaded_by_id=track.uploaded_by_id,
        created_at=track.created_at,
        stream_url=f"/api/tracks/{track.id}/stream",
        likes_count=track.likes_count,
        comments_count=track.comments_count,
        is_liked=is_liked,
    )


def track_rows_query(db: Session, current_user_id: int | None):
    if current_user_id is None:
        is_liked_expr = literal(False)
    else:
        is_liked_expr = exists().where(
            Like.user_id == current_user_id,
            Like.track_id == Track.id,
        )

    return db.query(Track, is_liked_expr.label("is_liked"))


def rows_to_track_out(rows: list[tuple[Track, bool]]) -> list[TrackOut]:
    return [track_to_out(track, bool(is_liked)) for track, is_liked in rows]


@router.post("/upload", response_model=TrackOut, status_code=status.HTTP_201_CREATED)
async def upload_track(
    title: str = Form(..., min_length=1, max_length=100),
    author: str = Form(..., min_length=1, max_length=50),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extension = validate_audio_file(file)
    upload_dir = ensure_upload_dir()
    filename = make_safe_audio_filename(extension)
    file_path = upload_dir / filename

    file_size_bytes = 0

    try:
        with file_path.open("wb") as output:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break

                file_size_bytes += len(chunk)
                validate_audio_size(file_size_bytes)
                output.write(chunk)
    except Exception:
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        raise

    if file_size_bytes <= 0:
        if file_path.exists():
            file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file is empty",
        )

    duration_seconds = detect_audio_duration_seconds(file_path)

    track = Track(
        title=title.strip(),
        author=author.strip(),
        filename=filename,
        original_filename=file.filename or filename,
        content_type=file.content_type or "audio/mpeg",
        file_size_bytes=file_size_bytes,
        duration_seconds=duration_seconds,
        uploaded_by_id=current_user.id,
    )
    db.add(track)
    db.commit()
    db.refresh(track)

    return track_to_out(track, is_liked=False)


@router.get("", response_model=list[TrackOut])
def list_tracks(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
    current_user_id = current_user.id if current_user else None

    rows = (
        track_rows_query(db, current_user_id)
        .filter(Track.is_deleted == False)  # noqa: E712
        .order_by(Track.created_at.desc(), Track.id.desc())
        .offset(safe_offset)
        .limit(safe_limit)
        .all()
    )
    return rows_to_track_out(rows)


@router.get("/my", response_model=list[TrackOut])
def list_my_tracks(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        track_rows_query(db, current_user.id)
        .filter(
            Track.uploaded_by_id == current_user.id,
            Track.is_deleted == False,  # noqa: E712
        )
        .order_by(Track.created_at.desc(), Track.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows_to_track_out(rows)


@router.get("/liked", response_model=list[TrackOut])
def list_liked_tracks(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Track, literal(True).label("is_liked"))
        .join(Like, Like.track_id == Track.id)
        .filter(
            Like.user_id == current_user.id,
            Track.is_deleted == False,  # noqa: E712
        )
        .order_by(Like.created_at.desc(), Track.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows_to_track_out(rows)


@router.get("/search", response_model=list[TrackOut])
def search_tracks(
    query: str,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    normalized_text = query.strip().lower()
    current_user_id = current_user.id if current_user else None

    if not normalized_text:
        rows = (
            track_rows_query(db, current_user_id)
            .filter(Track.is_deleted == False)  # noqa: E712
            .order_by(Track.created_at.desc(), Track.id.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return rows_to_track_out(rows)

    normalized = f"%{normalized_text}%"
    rows = (
        track_rows_query(db, current_user_id)
        .filter(
            Track.is_deleted == False,  # noqa: E712
            or_(func.lower(Track.title).like(normalized), func.lower(Track.author).like(normalized)),
        )
        .order_by(Track.created_at.desc(), Track.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return rows_to_track_out(rows)


@router.get("/{track_id}", response_model=TrackOut)
def get_track(
    track_id: int,
    db: Session = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    current_user_id = current_user.id if current_user else None
    row = (
        track_rows_query(db, current_user_id)
        .filter(Track.id == track_id, Track.is_deleted == False)  # noqa: E712
        .first()
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    track, is_liked = row
    return track_to_out(track, bool(is_liked))


@router.get("/{track_id}/stream")
def stream_track(
    track_id: int,
    db: Session = Depends(get_db),
):
    track = db.query(Track).filter(
        Track.id == track_id,
        Track.is_deleted == False,  # noqa: E712
    ).first()

    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    file_path = Path(settings.upload_dir) / track.filename

    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found",
        )

    media_type = track.content_type or "audio/mpeg"
    if "\n" in media_type or "\r" in media_type:
        media_type = "audio/mpeg"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
    )


@router.post("/{track_id}/play")
def register_track_play(
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(Track).filter(
        Track.id == track_id,
        Track.is_deleted == False,  # noqa: E712
    ).first()

    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    db.execute(
        update(Track)
        .where(Track.id == track_id)
        .values(play_count=Track.play_count + 1)
    )
    db.commit()
    db.refresh(track)

    return {"track_id": track_id, "play_count": track.play_count}


@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(Track).filter(Track.id == track_id, Track.uploaded_by_id == current_user.id).first()
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    file_path = Path(settings.upload_dir) / track.filename

    if not track.is_deleted:
        playlist_ids = [
            playlist_id
            for (playlist_id,) in db.query(PlaylistTrack.playlist_id)
            .filter(PlaylistTrack.track_id == track.id)
            .all()
        ]

        if playlist_ids:
            playlists = db.query(Playlist).filter(Playlist.id.in_(playlist_ids)).all()
            for playlist in playlists:
                playlist.tracks_count = max(0, playlist.tracks_count - 1)

    track.is_deleted = True
    db.commit()

    try:
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
    except OSError:
        pass

    return None
