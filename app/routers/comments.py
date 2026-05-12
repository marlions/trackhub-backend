from fastapi import APIRouter, Depends, HTTPException, Query, status
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
    track.comments_count += 1
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
def list_comments(
    track_id: int,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    track_exists = db.query(Track.id).filter(Track.id == track_id, Track.is_deleted == False).first()  # noqa: E712
    if not track_exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Track not found")

    rows = (
        db.query(Comment, User.username)
        .join(User, Comment.user_id == User.id)
        .filter(Comment.track_id == track_id)
        .order_by(Comment.created_at.desc(), Comment.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        CommentOut(
            id=comment.id,
            user_id=comment.user_id,
            track_id=comment.track_id,
            text=comment.text,
            created_at=comment.created_at,
            username=username,
        )
        for comment, username in rows
    ]
