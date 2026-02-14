from __future__ import annotations

import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from word_assistance.config import ARTIFACTS_DIR, BACKUPS_DIR, DB_PATH

UTC = timezone.utc


def create_backup_bundle() -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    backup_path = BACKUPS_DIR / f"word_assistance_backup_{ts}.zip"

    with zipfile.ZipFile(backup_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        if DB_PATH.exists():
            zf.write(DB_PATH, arcname="word_assistance.db")

        if ARTIFACTS_DIR.exists():
            for path in ARTIFACTS_DIR.rglob("*"):
                if path.is_file() and path != backup_path:
                    rel = path.relative_to(ARTIFACTS_DIR)
                    zf.write(path, arcname=str(Path("artifacts") / rel))

    return backup_path


def restore_backup_bundle(bundle_path: Path) -> None:
    if not bundle_path.exists():
        raise FileNotFoundError(bundle_path)

    temp_dir = BACKUPS_DIR / "_restore_tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(bundle_path, "r") as zf:
        zf.extractall(temp_dir)

    db_src = temp_dir / "word_assistance.db"
    if db_src.exists():
        shutil.copy2(db_src, DB_PATH)

    artifacts_src = temp_dir / "artifacts"
    if artifacts_src.exists():
        for path in artifacts_src.rglob("*"):
            if path.is_file():
                rel = path.relative_to(artifacts_src)
                dest = ARTIFACTS_DIR / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest)

    shutil.rmtree(temp_dir)
