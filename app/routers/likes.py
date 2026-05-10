from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Like, Track, User
from app.security import get_current_user

router = APIRouter(prefix="/api/tracks", tags=["likes"])


def count_track_likes(db: Session, track_id: int) -> int:
    return (
        db.query(func.count(Like.id))
        .filter(Like.track_id == track_id)
        .scalar()
        or 0
    )


@router.post("/{track_id}/like", status_code=status.HTTP_200_OK)
def toggle_like_track(
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track_exists = (
        db.query(Track.id)
        .filter(
            Track.id == track_id,
            Track.is_deleted == False,  # noqa: E712
        )
        .first()
    )

    if not track_exists:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    existing_like = (
        db.query(Like)
        .filter(
            Like.user_id == current_user.id,
            Like.track_id == track_id,
        )
        .first()
    )

    if existing_like:
        db.delete(existing_like)
        db.commit()
        return {
            "message": "Track unliked",
            "liked": False,
            "likes_count": count_track_likes(db, track_id),
        }

    like = Like(
        user_id=current_user.id,
        track_id=track_id,
    )

    db.add(like)
    db.commit()

    return {
        "message": "Track liked",
        "liked": True,
        "likes_count": count_track_likes(db, track_id),
    }


@router.delete("/{track_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def unlike_track(
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    like = (
        db.query(Like)
        .filter(
            Like.user_id == current_user.id,
            Like.track_id == track_id,
        )
        .first()
    )

    if like:
        db.delete(like)
        db.commit()

    return None
