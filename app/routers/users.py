from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Follow, User
from app.schemas import FollowOut, FollowStatusOut, UserPublicOut
from app.security import get_current_user

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
)


def get_followers_count(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(Follow.id))
        .filter(Follow.following_id == user_id)
        .scalar()
        or 0
    )


def get_following_count(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(Follow.id))
        .filter(Follow.follower_id == user_id)
        .scalar()
        or 0
    )


def is_user_following(db: Session, follower_id: int, following_id: int) -> bool:
    return (
        db.query(Follow)
        .filter(
            Follow.follower_id == follower_id,
            Follow.following_id == following_id,
        )
        .first()
        is not None
    )


def to_user_public_out(
    user: User,
    db: Session,
    current_user_id: int,
) -> UserPublicOut:
    return UserPublicOut(
        id=user.id,
        username=user.username,
        is_following=is_user_following(
            db=db,
            follower_id=current_user_id,
            following_id=user.id,
        ),
        followers_count=get_followers_count(db, user.id),
        following_count=get_following_count(db, user.id),
    )


@router.get("/search", response_model=list[UserPublicOut])
def search_users(
    query: str = Query("", min_length=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    normalized_query = query.strip()

    users_query = db.query(User)

    if normalized_query:
        users_query = users_query.filter(
            or_(
                User.username.ilike(f"%{normalized_query}%"),
                User.email.ilike(f"%{normalized_query}%"),
            )
        )

    users = (
        users_query
        .filter(User.id != current_user.id)
        .order_by(User.username.asc())
        .limit(30)
        .all()
    )

    return [
        to_user_public_out(
            user=user,
            db=db,
            current_user_id=current_user.id,
        )
        for user in users
    ]


@router.get("/me/following", response_model=list[FollowOut])
def get_my_following(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Follow, User)
        .join(User, Follow.following_id == User.id)
        .filter(Follow.follower_id == current_user.id)
        .order_by(Follow.created_at.desc())
        .all()
    )

    return [
        FollowOut(
            id=user.id,
            username=user.username,
            followed_at=follow.created_at,
        )
        for follow, user in rows
    ]


@router.get("/me/followers", response_model=list[FollowOut])
def get_my_followers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Follow, User)
        .join(User, Follow.follower_id == User.id)
        .filter(Follow.following_id == current_user.id)
        .order_by(Follow.created_at.desc())
        .all()
    )

    return [
        FollowOut(
            id=user.id,
            username=user.username,
            followed_at=follow.created_at,
        )
        for follow, user in rows
    ]


@router.get("/{user_id}", response_model=UserPublicOut)
def get_user_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = db.query(User).filter(User.id == user_id).first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    return to_user_public_out(
        user=user,
        db=db,
        current_user_id=current_user.id,
    )


@router.post("/{user_id}/follow", response_model=FollowStatusOut)
def follow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нельзя подписаться на самого себя",
        )

    target_user = db.query(User).filter(User.id == user_id).first()

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    existing_follow = (
        db.query(Follow)
        .filter(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id,
        )
        .first()
    )

    if existing_follow is None:
        follow = Follow(
            follower_id=current_user.id,
            following_id=user_id,
        )

        db.add(follow)
        db.commit()

    return FollowStatusOut(
        user_id=user_id,
        is_following=True,
        followers_count=get_followers_count(db, user_id),
    )


@router.delete("/{user_id}/follow", response_model=FollowStatusOut)
def unfollow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_user = db.query(User).filter(User.id == user_id).first()

    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    existing_follow = (
        db.query(Follow)
        .filter(
            Follow.follower_id == current_user.id,
            Follow.following_id == user_id,
        )
        .first()
    )

    if existing_follow is not None:
        db.delete(existing_follow)
        db.commit()

    return FollowStatusOut(
        user_id=user_id,
        is_following=False,
        followers_count=get_followers_count(db, user_id),
    )
