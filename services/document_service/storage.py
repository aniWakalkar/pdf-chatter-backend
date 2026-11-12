import uuid
from pathlib import Path

from shared.config import get_settings


def resolve_path(storage_key: str) -> Path:
    base = get_settings().upload_path
    path = (base / storage_key).resolve()
    if base not in path.parents:
        raise ValueError("Invalid storage key")
    return path


def save_file(user_id: uuid.UUID, data: bytes) -> str:
    storage_key = f"{user_id}/{uuid.uuid4().hex}.pdf"
    path = resolve_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return storage_key


def delete_file(storage_key: str) -> None:
    try:
        resolve_path(storage_key).unlink(missing_ok=True)
    except (OSError, ValueError):
        pass
