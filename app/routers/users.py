import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import DirectConversation, DirectMessage, User
from ..schemas import DirectMessageOut, ProfileUpdate, UserOut

router = APIRouter(prefix="/users", tags=["users"])

ALLOWED_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


def _resize_image(data: bytes, max_side: int, quality: int = 80) -> tuple[bytes, str] | None:
    """Сжать картинку в WebP ≤ max_side. None — оставить как есть (анимированный GIF или битые данные)."""
    try:
        from io import BytesIO

        from PIL import Image, ImageOps

        im = Image.open(BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if (im.format or "").upper() == "GIF":
            return None
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        out = BytesIO()
        im.save(out, "WEBP", quality=quality, method=4)
        return out.getvalue(), "webp"
    except Exception:
        return None


@router.get("", response_model=list[UserOut])
def list_users(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(User).filter(User.id != user.id).all()


@router.post("/me/avatar", response_model=UserOut)
def upload_avatar(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from pathlib import Path

    ext = ALLOWED_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(400, "Только PNG, JPEG, WebP или GIF")
    data = file.file.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "Картинка больше 5 МБ")
    if not data:
        raise HTTPException(400, "Пустой файл")
    # аватарки живут в маленьких кружках: жмём в WebP ≤192px, чтобы картинка
    # быстро доходила даже через медленный туннель (большие PNG не грузились)
    resized = _resize_image(data, 192, 80)
    if resized is not None:
        data, ext = resized

    dir_ = Path(settings.avatars_dir)
    dir_.mkdir(parents=True, exist_ok=True)
    if user.avatar:
        old = dir_ / str(user.avatar)
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass

    name = f"{user.id}_{secrets.token_hex(4)}.{ext}"
    (dir_ / name).write_bytes(data)
    user.avatar = name
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.put("/me/profile", response_model=UserOut)
def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.bio is not None:
        user.bio = payload.bio.strip() or None
    if payload.status is not None:
        user.status = payload.status.strip()[:100] or None
    if payload.profile_color is not None:
        color = payload.profile_color.strip()
        if color and not (_is_hex_color(color)):
            raise HTTPException(400, "Цвет должен быть в формате #RRGGBB")
        user.profile_color = color or None
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/me/banner", response_model=UserOut)
def upload_banner(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from pathlib import Path

    ext = ALLOWED_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(400, "Только PNG, JPEG, WebP или GIF")
    data = file.file.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "Картинка больше 5 МБ")
    if not data:
        raise HTTPException(400, "Пустой файл")
    # баннер шире аватара, но тоже жмём в WebP
    resized = _resize_image(data, 1280, 78)
    if resized is not None:
        data, ext = resized

    dir_ = Path(settings.avatars_dir)
    dir_.mkdir(parents=True, exist_ok=True)
    if user.banner:
        old = dir_ / str(user.banner)
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass

    name = f"b_{user.id}_{secrets.token_hex(4)}.{ext}"
    (dir_ / name).write_bytes(data)
    user.banner = name
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


def _is_hex_color(value: str) -> bool:
    import re

    return re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def _get_or_create_conversation(db: Session, me_id: int, other_id: int) -> DirectConversation:
    conv = (
        db.query(DirectConversation)
        .filter(
            ((DirectConversation.user_a_id == me_id) & (DirectConversation.user_b_id == other_id))
            | ((DirectConversation.user_a_id == other_id) & (DirectConversation.user_b_id == me_id))
        )
        .first()
    )
    if conv is None:
        conv = DirectConversation(user_a_id=me_id, user_b_id=other_id)
        db.add(conv)
        db.commit()
        db.refresh(conv)
    return conv


def _other_user(conv: DirectConversation, me_id: int) -> User:
    return conv.user_a if conv.user_b_id == me_id else conv.user_b


@router.get("/{other_id}/messages", response_model=list[DirectMessageOut])
def direct_messages(
    other_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    conv = _get_or_create_conversation(db, user.id, other_id)
    return db.query(DirectMessage).filter(DirectMessage.conversation_id == conv.id).order_by(DirectMessage.id.asc()).all()


@router.get("/conversations/me", response_model=list[dict])
def my_conversations(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    convs = (
        db.query(DirectConversation)
        .filter(
            (DirectConversation.user_a_id == user.id) | (DirectConversation.user_b_id == user.id)
        )
        .order_by(DirectConversation.id.desc())
        .all()
    )
    result = []
    for conv in convs:
        other = _other_user(conv, user.id)
        result.append(
            {
                "conversation_id": conv.id,
                "user": UserOut.model_validate(other),
            }
        )
    return result
