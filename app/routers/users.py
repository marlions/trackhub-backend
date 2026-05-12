from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import exists, func, or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Follow, User
from app.schemas import FollowOut, FollowStatusOut, UserPublicOut
from app.security import get_current_user

router = APIRouter(
    prefix="/api/users",
    tags=["users"],
)


def to_user_public_out(user: User, is_following: bool) -> UserPublicOut:
    return UserPublicOut(
        id=user.id,
        username=user.username,
        is_following=is_following,
        followers_count=user.followers_count,
        following_count=user.following_count,
    )


@router.get("/search", response_model=list[UserPublicOut])
def search_users(
    query: str = Query("", min_length=0),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    normalized_query = query.strip().lower()

    is_following_expr = exists().where(
        Follow.follower_id == current_user.id,
        Follow.following_id == User.id,
    )

    users_query = db.query(User, is_following_expr.label("is_following"))

    if normalized_query:
        pattern = f"%{normalized_query}%"
        users_query = users_query.filter(
            or_(
                func.lower(User.username).like(pattern),
                func.lower(User.email).like(pattern),
            )
        )

    rows = (
        users_query
        .filter(User.id != current_user.id)
        .order_by(User.username.asc(), User.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [to_user_public_out(user, bool(is_following)) for user, is_following in rows]


@router.get("/me/following", response_model=list[FollowOut])
def get_my_following(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Follow, User)
        .join(User, Follow.following_id == User.id)
        .filter(Follow.follower_id == current_user.id)
        .order_by(Follow.created_at.desc(), Follow.id.desc())
        .offset(offset)
        .limit(limit)
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
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(Follow, User)
        .join(User, Follow.follower_id == User.id)
        .filter(Follow.following_id == current_user.id)
        .order_by(Follow.created_at.desc(), Follow.id.desc())
        .offset(offset)
        .limit(limit)
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
    row = (
        db.query(
            User,
            exists().where(
                Follow.follower_id == current_user.id,
                Follow.following_id == User.id,
            ).label("is_following"),
        )
        .filter(User.id == user_id)
        .first()
    )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    user, is_following = row
    return to_user_public_out(user, bool(is_following))


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
        follow = Follow(follower_id=current_user.id, following_id=user_id)
        db.add(follow)
        target_user.followers_count += 1
        current_user.following_count += 1
        db.commit()

    return FollowStatusOut(
        user_id=user_id,
        is_following=True,
        followers_count=target_user.followers_count,
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
        target_user.followers_count = max(0, target_user.followers_count - 1)
        current_user.following_count = max(0, current_user.following_count - 1)
        db.commit()

    return FollowStatusOut(
        user_id=user_id,
        is_following=False,
        followers_count=target_user.followers_count,
    )
