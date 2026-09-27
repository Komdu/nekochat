import re
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import settings

router = APIRouter(prefix="/avatars", tags=["avatars"])

FILENAME_RE = re.compile(r"^[0-9a-zA-Z_.-]+$")


def avatars_path() -> Path:
    p = Path(settings.avatars_dir)
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.get("/{filename}")
def get_avatar(filename: str):
    if not FILENAME_RE.match(filename) or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = avatars_path() / filename
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(
        path,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )