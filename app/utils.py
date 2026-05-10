from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status

from app.config import settings

# По таблице требований оставлены только MP3 и WAV.
ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
}


def ensure_upload_dir() -> Path:
    path = Path(settings.upload_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def validate_audio_type(file: UploadFile) -> str:
    content_type = file.content_type or ""
    if content_type not in ALLOWED_AUDIO_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported audio type. Use mp3 or wav",
        )

    return ALLOWED_AUDIO_TYPES[content_type]


def validate_audio_file(file: UploadFile, content: bytes) -> str:
    """Backward-compatible validator for old code paths.

    The optimized upload path validates the type first and streams the body in
    chunks, so the whole file is not loaded into memory.
    """
    max_size = settings.max_audio_size_mb * 1024 * 1024
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File is too large. Max size is {settings.max_audio_size_mb} MB",
        )

    return validate_audio_type(file)


def make_safe_audio_filename(extension: str) -> str:
    return f"{uuid4().hex}{extension}"


def detect_audio_duration_seconds(file_path: Path) -> int:
    """
    Возвращает длительность аудиофайла в секундах.
    Если файл не удалось прочитать, возвращает 0.
    """
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(file_path)
        length = getattr(getattr(audio, "info", None), "length", None)

        if length is None:
            return 0

        return max(0, int(round(float(length))))
    except Exception:
        return 0
