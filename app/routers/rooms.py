from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import Message, Room, User
from ..ws_media import room_members
from ..schemas import MemberAdd, MessageOut, RoomCreate, RoomOut

router = APIRouter(prefix="/rooms", tags=["rooms"])


def _user_ids(room: Room) -> list[int]:
    return [m.id for m in room.members]


@router.get("", response_model=list[RoomOut])
def list_rooms(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rooms = db.query(Room).all()
    return [_to_out(r) for r in rooms]


def _to_out(room: Room):
    out = RoomOut(
        id=room.id,
        name=room.name,
        created_at=room.created_at,
        members=[m for m in room.members],
    )
    out.member_count = len(room.members)
    return out


@router.post("", response_model=RoomOut)
def create_room(payload: RoomCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room = Room(name=payload.name, created_by=user.id)
    room.members.append(user)
    db.add(room)
    db.commit()
    db.refresh(room)
    room_members.invalidate(room.id)
    return _to_out(room)


@router.get("/{room_id}/messages", response_model=list[MessageOut])
def room_messages(room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    if user.id not in _user_ids(room):
        raise HTTPException(403, "Not a member")
    return db.query(Message).filter(Message.room_id == room_id).order_by(Message.id.asc()).all()


@router.post("/{room_id}/join", response_model=RoomOut)
def join_room(room_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    if user not in room.members:
        room.members.append(user)
        db.commit()
    db.refresh(room)
    room_members.invalidate(room.id)
    return _to_out(room)


@router.post("/{room_id}/members", response_model=RoomOut)
def add_member(room_id: int, payload: MemberAdd, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    room = db.get(Room, room_id)
    if not room:
        raise HTTPException(404, "Room not found")
    if user.id not in _user_ids(room):
        raise HTTPException(403, "Not a member")
    target = db.query(User).filter(User.username == payload.username).first()
    if not target:
        raise HTTPException(404, "User not found")
    if target not in room.members:
        room.members.append(target)
        db.commit()
    db.refresh(room)
    room_members.invalidate(room.id)
    return _to_out(room)
