"""Nekochat Admin — панель управления сервером (URL: /admin).

Вход — по хэшу, который сервер печатает в консоль при старте процесса.
Хэш генерируется заново при каждом перезапуске; вместе с ним автоматически
сбрасываются и все открытые админ-сессии (подпись сессии зависит от хэша).

Возможности: статистика, пользователи (бан/разбан, редактирование, сброс
пароля, полное удаление с каскадом), сообщения (просмотр/удаление), комнаты.
"""
import hashlib
import hmac
import re
import secrets
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from .database import get_db
from .models import DirectConversation, DirectMessage, Message, Room, User, room_members
from .security import hash_password
from .ws_manager import manager

router = APIRouter(prefix="/admin", tags=["admin"])

# Новый хэш на каждый старт процесса — сброс при перезапуске сервера.
_admin_hash = secrets.token_urlsafe(24)


def _log(msg: str) -> None:
    """Печать в консоль, устойчивая к кириллице на Windows (cp1252)."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        safe = msg.encode("utf-8", "replace").decode("ascii", "replace")
        print(safe, flush=True)


_log(
    "\n==============================================\n"
    "  NEKOCHAT ADMIN PANEL\n"
    f"  URL : http://<server>/admin\n"
    f"  HASH: {_admin_hash}\n"
    "  (hash is valid until the server restarts)\n"
    "==============================================\n"
)

_COOKIE = "neko_admin"


def _session_token() -> str:
    nonce = secrets.token_hex(8)
    sig = hmac.new(
        _admin_hash.encode(),
        f"nonce:{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{nonce}.{sig}"


def _check_session(token: str | None) -> bool:
    if not token:
        return False
    try:
        nonce, sig = token.split(".", 1)
    except ValueError:
        return False
    expected = hmac.new(
        _admin_hash.encode(),
        f"nonce:{nonce}".encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(sig, expected)


def require_admin(request: Request) -> None:
    """FastAPI-зависимость: любой роут с ней требует админ-сессию."""
    if not _check_session(request.cookies.get(_COOKIE)):
        raise HTTPException(401, "Нужна админ-сессия")


def _admin_html() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app" / "static" / "admin.html"
    return Path(__file__).resolve().parent / "static" / "admin.html"


def _user_view(u: User) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "avatar": u.avatar,
        "bio": u.bio,
        "profile_color": u.profile_color,
        "status": u.status,
        "banner": u.banner,
        "is_online": u.is_online,
        "is_banned": bool(getattr(u, "is_banned", False)),
        "created_at": u.created_at.isoformat() if u.created_at else None,
    }


async def _kick(user_id: int) -> None:
    """Разрывает все WebSocket-соединения пользователя (обрывает и звонки)."""
    for ws in list(manager.active.get(user_id, set())):
        try:
            await ws.close(code=4403)
        except Exception:
            pass


# ----------------------------------------------------------------------------
# Сессия и страница
# ----------------------------------------------------------------------------

class LoginIn(BaseModel):
    hash: str


@router.get("")
def panel():
    return FileResponse(
        _admin_html(),
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@router.post("/login")
def login(payload: LoginIn, request: Request, response: Response):
    ok = hmac.compare_digest(payload.hash.strip(), _admin_hash)
    ip = request.client.host if request.client else "?"
    _log(f"[admin] login {ip} -> {'OK' if ok else 'FAIL'}")
    if not ok:
        raise HTTPException(401, "Неверный хэш")
    response.set_cookie(
        _COOKIE,
        _session_token(),
        httponly=True,
        samesite="lax",
        path="/admin",
        max_age=7 * 24 * 3600,
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(_COOKIE, path="/admin")
    return {"ok": True}


@router.get("/auth")
def auth_status(request: Request):
    return {"ok": _check_session(request.cookies.get(_COOKIE))}


# ----------------------------------------------------------------------------
# Статистика
# ----------------------------------------------------------------------------

@router.get("/stats")
def stats(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    return {
        "users": db.query(func.count(User.id)).scalar() or 0,
        "online": db.query(func.count(User.id)).filter(User.is_online.is_(True)).scalar() or 0,
        "banned": db.query(func.count(User.id)).filter(User.is_banned.is_(True)).scalar() or 0,
        "rooms": db.query(func.count(Room.id)).scalar() or 0,
        "room_messages": db.query(func.count(Message.id)).scalar() or 0,
        "direct_messages": db.query(func.count(DirectMessage.id)).scalar() or 0,
        "ws_connections": sum(len(s) for s in manager.active.values()),
        "admin_hash_ok": True,
    }


# ----------------------------------------------------------------------------
# Пользователи
# ----------------------------------------------------------------------------

@router.get("/users")
def list_users(q: str = "", db: Session = Depends(get_db), _: None = Depends(require_admin)):
    query = db.query(User)
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(User.username.ilike(like) | User.display_name.ilike(like))
    users = query.order_by(User.id.desc()).limit(500).all()

    room_counts = {
        uid: n for uid, n in
        db.query(Message.user_id, func.count(Message.id)).group_by(Message.user_id).all()
    }
    direct_counts = {
        uid: n for uid, n in
        db.query(DirectMessage.sender_id, func.count(DirectMessage.id)).group_by(DirectMessage.sender_id).all()
    }
    membership_counts = {
        uid: n for uid, n in
        db.query(room_members.c.user_id, func.count(room_members.c.room_id)).group_by(room_members.c.user_id).all()
    }

    result = []
    for u in users:
        v = _user_view(u)
        v["stats"] = {
            "room_messages": room_counts.get(u.id, 0),
            "direct_messages": direct_counts.get(u.id, 0),
            "rooms": membership_counts.get(u.id, 0),
        }
        result.append(v)
    return result


@router.get("/users/{user_id}")
def user_detail(user_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    v = _user_view(u)
    v["rooms"] = [
        {"id": r.id, "name": r.name, "member_count": len(r.members)}
        for r in db.query(Room)
        .join(room_members, room_members.c.room_id == Room.id)
        .filter(room_members.c.user_id == user_id)
        .all()
    ]
    return v


@router.post("/users/{user_id}/ban")
async def ban_user(user_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    u.is_banned = True
    db.commit()
    await _kick(user_id)
    _log(f"[admin] user {user_id} banned")
    return {"ok": True, "id": user_id}


@router.post("/users/{user_id}/unban")
def unban_user(user_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    u.is_banned = False
    db.commit()
    _log(f"[admin] user {user_id} unbanned")
    return {"ok": True, "id": user_id}


class AdminEditIn(BaseModel):
    display_name: str | None = None
    bio: str | None = None
    status: str | None = None
    profile_color: str | None = None


@router.post("/users/{user_id}/edit")
def edit_user(
    user_id: int,
    payload: AdminEditIn,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    if payload.display_name is not None:
        u.display_name = payload.display_name.strip()[:100] or u.username
    if payload.bio is not None:
        u.bio = payload.bio.strip() or None
    if payload.status is not None:
        u.status = payload.status.strip()[:100] or None
    if payload.profile_color is not None:
        c = payload.profile_color.strip()
        if c and not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
            raise HTTPException(400, "Цвет должен быть #RRGGBB")
        u.profile_color = c or None
    db.commit()
    return {"ok": True, "user": _user_view(u)}


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    temp = secrets.token_urlsafe(9)
    u.password_hash = hash_password(temp)
    db.commit()
    _log(f"[admin] user {user_id} password reset")
    return {"ok": True, "temp_password": temp}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "Пользователь не найден")
    await _kick(user_id)
    convs = (
        db.query(DirectConversation)
        .filter(
            (DirectConversation.user_a_id == user_id) | (DirectConversation.user_b_id == user_id)
        )
        .all()
    )
    for c in convs:
        db.delete(c)  # cascade удаляет direct_messages
    db.execute(room_members.delete().where(room_members.c.user_id == user_id))
    db.query(Message).filter(Message.user_id == user_id).delete(synchronize_session=False)
    # комнаты, созданные этим пользователем:
    # пустые — удалить (cascade удалит room messages);
    # живые (есть другие участники) — отвязать создателя, иначе Postgres
    # блокирует удаление юзера внешним ключом rooms.created_by.
    for r in db.query(Room).filter(Room.created_by == user_id).all():
        if not r.members:
            db.delete(r)
        else:
            r.created_by = None
    db.delete(u)
    db.commit()
    _log(f"[admin] user {user_id} deleted")
    return {"ok": True, "deleted_user_id": user_id}


# ----------------------------------------------------------------------------
# Сообщения
# ----------------------------------------------------------------------------

def _msg_out(m: Message, users: dict[int, dict]) -> dict:
    return {
        "id": m.id,
        "room_id": m.room_id,
        "user_id": m.user_id,
        "content": (m.content or "")[:500],
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "user": users.get(m.user_id),
    }


def _dmsg_out(m: DirectMessage, users: dict[int, dict]) -> dict:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "sender_id": m.sender_id,
        "content": (m.content or "")[:500],
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "user": users.get(m.sender_id),
    }


@router.get("/messages")
def list_messages(
    user_id: int | None = None,
    room_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    q = db.query(Message)
    if user_id:
        q = q.filter(Message.user_id == user_id)
    if room_id:
        q = q.filter(Message.room_id == room_id)
    rows = q.order_by(Message.id.desc()).limit(min(max(limit, 1), 500)).all()
    ids = {m.user_id for m in rows}
    users = (
        {u.id: _user_view(u) for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    )
    return [_msg_out(m, users) for m in rows]


@router.get("/direct-messages")
def list_direct_messages(
    user_id: int | None = None,
    conversation_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    _: None = Depends(require_admin),
):
    q = db.query(DirectMessage)
    if user_id:
        q = q.filter(DirectMessage.sender_id == user_id)
    if conversation_id:
        q = q.filter(DirectMessage.conversation_id == conversation_id)
    rows = q.order_by(DirectMessage.id.desc()).limit(min(max(limit, 1), 500)).all()
    ids = {m.sender_id for m in rows}
    users = (
        {u.id: _user_view(u) for u in db.query(User).filter(User.id.in_(ids)).all()} if ids else {}
    )
    return [_dmsg_out(m, users) for m in rows]


@router.delete("/messages/{message_id}")
def delete_message(message_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    m = db.get(Message, message_id)
    if not m:
        raise HTTPException(404, "Сообщение не найдено")
    db.delete(m)
    db.commit()
    return {"ok": True}


@router.delete("/direct-messages/{message_id}")
def delete_direct_message(message_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    m = db.get(DirectMessage, message_id)
    if not m:
        raise HTTPException(404, "Сообщение не найдено")
    db.delete(m)
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------------------------
# Комнаты
# ----------------------------------------------------------------------------

@router.get("/rooms")
def list_rooms(db: Session = Depends(get_db), _: None = Depends(require_admin)):
    rooms = db.query(Room).order_by(Room.id.desc()).limit(500).all()
    msg_counts = {
        rid: n for rid, n in
        db.query(Message.room_id, func.count(Message.id)).group_by(Message.room_id).all()
    }
    result = []
    for r in rooms:
        result.append(
            {
                "id": r.id,
                "name": r.name,
                "created_by": r.created_by,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "member_count": len(r.members),
                "message_count": msg_counts.get(r.id, 0),
            }
        )
    return result


@router.get("/rooms/{room_id}")
def room_detail(room_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    r = db.get(Room, room_id)
    if not r:
        raise HTTPException(404, "Комната не найдена")
    return {
        "id": r.id,
        "name": r.name,
        "created_by": r.created_by,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "members": [_user_view(m) for m in r.members],
        "message_count": db.query(func.count(Message.id)).filter(Message.room_id == room_id).scalar() or 0,
    }


@router.delete("/rooms/{room_id}")
def delete_room(room_id: int, db: Session = Depends(get_db), _: None = Depends(require_admin)):
    r = db.get(Room, room_id)
    if not r:
        raise HTTPException(404, "Комната не найдена")
    db.delete(r)  # cascade удаляет сообщения и memberships
    db.commit()
    _log(f"[admin] room {room_id} deleted")
    return {"ok": True}