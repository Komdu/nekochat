import secrets

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import DirectConversation, DirectMessage, User
from ..schemas import DirectMessageOut, PasswordChange, ProfileUpdate, UserOut
from ..security import hash_password, verify_password

router = APIRouter(prefix="/users", tags=["users"])

ALLOWED_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


# Сигнатуры файлов. Заголовок Content-Type приходит от клиента и ничего не
# значит: мусор можно пометить как image/png, и сервер обязан это отсечь сам.
_MAGIC = {
    b"\x89PNG\r\n\x1a\n": "png",
    b"\xff\xd8\xff": "jpg",
    b"GIF87a": "gif",
    b"GIF89a": "gif",
}


def _sniff_image(data: bytes) -> str | None:
    """Формат по первым байтам, а не по заявленному Content-Type."""
    for magic, ext in _MAGIC.items():
        if data.startswith(magic):
            return ext
    # WebP: "RIFF" .... "WEBP" на 8-м байте
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


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
    # Сверяем заявленный тип с настоящим: иначе под видом картинки на сервер
    # можно положить что угодно и получить обратно уже с картиночным
    # Content-Type из /avatars/.
    real = _sniff_image(data)
    if real is None:
        raise HTTPException(400, "Это не картинка")
    ext = real
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
    if payload.display_name is not None:
        name = payload.display_name.strip()
        if not name:
            raise HTTPException(400, "Имя не может быть пустым")
        if len(name) > 40:
            raise HTTPException(400, "Имя длиннее 40 символов")
        # управляющие символы ломают разметку в списках и заголовках чата
        if any(ord(ch) < 32 for ch in name):
            raise HTTPException(400, "В имени нельзя использовать невидимые символы")
        user.display_name = name
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
    # Статус, имя и аватар — это присутствие: без рассылки остальные
    # продолжат видеть старое значение, пока не перезагрузят страницу.
    _broadcast_presence(user)
    return UserOut.model_validate(user)


def _broadcast_presence(user: User) -> None:
    """Сообщить всем, что у человека изменилось то, что видно рядом с ником.

    Отдельным событием, а не в общий поток сообщений: получателям не нужен
    текст, им нужен новый статус.
    """
    from ..ws_manager import manager, spawn

    payload = {
        "type": "presence_update",
        "user": {
            "id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "avatar": user.avatar,
            "bio": user.bio,
            "status": user.status,
            "profile_color": user.profile_color,
            "is_online": user.is_online,
        },
    }
    # Автору событие не нужно: он и так видит свой профиль, а лишнее событие
    # дёрнуло бы у него перерисовку списка.
    _spawn(manager.broadcast(payload, exclude={user.id}))


def _spawn(coro) -> None:
    """Отправить рассылку из синхронного эндпоинта.

    Этот обработчик FastAPI выполняет в пуле потоков, а не на event loop:
    get_running_loop() здесь падает, и рассылка молча терялась бы. Поэтому
    запуск идёт через run_coroutine_threadsafe на loop, сохранённый при старте.
    """
    from ..ws_manager import spawn

    spawn(coro)


@router.put("/me/password")
def change_password(
    payload: PasswordChange,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Смена пароля на свой.

    Старый пароль обязателен: иначе утёкший токен позволил бы захватить
    аккаунт навсегда — пароль стал бы единственным, что отличает хозяина от
    вора, а он бы уже утек.

    Новый пароль — ровно тот, что ввёл человек. Никаких генераций: смысл
    смены в том, чтобы поставить свой, известный только тебе пароль.
    """
    if not verify_password(payload.old_password, user.password_hash):
        raise HTTPException(400, "Старый пароль неверный")
    new = payload.new_password
    if len(new) < 6:
        raise HTTPException(400, "Новый пароль короче 6 символов")
    if len(new) > 256:
        raise HTTPException(400, "Новый пароль длиннее 256 символов")
    if new == payload.old_password:
        raise HTTPException(400, "Новый пароль совпадает со старым")
    user.password_hash = hash_password(new)
    db.commit()
    # Текущий токен остаётся рабочим: он подписан по sub=user.id, а не по
    # паролю, иначе смена пароля выкидывала бы из всех вкладок сразу.
    # Выданные ранее токены остаются действительными до истечения exp —
    # отзывать их сервер не умеет, это осознанный компромисс.
    return {"ok": True}


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
