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


def followers_count_query(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(Follow.id))
        .filter(Follow.following_id == user_id)
        .scalar()
        or 0
    )


# Backward-compatible names.
def get_followers_count(db: Session, user_id: int) -> int:
    return followers_count_query(db, user_id)


def get_following_count(db: Session, user_id: int) -> int:
    return (
        db.query(func.count(Follow.id))
        .filter(Follow.follower_id == user_id)
        .scalar()
        or 0
    )


def is_user_following(db: Session, follower_id: int, following_id: int) -> bool:
    return (
        db.query(Follow.id)
        .filter(
            Follow.follower_id == follower_id,
            Follow.following_id == following_id,
        )
        .first()
        is not None
    )


def user_public_subqueries(db: Session, current_user_id: int):
    followers_subquery = (
        db.query(
            Follow.following_id.label("user_id"),
            func.count(Follow.id).label("followers_count"),
        )
        .group_by(Follow.following_id)
        .subquery()
    )

    following_subquery = (
        db.query(
            Follow.follower_id.label("user_id"),
            func.count(Follow.id).label("following_count"),
        )
        .group_by(Follow.follower_id)
        .subquery()
    )

    current_user_following_subquery = (
        db.query(Follow.following_id.label("user_id"))
        .filter(Follow.follower_id == current_user_id)
        .subquery()
    )

    return followers_subquery, following_subquery, current_user_following_subquery


def user_public_query(db: Session, current_user_id: int):
    followers_subquery, following_subquery, current_user_following_subquery = user_public_subqueries(
        db=db,
        current_user_id=current_user_id,
    )

    return (
        db.query(
            User,
            (current_user_following_subquery.c.user_id.isnot(None)).label("is_following"),
            func.coalesce(followers_subquery.c.followers_count, 0).label("followers_count"),
            func.coalesce(following_subquery.c.following_count, 0).label("following_count"),
        )
        .outerjoin(followers_subquery, followers_subquery.c.user_id == User.id)
        .outerjoin(following_subquery, following_subquery.c.user_id == User.id)
        .outerjoin(current_user_following_subquery, current_user_following_subquery.c.user_id == User.id)
    )


def user_public_row_to_out(
    user: User,
    is_following: bool | None,
    followers_count: int | None,
    following_count: int | None,
) -> UserPublicOut:
    return UserPublicOut(
        id=user.id,
        username=user.username,
        is_following=bool(is_following),
        followers_count=int(followers_count or 0),
        following_count=int(following_count or 0),
    )


# Backward-compatible name for old code/tests.
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
    normalized_query = query.strip().lower()

    users_query = user_public_query(db, current_user.id).filter(User.id != current_user.id)

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
        .order_by(User.username.asc())
        .limit(30)
        .all()
    )

    return [
        user_public_row_to_out(
            user=user,
            is_following=is_following,
            followers_count=followers_count,
            following_count=following_count,
        )
        for user, is_following, followers_count, following_count in rows
    ]


@router.get("/me/following", response_model=list[FollowOut])
def get_my_following(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(User.id, User.username, Follow.created_at)
        .join(Follow, Follow.following_id == User.id)
        .filter(Follow.follower_id == current_user.id)
        .order_by(Follow.created_at.desc())
        .all()
    )

    return [
        FollowOut(
            id=user_id,
            username=username,
            followed_at=followed_at,
        )
        for user_id, username, followed_at in rows
    ]


@router.get("/me/followers", response_model=list[FollowOut])
def get_my_followers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(User.id, User.username, Follow.created_at)
        .join(Follow, Follow.follower_id == User.id)
        .filter(Follow.following_id == current_user.id)
        .order_by(Follow.created_at.desc())
        .all()
    )

    return [
        FollowOut(
            id=user_id,
            username=username,
            followed_at=followed_at,
        )
        for user_id, username, followed_at in rows
    ]


@router.get("/{user_id}", response_model=UserPublicOut)
def get_user_profile(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    row = (
        user_public_query(db, current_user.id)
        .filter(User.id == user_id)
        .first()
    )

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    user, is_following, followers_count, following_count = row
    return user_public_row_to_out(user, is_following, followers_count, following_count)


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

    target_user_exists = db.query(User.id).filter(User.id == user_id).first()

    if target_user_exists is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )

    existing_follow = (
        db.query(Follow.id)
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
        followers_count=followers_count_query(db, user_id),
    )


@router.delete("/{user_id}/follow", response_model=FollowStatusOut)
def unfollow_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_user_exists = db.query(User.id).filter(User.id == user_id).first()

    if target_user_exists is None:
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
        followers_count=followers_count_query(db, user_id),
    )
