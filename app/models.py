from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .database import Base

room_members = Table(
    "room_members",
    Base.metadata,
    Column("room_id", Integer, ForeignKey("rooms.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=False)
    avatar = Column(String(255), nullable=True)
    bio = Column(Text, nullable=True)
    profile_color = Column(String(9), nullable=True)
    status = Column(String(100), nullable=True)
    banner = Column(String(255), nullable=True)
    is_online = Column(Boolean, default=False)
    is_banned = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    rooms = relationship("Room", secondary=room_members, back_populates="members")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    created_by = Column(Integer, ForeignKey("users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    members = relationship("User", secondary=room_members, back_populates="rooms")
    messages = relationship("Message", back_populates="room", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    room = relationship("Room", back_populates="messages")
    user = relationship("User")


class DirectConversation(Base):
    __tablename__ = "direct_conversations"
    __table_args__ = (UniqueConstraint("user_a_id", "user_b_id", name="uq_direct_pair"),)

    id = Column(Integer, primary_key=True, index=True)
    user_a_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    user_b_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ensure a < b for uniqueness
    def __init__(self, user_a_id, user_b_id, **kwargs):
        lower, higher = sorted([user_a_id, user_b_id])
        super().__init__(user_a_id=lower, user_b_id=higher, **kwargs)

    messages = relationship("DirectMessage", back_populates="conversation", cascade="all, delete-orphan")
    user_a = relationship("User", foreign_keys=[user_a_id])
    user_b = relationship("User", foreign_keys=[user_b_id])


class DirectMessage(Base):
    __tablename__ = "direct_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("direct_conversations.id"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("DirectConversation", back_populates="messages")
    sender = relationship("User")
