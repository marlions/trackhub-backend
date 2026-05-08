from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Like, Track, User
from app.security import get_current_user

router = APIRouter(prefix="/api/tracks", tags=["likes"])


@router.post("/{track_id}/like", status_code=status.HTTP_201_CREATED)
def like_track(
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(Track).filter(Track.id == track_id, Track.is_deleted == False).first()  # noqa: E712
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    existing = db.query(Like).filter(Like.user_id == current_user.id, Like.track_id == track_id).first()
    if existing:
        return {"message": "Track is already liked"}

    like = Like(user_id=current_user.id, track_id=track_id)
    db.add(like)
    db.commit()
    return {"message": "Track liked"}


@router.delete("/{track_id}/like", status_code=status.HTTP_204_NO_CONTENT)
def unlike_track(
    track_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    like = db.query(Like).filter(Like.user_id == current_user.id, Like.track_id == track_id).first()
    if like:
        db.delete(like)
        db.commit()
    return None
