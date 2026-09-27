from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: str


class UserLogin(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    id: int
    username: str
    display_name: str
    avatar: str | None = None
    bio: str | None = None
    profile_color: str | None = None
    status: str | None = None
    banner: str | None = None
    is_online: bool

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    bio: str | None = None
    profile_color: str | None = None
    status: str | None = None


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class MessageOut(BaseModel):
    id: int
    content: str
    created_at: datetime
    user: UserOut

    class Config:
        from_attributes = True


class DirectMessageOut(BaseModel):
    id: int
    content: str
    created_at: datetime
    sender: UserOut

    class Config:
        from_attributes = True


class RoomOut(BaseModel):
    id: int
    name: str
    created_at: datetime
    member_count: int = 0
    members: list[UserOut] = []

    class Config:
        from_attributes = True


class RoomCreate(BaseModel):
    name: str


class MemberAdd(BaseModel):
    username: str
