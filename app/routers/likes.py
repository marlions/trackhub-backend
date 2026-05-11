from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Like, Track, User
from app.security import get_current_user

router = APIRouter(prefix="/api/tracks", tags=["likes"])


def like_status_response(track_id: int, liked: bool, likes_count: int) -> dict:
    return {
        "track_id": track_id,
        "liked": liked,
        "likes_count": max(0, likes_count),
    }


@router.post("/{track_id}/like", status_code=status.HTTP_200_OK)
def toggle_like_track(
    track_id: int,
    current_user: User = Depends(get_current_user),
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

    existing_like = db.query(Like).filter(
        Like.user_id == current_user.id,
        Like.track_id == track_id,
    ).first()

    if existing_like:
        db.delete(existing_like)
        track.likes_count = max(0, track.likes_count - 1)
        db.commit()
        return like_status_response(track_id, False, track.likes_count)

    like = Like(user_id=current_user.id, track_id=track_id)
    db.add(like)
    track.likes_count += 1
    db.commit()

    return like_status_response(track_id, True, track.likes_count)


@router.delete("/{track_id}/like", status_code=status.HTTP_200_OK)
def unlike_track(
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

    like = db.query(Like).filter(
        Like.user_id == current_user.id,
        Like.track_id == track_id,
    ).first()

    if like:
        db.delete(like)
        track.likes_count = max(0, track.likes_count - 1)
        db.commit()

    return like_status_response(track_id, False, track.likes_count)
