from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import exists, literal
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Like, Playlist, PlaylistTrack, Track, User
from app.schemas import PlaylistCreate, PlaylistOut
from app.security import get_current_user
from app.routers.tracks import track_to_out

router = APIRouter(prefix="/api/playlists", tags=["playlists"])
MAX_TRACKS_PER_PLAYLIST = 100


def to_playlist_out(playlist: Playlist) -> PlaylistOut:
    return PlaylistOut(
        id=playlist.id,
        name=playlist.name,
        owner_id=playlist.owner_id,
        created_at=playlist.created_at,
        tracks_count=playlist.tracks_count,
    )


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
    return to_playlist_out(playlist)


@router.get("", response_model=list[PlaylistOut])
def list_my_playlists(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlists = (
        db.query(Playlist)
        .filter(Playlist.owner_id == current_user.id)
        .order_by(Playlist.created_at.desc(), Playlist.id.desc())
        .all()
    )
    return [to_playlist_out(playlist) for playlist in playlists]


@router.post("/{playlist_id}/tracks/{track_id}", status_code=status.HTTP_201_CREATED)
def add_track_to_playlist(
    playlist_id: int,
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.owner_id == current_user.id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    track = db.query(Track).filter(Track.id == track_id, Track.is_deleted == False).first()  # noqa: E712
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    existing = db.query(PlaylistTrack).filter(
        PlaylistTrack.playlist_id == playlist_id,
        PlaylistTrack.track_id == track_id,
    ).first()
    if existing:
        return {"message": "Track is already in playlist", "tracks_count": playlist.tracks_count}

    if playlist.tracks_count >= MAX_TRACKS_PER_PLAYLIST:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В плейлист нельзя добавить больше 100 треков",
        )

    link = PlaylistTrack(playlist_id=playlist_id, track_id=track_id)
    db.add(link)
    playlist.tracks_count += 1
    db.commit()

    return {"message": "Track added to playlist", "tracks_count": playlist.tracks_count}


@router.get("/{playlist_id}/tracks")
def list_playlist_tracks(
    playlist_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.owner_id == current_user.id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    is_liked_expr = exists().where(
        Like.user_id == current_user.id,
        Like.track_id == Track.id,
    )

    rows = (
        db.query(Track, is_liked_expr.label("is_liked"))
        .join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
        .filter(
            PlaylistTrack.playlist_id == playlist_id,
            Track.is_deleted == False,  # noqa: E712
        )
        .order_by(PlaylistTrack.created_at.desc(), PlaylistTrack.id.desc())
        .all()
    )

    return [track_to_out(track, bool(is_liked)) for track, is_liked in rows]


@router.delete("/{playlist_id}/tracks/{track_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_track_from_playlist(
    playlist_id: int,
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.owner_id == current_user.id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    link = db.query(PlaylistTrack).filter(
        PlaylistTrack.playlist_id == playlist_id,
        PlaylistTrack.track_id == track_id,
    ).first()
    if link:
        db.delete(link)
        playlist.tracks_count = max(0, playlist.tracks_count - 1)
        db.commit()
    return None


@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_playlist(
    playlist_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    playlist = db.query(Playlist).filter(Playlist.id == playlist_id, Playlist.owner_id == current_user.id).first()
    if not playlist:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Playlist not found")

    db.delete(playlist)
    db.commit()
    return None
