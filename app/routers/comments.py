from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Comment, Track, User
from app.schemas import CommentCreate, CommentOut
from app.security import get_current_user

router = APIRouter(prefix="/api/tracks", tags=["comments"])


@router.post("/{track_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def create_comment(
    track_id: int,
    payload: CommentCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    track = db.query(Track).filter(Track.id == track_id, Track.is_deleted == False).first()  # noqa: E712
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    comment = Comment(user_id=current_user.id, track_id=track_id, text=payload.text.strip())
    db.add(comment)
    db.commit()
    db.refresh(comment)

    return CommentOut(
        id=comment.id,
        user_id=comment.user_id,
        track_id=comment.track_id,
        text=comment.text,
        created_at=comment.created_at,
        username=current_user.username,
    )


@router.get("/{track_id}/comments", response_model=list[CommentOut])
def list_comments(track_id: int, db: Session = Depends(get_db)):
    track = db.query(Track).filter(Track.id == track_id, Track.is_deleted == False).first()  # noqa: E712
    if not track:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    comments = (
        db.query(Comment)
        .filter(Comment.track_id == track_id)
        .order_by(Comment.created_at.desc())
        .all()
    )
    return [
        CommentOut(
            id=comment.id,
            user_id=comment.user_id,
            track_id=comment.track_id,
            text=comment.text,
            created_at=comment.created_at,
            username=comment.user.username,
        )
        for comment in comments
    ]
