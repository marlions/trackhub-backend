from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Playlist, PlaylistTrack, Track, User
from app.schemas import PlaylistCreate, PlaylistOut, TrackOut
from app.security import get_current_user
from app.routers.tracks import get_track_count_subqueries, track_rows_to_out

router = APIRouter(prefix="/api/playlists", tags=["playlists"])

MAX_TRACKS_PER_PLAYLIST = 100


def playlist_row_to_out(playlist: Playlist, tracks_count: int | None = 0) -> PlaylistOut:
    return PlaylistOut(
        id=playlist.id,
        name=playlist.name,
        owner_id=playlist.owner_id,
        created_at=playlist.created_at,
        tracks_count=int(tracks_count or 0),
    )


def playlist_counts_subquery(db: Session):
    return (
        db.query(
            PlaylistTrack.playlist_id.label("playlist_id"),
            func.count(PlaylistTrack.id).label("tracks_count"),
        )
        .join(Track, PlaylistTrack.track_id == Track.id)
        .filter(Track.is_deleted == False)  # noqa: E712
        .group_by(PlaylistTrack.playlist_id)
        .subquery()
    )


# Backward-compatible name for older imports/tests.
def to_playlist_out(playlist: Playlist, db: Session) -> PlaylistOut:
    tracks_count = (
        db.query(func.count(PlaylistTrack.id))
        .join(Track, PlaylistTrack.track_id == Track.id)
        .filter(
            PlaylistTrack.playlist_id == playlist.id,
            Track.is_deleted == False,  # noqa: E712
        )
        .scalar()
        or 0
    )
    return playlist_row_to_out(playlist, tracks_count)


@router.post("", response_model=PlaylistOut, status_code=status.HTTP_201_CREATED)
def create_playlist(
    payload: PlaylistCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist = Playlist(name=payload.name.strip(), owner_id=current_user.id)
    db.add(playlist)
    db.commit()
    db.refresh(playlist)

    return playlist_row_to_out(playlist, 0)


@router.get("", response_model=list[PlaylistOut])
def list_my_playlists(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    counts_subquery = playlist_counts_subquery(db)

    rows = (
        db.query(
            Playlist,
            func.coalesce(counts_subquery.c.tracks_count, 0).label("tracks_count"),
        )
        .outerjoin(counts_subquery, counts_subquery.c.playlist_id == Playlist.id)
        .filter(Playlist.owner_id == current_user.id)
        .order_by(Playlist.created_at.desc())
        .all()
    )

    return [playlist_row_to_out(playlist, tracks_count) for playlist, tracks_count in rows]


@router.post("/{playlist_id}/tracks/{track_id}", status_code=status.HTTP_201_CREATED)
def add_track_to_playlist(
    playlist_id: int,
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist_exists = (
        db.query(Playlist.id)
        .filter(
            Playlist.id == playlist_id,
            Playlist.owner_id == current_user.id,
        )
        .first()
    )
    if not playlist_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    track_exists = (
        db.query(Track.id)
        .filter(
            Track.id == track_id,
            Track.is_deleted == False,  # noqa: E712
        )
        .first()
    )
    if not track_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    existing = (
        db.query(PlaylistTrack.id)
        .filter(
            PlaylistTrack.playlist_id == playlist_id,
            PlaylistTrack.track_id == track_id,
        )
        .first()
    )
    if existing:
        return {"message": "Track is already in playlist"}

    tracks_count = (
        db.query(func.count(PlaylistTrack.id))
        .join(Track, PlaylistTrack.track_id == Track.id)
        .filter(
            PlaylistTrack.playlist_id == playlist_id,
            Track.is_deleted == False,  # noqa: E712
        )
        .scalar()
        or 0
    )

    if tracks_count >= MAX_TRACKS_PER_PLAYLIST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"В плейлист нельзя добавить больше {MAX_TRACKS_PER_PLAYLIST} треков",
        )

    link = PlaylistTrack(playlist_id=playlist_id, track_id=track_id)
    db.add(link)
    db.commit()

    return {"message": "Track added to playlist"}


@router.get("/{playlist_id}/tracks", response_model=list[TrackOut])
def list_playlist_tracks(
    playlist_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist_exists = (
        db.query(Playlist.id)
        .filter(
            Playlist.id == playlist_id,
            Playlist.owner_id == current_user.id,
        )
        .first()
    )
    if not playlist_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    likes_subquery, comments_subquery = get_track_count_subqueries(db)

    rows = (
        db.query(
            Track,
            func.coalesce(likes_subquery.c.likes_count, 0).label("likes_count"),
            func.coalesce(comments_subquery.c.comments_count, 0).label("comments_count"),
        )
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
        .outerjoin(likes_subquery, likes_subquery.c.track_id == Track.id)
        .outerjoin(comments_subquery, comments_subquery.c.track_id == Track.id)
        .filter(
            PlaylistTrack.playlist_id == playlist_id,
            Track.is_deleted == False,  # noqa: E712
        )
        .order_by(PlaylistTrack.created_at.desc())
        .all()
    )

    return track_rows_to_out(rows)


@router.delete("/{playlist_id}/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_track_from_playlist(
    playlist_id: int,
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist_exists = (
        db.query(Playlist.id)
        .filter(
            Playlist.id == playlist_id,
            Playlist.owner_id == current_user.id,
        )
        .first()
    )
    if not playlist_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    link = (
        db.query(PlaylistTrack)
        .filter(
            PlaylistTrack.playlist_id == playlist_id,
            PlaylistTrack.track_id == track_id,
        )
        .first()
    )
    if link:
        db.delete(link)
        db.commit()

    return None


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_playlist(
    playlist_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist = (
        db.query(Playlist)
        .filter(
            Playlist.id == playlist_id,
            Playlist.owner_id == current_user.id,
        )
        .first()
    )
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    db.delete(playlist)
    db.commit()

    return None
