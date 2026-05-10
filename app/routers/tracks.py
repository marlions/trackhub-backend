import os
import re
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, get_db
from app.models import Comment, Like, Track, User
from app.schemas import TrackOut
from app.security import get_current_user
from app.utils import (
    detect_audio_duration_seconds,
    ensure_upload_dir,
    make_safe_audio_filename,
    validate_audio_type,
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


async def save_upload_file_chunked(file: UploadFile, file_path: Path) -> int:
    """Save UploadFile without loading the whole audio file into memory."""
    max_size = settings.max_audio_size_mb * 1024 * 1024
    total_size = 0

    try:
        with file_path.open("wb") as output:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break

                total_size += len(chunk)
                if total_size > max_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File is too large. Max size is {settings.max_audio_size_mb} MB",
                    )

                output.write(chunk)
    except Exception:
        try:
            if file_path.exists() and file_path.is_file():
                file_path.unlink()
        finally:
            raise

    return total_size


def get_track_count_subqueries(db: Session):
    likes_subquery = (
        db.query(
            Like.track_id.label("track_id"),
            func.count(Like.id).label("likes_count"),
        )
        .group_by(Like.track_id)
        .subquery()
    )

    comments_subquery = (
        db.query(
            Comment.track_id.label("track_id"),
            func.count(Comment.id).label("comments_count"),
        )
        .group_by(Comment.track_id)
        .subquery()
    )

    return likes_subquery, comments_subquery


def track_row_to_out(track: Track, likes_count: int | None = 0, comments_count: int | None = 0) -> TrackOut:
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
        likes_count=int(likes_count or 0),
        comments_count=int(comments_count or 0),
    )


def track_rows_to_out(rows) -> list[TrackOut]:
    return [track_row_to_out(track, likes_count, comments_count) for track, likes_count, comments_count in rows]


def query_tracks_with_counts(db: Session):
    likes_subquery, comments_subquery = get_track_count_subqueries(db)

    return (
        db.query(
            Track,
            func.coalesce(likes_subquery.c.likes_count, 0).label("likes_count"),
            func.coalesce(comments_subquery.c.comments_count, 0).label("comments_count"),
        )
        .outerjoin(likes_subquery, likes_subquery.c.track_id == Track.id)
        .outerjoin(comments_subquery, comments_subquery.c.track_id == Track.id)
    )


def get_track_out_or_404(track_id: int, db: Session) -> TrackOut:
    row = (
        query_tracks_with_counts(db)
        .filter(
            Track.id == track_id,
            Track.is_deleted == False,  # noqa: E712
        )
        .first()
    )

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    track, likes_count, comments_count = row
    return track_row_to_out(track, likes_count, comments_count)


# Backward-compatible name for older imports from other routers.
def to_track_out(track: Track, db: Session) -> TrackOut:
    row = (
        query_tracks_with_counts(db)
        .filter(Track.id == track.id)
        .first()
    )

    if row is None:
        return track_row_to_out(track, 0, 0)

    track_obj, likes_count, comments_count = row
    return track_row_to_out(track_obj, likes_count, comments_count)


def increment_track_play_count(track_id: int) -> None:
    """Increment play counter outside the stream response path."""
    db = SessionLocal()
    try:
        db.query(Track).filter(
            Track.id == track_id,
            Track.is_deleted == False,  # noqa: E712
        ).update(
            {Track.play_count: Track.play_count + 1},
            synchronize_session=False,
        )
        db.commit()
    finally:
        db.close()


@router.post("/upload", response_model=TrackOut, status_code=status.HTTP_201_CREATED)
async def upload_track(
    title: str = Form(..., min_length=1, max_length=100),
    author: str = Form(..., min_length=1, max_length=50),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    extension = validate_audio_type(file)
    upload_dir = ensure_upload_dir()
    filename = make_safe_audio_filename(extension)
    file_path = upload_dir / filename

    file_size_bytes = await save_upload_file_chunked(file, file_path)
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

    return track_row_to_out(track, 0, 0)


@router.get("", response_model=list[TrackOut])
def list_tracks(db: Session = Depends(get_db), limit: int = 50, offset: int = 0):
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)

    rows = (
        query_tracks_with_counts(db)
        .filter(Track.is_deleted == False)  # noqa: E712
        .order_by(Track.created_at.desc())
        .offset(safe_offset)
        .limit(safe_limit)
        .all()
    )

    return track_rows_to_out(rows)


@router.get("/my", response_model=list[TrackOut])
def list_my_tracks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
):
    safe_limit = min(max(limit, 1), 100)
    safe_offset = max(offset, 0)

    rows = (
        query_tracks_with_counts(db)
        .filter(
            Track.uploaded_by_id == current_user.id,
            Track.is_deleted == False,  # noqa: E712
        )
        .order_by(Track.created_at.desc())
        .offset(safe_offset)
        .limit(safe_limit)
        .all()
    )

    return track_rows_to_out(rows)


@router.get("/search", response_model=list[TrackOut])
def search_tracks(query: str = "", db: Session = Depends(get_db), limit: int = 50):
    normalized_query = query.strip().lower()
    safe_limit = min(max(limit, 1), 100)

    base_query = query_tracks_with_counts(db).filter(Track.is_deleted == False)  # noqa: E712

    if normalized_query:
        pattern = f"%{normalized_query}%"
        base_query = base_query.filter(
            or_(
                func.lower(Track.title).like(pattern),
                func.lower(Track.author).like(pattern),
            )
        )

    rows = (
        base_query
        .order_by(Track.created_at.desc())
        .limit(safe_limit)
        .all()
    )

    return track_rows_to_out(rows)


@router.get("/{track_id}", response_model=TrackOut)
def get_track(track_id: int, db: Session = Depends(get_db)):
    return get_track_out_or_404(track_id, db)


@router.post("/{track_id}/play", status_code=status.HTTP_200_OK)
def register_track_play(
    track_id: int,
    db: Session = Depends(get_db),
):
    updated_rows = (
        db.query(Track)
        .filter(
            Track.id == track_id,
            Track.is_deleted == False,  # noqa: E712
        )
        .update(
            {Track.play_count: Track.play_count + 1},
            synchronize_session=False,
        )
    )

    if not updated_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    db.commit()

    play_count = (
        db.query(Track.play_count)
        .filter(Track.id == track_id)
        .scalar()
        or 0
    )

    return {
        "track_id": track_id,
        "play_count": int(play_count),
    }


@router.get("/{track_id}/stream")
def stream_track(
    track_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    row = (
        db.query(Track.id, Track.filename, Track.content_type)
        .filter(
            Track.id == track_id,
            Track.is_deleted == False,  # noqa: E712
        )
        .first()
    )

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    _, filename, content_type = row
    file_path = Path(settings.upload_dir) / filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Audio file not found",
        )

    # Совместимость с текущим Android: счётчик всё ещё растёт при /stream,
    # но обновление уходит в background task и не задерживает старт воспроизведения.
    background_tasks.add_task(increment_track_play_count, track_id)

    media_type = content_type or "audio/mpeg"
    if "\n" in media_type or "\r" in media_type:
        media_type = "audio/mpeg"

    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=safe_download_filename(filename),
    )


@router.delete("/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_track(
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = (
        db.query(Track)
        .filter(
            Track.id == track_id,
            Track.uploaded_by_id == current_user.id,
            Track.is_deleted == False,  # noqa: E712
        )
        .first()
    )

    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    file_path = Path(settings.upload_dir) / track.filename

    track.is_deleted = True
    db.commit()

    # По требованиям файл должен удаляться с сервера.
    # Запись в БД оставляем как soft-delete, чтобы не ломать историю и связи.
    try:
        if file_path.exists() and file_path.is_file():
            file_path.unlink()
    except OSError:
        # Удаление записи уже выполнено; ошибка файловой системы не должна возвращать удалённый трек обратно.
        pass

    return None
