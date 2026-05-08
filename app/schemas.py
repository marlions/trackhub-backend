from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    created_at: datetime

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class TrackOut(BaseModel):
    id: int
    title: str
    author: str
    original_filename: str
    content_type: str
    file_size_bytes: int
    play_count: int
    uploaded_by_id: int
    created_at: datetime
    stream_url: str
    likes_count: int = 0
    comments_count: int = 0

    class Config:
        from_attributes = True


class CommentCreate(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class CommentOut(BaseModel):
    id: int
    user_id: int
    track_id: int
    text: str
    created_at: datetime
    username: str


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class PlaylistOut(BaseModel):
    id: int
    name: str
    owner_id: int
    created_at: datetime
    tracks_count: int = 0

    class Config:
        from_attributes = True
