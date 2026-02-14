from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"
UPLOADS_DIR = ARTIFACTS_DIR / "uploads"
CARDS_DIR = ARTIFACTS_DIR / "cards"
DICTIONARY_DIR = ARTIFACTS_DIR / "dictionary"
EXERCISES_DIR = ARTIFACTS_DIR / "exercises"
LEARNING_DIR = ARTIFACTS_DIR / "learning"
REPORTS_DIR = ARTIFACTS_DIR / "reports"
EXPORTS_DIR = ARTIFACTS_DIR / "exports"
AUDIO_DIR = ARTIFACTS_DIR / "audio"
BACKUPS_DIR = ARTIFACTS_DIR / "backups"
ASSETS_DIR = PROJECT_ROOT / "static" / "assets"
DB_PATH = PROJECT_ROOT / "word_assistance.db"


@dataclass(frozen=True)
class DailyLimits:
    new_words: int = 8
    reviews: int = 20


def ensure_dirs() -> None:
    for path in [
        ARTIFACTS_DIR,
        UPLOADS_DIR,
        CARDS_DIR,
        DICTIONARY_DIR,
        EXERCISES_DIR,
        LEARNING_DIR,
        REPORTS_DIR,
        EXPORTS_DIR,
        AUDIO_DIR,
        BACKUPS_DIR,
        ASSETS_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
