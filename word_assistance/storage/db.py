from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from word_assistance.config import DB_PATH, DailyLimits

UTC = timezone.utc
ALLOWED_ORCHESTRATION_MODES = {"OPENCLAW_PREFERRED", "LOCAL_ONLY", "OPENCLAW_ONLY"}
ALLOWED_OCR_STRENGTH = {"FAST", "BALANCED", "ACCURATE"}
ALLOWED_CARD_LLM_STRATEGY = {"QUALITY_FIRST", "BALANCED", "FAST_FIRST"}


@dataclass
class ReviewResult:
    word_id: int
    result: str
    mode: str
    error_type: str
    user_answer: str | None = None
    correct_answer: str | None = None
    latency_ms: int | None = None


class Database:
    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def initialize(self) -> None:
        schema_path = Path(__file__).with_name("schema.sql")
        with self.connect() as conn:
            conn.executescript(schema_path.read_text(encoding="utf-8"))
        self.ensure_parent_settings_schema()
        self.ensure_default_users()
        self.ensure_default_parent_settings()

    def ensure_parent_settings_schema(self) -> None:
        with self.connect() as conn:
            columns = {
                str(row["name"])
                for row in conn.execute("PRAGMA table_info(parent_settings)").fetchall()
            }
            if "orchestration_mode" not in columns:
                conn.execute(
                    """
                    ALTER TABLE parent_settings
                    ADD COLUMN orchestration_mode TEXT NOT NULL DEFAULT 'OPENCLAW_PREFERRED'
                    """
                )
            if "llm_provider" not in columns:
                conn.execute(
                    """
                    ALTER TABLE parent_settings
                    ADD COLUMN llm_provider TEXT NOT NULL DEFAULT 'openai-compatible'
                    """
                )
            if "llm_model" not in columns:
                conn.execute(
                    """
                    ALTER TABLE parent_settings
                    ADD COLUMN llm_model TEXT NOT NULL DEFAULT 'gpt-4o-mini'
                    """
                )
            if "card_llm_quality_model" not in columns:
                conn.execute(
                    """
                    ALTER TABLE parent_settings
                    ADD COLUMN card_llm_quality_model TEXT NOT NULL DEFAULT 'gpt-4.1-mini'
                    """
                )
            if "card_llm_fast_model" not in columns:
                conn.execute(
                    """
                    ALTER TABLE parent_settings
                    ADD COLUMN card_llm_fast_model TEXT NOT NULL DEFAULT 'gpt-4o-mini'
                    """
                )
            if "card_llm_strategy" not in columns:
                conn.execute(
                    """
                    ALTER TABLE parent_settings
                    ADD COLUMN card_llm_strategy TEXT NOT NULL DEFAULT 'QUALITY_FIRST'
                    """
                )
            if "ocr_strength" not in columns:
                conn.execute(
                    """
                    ALTER TABLE parent_settings
                    ADD COLUMN ocr_strength TEXT NOT NULL DEFAULT 'BALANCED'
                    """
                )
            if "correction_auto_accept_threshold" not in columns:
                conn.execute(
                    """
                    ALTER TABLE parent_settings
                    ADD COLUMN correction_auto_accept_threshold REAL NOT NULL DEFAULT 0.85
                    """
                )

    def ensure_default_users(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (id, role, display_name)
                VALUES (1, 'PARENT', '家长'), (2, 'CHILD', '孩子')
                """
            )

    def ensure_default_parent_settings(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO parent_settings
                (
                  parent_user_id, child_user_id, daily_new_limit, daily_review_limit,
                  orchestration_mode, strict_mode, llm_enabled, voice_accent, tts_voice,
                  auto_tts, ocr_strength, correction_auto_accept_threshold, llm_provider, llm_model,
                  card_llm_quality_model, card_llm_fast_model, card_llm_strategy
                )
                VALUES (
                  1, 2, 8, 20,
                  'OPENCLAW_PREFERRED', 0, 1, 'en-GB', 'en-GB-SoniaNeural',
                  0, 'BALANCED', 0.85, 'openai-compatible', 'gpt-4o-mini',
                  'gpt-4.1-mini', 'gpt-4o-mini', 'QUALITY_FIRST'
                )
                """
            )

    def get_user(self, user_id: int) -> sqlite3.Row | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return row

    def get_parent_settings(self, child_user_id: int) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM parent_settings
                WHERE child_user_id = ?
                """,
                (child_user_id,),
            ).fetchone()
        if not row:
            self.ensure_default_parent_settings()
            return self.get_parent_settings(child_user_id)
        data = dict(row)
        data["strict_mode"] = bool(data["strict_mode"])
        data["llm_enabled"] = bool(data["llm_enabled"])
        data["auto_tts"] = bool(data["auto_tts"])
        data["orchestration_mode"] = _normalize_orchestration_mode(data.get("orchestration_mode"))
        data["ocr_strength"] = _normalize_ocr_strength(data.get("ocr_strength"))
        data["llm_model"] = _normalize_model_name(data.get("llm_model"), "gpt-4o-mini")
        data["card_llm_quality_model"] = _normalize_model_name(
            data.get("card_llm_quality_model"),
            "gpt-4.1-mini",
        )
        data["card_llm_fast_model"] = _normalize_model_name(
            data.get("card_llm_fast_model"),
            data["llm_model"],
        )
        data["card_llm_strategy"] = _normalize_card_llm_strategy(data.get("card_llm_strategy"))
        data["correction_auto_accept_threshold"] = _normalize_auto_accept_threshold(
            data.get("correction_auto_accept_threshold")
        )
        return data

    def update_parent_settings(self, child_user_id: int, settings: dict) -> dict:
        current = self.get_parent_settings(child_user_id)
        merged = {
            **current,
            **settings,
            "daily_new_limit": max(1, min(int(settings.get("daily_new_limit", current["daily_new_limit"])), 40)),
            "daily_review_limit": max(1, min(int(settings.get("daily_review_limit", current["daily_review_limit"])), 200)),
            "strict_mode": int(bool(settings.get("strict_mode", current["strict_mode"]))),
            "llm_enabled": int(bool(settings.get("llm_enabled", current["llm_enabled"]))),
            "auto_tts": int(bool(settings.get("auto_tts", current["auto_tts"]))),
            "voice_accent": str(settings.get("voice_accent", current["voice_accent"])),
            "tts_voice": str(settings.get("tts_voice", current["tts_voice"])),
            "ocr_strength": _normalize_ocr_strength(settings.get("ocr_strength", current.get("ocr_strength"))),
            "correction_auto_accept_threshold": _normalize_auto_accept_threshold(
                settings.get("correction_auto_accept_threshold", current.get("correction_auto_accept_threshold"))
            ),
            "llm_provider": str(settings.get("llm_provider", current.get("llm_provider", "openai-compatible"))),
            "llm_model": _normalize_model_name(
                settings.get("llm_model", current.get("llm_model", "gpt-4o-mini")),
                "gpt-4o-mini",
            ),
            "card_llm_quality_model": _normalize_model_name(
                settings.get("card_llm_quality_model", current.get("card_llm_quality_model", "gpt-4.1-mini")),
                "gpt-4.1-mini",
            ),
            "card_llm_fast_model": _normalize_model_name(
                settings.get("card_llm_fast_model", current.get("card_llm_fast_model", "gpt-4o-mini")),
                "gpt-4o-mini",
            ),
            "card_llm_strategy": _normalize_card_llm_strategy(
                settings.get("card_llm_strategy", current.get("card_llm_strategy", "QUALITY_FIRST"))
            ),
            "orchestration_mode": _normalize_orchestration_mode(
                settings.get("orchestration_mode", current.get("orchestration_mode"))
            ),
        }
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE parent_settings
                SET daily_new_limit = ?,
                    daily_review_limit = ?,
                    orchestration_mode = ?,
                    strict_mode = ?,
                    llm_enabled = ?,
                    voice_accent = ?,
                    tts_voice = ?,
                    auto_tts = ?,
                    ocr_strength = ?,
                    correction_auto_accept_threshold = ?,
                    llm_provider = ?,
                    llm_model = ?,
                    card_llm_quality_model = ?,
                    card_llm_fast_model = ?,
                    card_llm_strategy = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE child_user_id = ?
                """,
                (
                    merged["daily_new_limit"],
                    merged["daily_review_limit"],
                    merged["orchestration_mode"],
                    merged["strict_mode"],
                    merged["llm_enabled"],
                    merged["voice_accent"],
                    merged["tts_voice"],
                    merged["auto_tts"],
                    merged["ocr_strength"],
                    merged["correction_auto_accept_threshold"],
                    merged["llm_provider"],
                    merged["llm_model"],
                    merged["card_llm_quality_model"],
                    merged["card_llm_fast_model"],
                    merged["card_llm_strategy"],
                    child_user_id,
                ),
            )
        return self.get_parent_settings(child_user_id)

    def get_daily_limits(self, user_id: int) -> DailyLimits:
        settings = self.get_parent_settings(user_id)
        return DailyLimits(
            new_words=int(settings.get("daily_new_limit", 8)),
            reviews=int(settings.get("daily_review_limit", 20)),
        )

    def save_chat_message(self, *, user_id: int, role: str, message: str) -> dict | None:
        text = str(message or "").strip()
        if not text:
            return None
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in {"user", "assistant"}:
            raise ValueError("invalid chat role")

        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO chat_messages (user_id, role, message)
                VALUES (?, ?, ?)
                """,
                (user_id, normalized_role, text),
            )
            row = conn.execute(
                """
                SELECT id, user_id, role, message, created_at
                FROM chat_messages
                WHERE id = ?
                """,
                (int(cur.lastrowid),),
            ).fetchone()
        return dict(row) if row else None

    def list_chat_messages(self, *, user_id: int, limit: int = 120) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, user_id, role, message, created_at
                FROM chat_messages
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, max(1, min(int(limit), 500))),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def clear_chat_messages(self, *, user_id: int) -> int:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
        return int(cur.rowcount or 0)

    def create_import(
        self,
        *,
        user_id: int,
        source_type: str,
        source_name: str,
        source_path: str | None,
        importer_role: str,
        tags: Sequence[str] | None,
        note: str | None,
    ) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO imports (user_id, source_type, source_name, source_path, importer_role, tags, note)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    source_type,
                    source_name,
                    source_path,
                    importer_role,
                    _json_dumps(tags or []),
                    note,
                ),
            )
            return int(cur.lastrowid)

    def add_import_items(self, import_id: int, items: Sequence[dict]) -> None:
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO import_items
                (import_id, word_candidate, suggested_correction, confidence, needs_confirmation, accepted, final_lemma)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        import_id,
                        item["word_candidate"],
                        item["suggested_correction"],
                        item["confidence"],
                        int(item["needs_confirmation"]),
                        item.get("accepted"),
                        item.get("final_lemma"),
                    )
                    for item in items
                ],
            )

    def list_import_items(self, import_id: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT id, word_candidate, suggested_correction, confidence, needs_confirmation, accepted, final_lemma
                FROM import_items
                WHERE import_id = ?
                ORDER BY id
                """,
                (import_id,),
            ).fetchall()
        items: list[dict] = []
        for row in rows:
            obj = dict(row)
            obj["needs_confirmation"] = bool(obj.get("needs_confirmation"))
            items.append(obj)
        return items

    def update_import_item_acceptance(self, import_item_id: int, accepted: bool, final_lemma: str | None) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE import_items
                SET accepted = ?, final_lemma = COALESCE(?, suggested_correction)
                WHERE id = ?
                """,
                (int(accepted), final_lemma, import_item_id),
            )

    def commit_import(self, import_id: int) -> int:
        with self.connect() as conn:
            import_row = conn.execute("SELECT * FROM imports WHERE id = ?", (import_id,)).fetchone()
            if import_row is None:
                raise ValueError(f"import batch {import_id} not found")

            items = conn.execute(
                """
                SELECT * FROM import_items
                WHERE import_id = ? AND COALESCE(accepted, 1) = 1
                """,
                (import_id,),
            ).fetchall()
            inserted = 0
            for item in items:
                lemma = (item["final_lemma"] or item["suggested_correction"]).strip().lower()
                if not lemma:
                    continue
                word_id = conn.execute(
                    """
                    INSERT INTO words (user_id, lemma, surface, tags, status)
                    VALUES (?, ?, ?, ?, 'NEW')
                    ON CONFLICT(user_id, lemma)
                    DO UPDATE SET
                        surface = excluded.surface,
                        tags = excluded.tags,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    (
                        import_row["user_id"],
                        lemma,
                        item["word_candidate"],
                        import_row["tags"],
                    ),
                ).fetchone()[0]
                conn.execute(
                    """
                    INSERT OR IGNORE INTO srs_state (word_id, next_review_at, ease, interval_days, streak, lapses)
                    VALUES (?, ?, 2.5, 1, 0, 0)
                    """,
                    (word_id, _iso_now()),
                )
                inserted += 1
            return inserted

    def get_word(self, word_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
        return _decode_word(row) if row else None

    def get_word_by_lemma(self, user_id: int, lemma: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM words WHERE user_id = ? AND lemma = ?", (user_id, lemma.lower())
            ).fetchone()
        return _decode_word(row) if row else None

    def update_word_learning_fields(
        self,
        *,
        word_id: int,
        phonetic: str | None = None,
        meaning_zh: Sequence[str] | None = None,
        meaning_en: Sequence[str] | None = None,
        examples: Sequence[str] | None = None,
    ) -> dict:
        with self.connect() as conn:
            current = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
            if current is None:
                raise ValueError("word not found")

            next_phonetic = str(phonetic).strip() if phonetic is not None else current["phonetic"]
            next_meaning_zh = _sanitize_str_list(meaning_zh) if meaning_zh is not None else _json_loads(current["meaning_zh"])
            next_meaning_en = _sanitize_str_list(meaning_en) if meaning_en is not None else _json_loads(current["meaning_en"])
            next_examples = _sanitize_str_list(examples) if examples is not None else _json_loads(current["examples"])

            conn.execute(
                """
                UPDATE words
                SET phonetic = ?,
                    meaning_zh = ?,
                    meaning_en = ?,
                    examples = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    next_phonetic or None,
                    _json_dumps(next_meaning_zh),
                    _json_dumps(next_meaning_en),
                    _json_dumps(next_examples),
                    word_id,
                ),
            )
            row = conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()
        if row is None:
            raise ValueError("word not found")
        return _decode_word(row)

    def list_words(
        self,
        user_id: int,
        *,
        status: str | None = None,
        statuses: Sequence[str] | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        resolved_statuses = _resolve_statuses(status=status, statuses=statuses)
        clauses = ["w.user_id = ?"]
        params: list[object] = [user_id]

        if resolved_statuses:
            placeholders = ",".join(["?"] * len(resolved_statuses))
            clauses.append(f"w.status IN ({placeholders})")
            params.extend(resolved_statuses)

        params.extend([max(1, int(limit)), max(0, int(offset))])
        query = f"""
            SELECT w.*, s.next_review_at, s.interval_days, s.streak, s.lapses
            FROM words w
            LEFT JOIN srs_state s ON s.word_id = w.id
            WHERE {' AND '.join(clauses)}
            ORDER BY w.id ASC
            LIMIT ? OFFSET ?
        """
        with self.connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [_decode_word(row) for row in rows]

    def count_words(self, user_id: int, *, status: str | None = None, statuses: Sequence[str] | None = None) -> int:
        resolved_statuses = _resolve_statuses(status=status, statuses=statuses)
        clauses = ["user_id = ?"]
        params: list[object] = [user_id]
        if resolved_statuses:
            placeholders = ",".join(["?"] * len(resolved_statuses))
            clauses.append(f"status IN ({placeholders})")
            params.extend(resolved_statuses)
        query = f"SELECT COUNT(*) AS cnt FROM words WHERE {' AND '.join(clauses)}"
        with self.connect() as conn:
            row = conn.execute(query, tuple(params)).fetchone()
        return int(row["cnt"] if row else 0)

    def export_words(self, user_id: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT w.lemma, w.surface, w.status, w.tags, w.meaning_zh, w.meaning_en, w.examples,
                       s.next_review_at, s.interval_days, s.streak, s.lapses,
                       COALESCE(t.total_reviews, 0) AS total_reviews,
                       COALESCE(t.pass_reviews, 0) AS pass_reviews,
                       CASE WHEN COALESCE(t.total_reviews, 0) = 0 THEN 0
                            ELSE ROUND(t.pass_reviews * 1.0 / t.total_reviews, 3)
                       END AS accuracy
                FROM words w
                LEFT JOIN srs_state s ON s.word_id = w.id
                LEFT JOIN (
                    SELECT word_id,
                           COUNT(*) AS total_reviews,
                           SUM(CASE WHEN result = 'PASS' THEN 1 ELSE 0 END) AS pass_reviews
                    FROM reviews
                    GROUP BY word_id
                ) t ON t.word_id = w.id
                WHERE w.user_id = ?
                ORDER BY datetime(w.updated_at) DESC
                """,
                (user_id,),
            ).fetchall()
        data: list[dict] = []
        for row in rows:
            obj = dict(row)
            obj["tags"] = _json_loads(obj.get("tags"))
            obj["meaning_zh"] = _json_loads(obj.get("meaning_zh"))
            obj["meaning_en"] = _json_loads(obj.get("meaning_en"))
            obj["examples"] = _json_loads(obj.get("examples"))
            data.append(obj)
        return data

    def correct_word(
        self,
        *,
        user_id: int,
        word_id: int,
        new_lemma: str,
        new_surface: str | None,
        reason: str | None,
        corrected_by_role: str,
    ) -> dict:
        normalized = new_lemma.strip().lower()
        if not normalized:
            raise ValueError("new lemma is empty")

        role = corrected_by_role.upper()
        if role not in {"PARENT", "CHILD"}:
            raise ValueError("corrected_by_role must be PARENT or CHILD")

        with self.connect() as conn:
            current = conn.execute(
                "SELECT * FROM words WHERE id = ? AND user_id = ?",
                (word_id, user_id),
            ).fetchone()
            if current is None:
                raise ValueError("word not found")

            conflict = conn.execute(
                "SELECT * FROM words WHERE user_id = ? AND lemma = ? AND id != ?",
                (user_id, normalized, word_id),
            ).fetchone()

            surface = (new_surface or normalized).strip() or normalized
            target_word_id = word_id

            if conflict is None:
                conn.execute(
                    """
                    UPDATE words
                    SET lemma = ?, surface = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (normalized, surface, word_id),
                )
            else:
                target_word_id = int(conflict["id"])
                self._merge_word_records(conn, source_word_id=word_id, target_word_id=target_word_id)
                merged_tags = _merge_json_text_lists(current["tags"], conflict["tags"], limit=10)
                merged_meaning_zh = _merge_json_text_lists(current["meaning_zh"], conflict["meaning_zh"], limit=8)
                merged_meaning_en = _merge_json_text_lists(current["meaning_en"], conflict["meaning_en"], limit=8)
                merged_examples = _merge_json_text_lists(current["examples"], conflict["examples"], limit=6)
                merged_status = _merge_status(current["status"], conflict["status"])
                merged_phonetic = str(conflict["phonetic"] or current["phonetic"] or "").strip() or None

                conn.execute(
                    """
                    UPDATE words
                    SET lemma = ?,
                        surface = ?,
                        phonetic = ?,
                        meaning_zh = ?,
                        meaning_en = ?,
                        examples = ?,
                        tags = ?,
                        status = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (
                        normalized,
                        surface,
                        merged_phonetic,
                        _json_dumps(merged_meaning_zh),
                        _json_dumps(merged_meaning_en),
                        _json_dumps(merged_examples),
                        _json_dumps(merged_tags),
                        merged_status,
                        target_word_id,
                    ),
                )
                conn.execute("DELETE FROM words WHERE id = ?", (word_id,))

            conn.execute(
                """
                INSERT INTO word_corrections
                (word_id, user_id, old_lemma, new_lemma, old_surface, new_surface, reason, corrected_by_role)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target_word_id,
                    user_id,
                    current["lemma"],
                    normalized,
                    current["surface"],
                    surface,
                    reason,
                    role,
                ),
            )

            row = conn.execute("SELECT * FROM words WHERE id = ?", (target_word_id,)).fetchone()
        return _decode_word(row)

    def list_word_corrections(self, user_id: int, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM word_corrections
                WHERE user_id = ?
                ORDER BY datetime(corrected_at) DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_word(
        self,
        *,
        user_id: int,
        word_id: int,
        deleted_by_role: str = "CHILD",
    ) -> dict:
        role = deleted_by_role.upper()
        if role not in {"PARENT", "CHILD"}:
            raise ValueError("deleted_by_role must be PARENT or CHILD")

        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM words WHERE id = ? AND user_id = ?",
                (word_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError("word not found")
            payload = _decode_word(row)
            conn.execute("DELETE FROM words WHERE id = ? AND user_id = ?", (word_id, user_id))
        return payload

    def set_word_status(self, *, user_id: int, word_id: int, status: str) -> dict:
        normalized = str(status or "").strip().upper()
        if normalized not in {"NEW", "LEARNING", "REVIEWING", "MASTERED", "SUSPENDED"}:
            raise ValueError("invalid status")

        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM words WHERE id = ? AND user_id = ?",
                (word_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError("word not found")
            conn.execute(
                "UPDATE words SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (normalized, word_id),
            )
            if normalized in {"LEARNING", "REVIEWING"}:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO srs_state (word_id, next_review_at, ease, interval_days, streak, lapses)
                    VALUES (?, ?, 2.5, 1, 0, 0)
                    """,
                    (word_id, _iso_now()),
                )
            updated = conn.execute(
                """
                SELECT w.*, s.next_review_at, s.interval_days, s.streak, s.lapses
                FROM words w
                LEFT JOIN srs_state s ON s.word_id = w.id
                WHERE w.id = ?
                """,
                (word_id,),
            ).fetchone()
        if updated is None:
            raise ValueError("word not found")
        return _decode_word(updated)

    def _merge_word_records(self, conn: sqlite3.Connection, *, source_word_id: int, target_word_id: int) -> None:
        conn.execute(
            "UPDATE reviews SET word_id = ? WHERE word_id = ?",
            (target_word_id, source_word_id),
        )
        conn.execute(
            "UPDATE word_corrections SET word_id = ? WHERE word_id = ?",
            (target_word_id, source_word_id),
        )

        source_state = conn.execute("SELECT * FROM srs_state WHERE word_id = ?", (source_word_id,)).fetchone()
        target_state = conn.execute("SELECT * FROM srs_state WHERE word_id = ?", (target_word_id,)).fetchone()
        if source_state and target_state:
            merged = _merge_srs_state(source=source_state, target=target_state)
            conn.execute(
                """
                UPDATE srs_state
                SET last_review_at = ?,
                    next_review_at = ?,
                    ease = ?,
                    interval_days = ?,
                    streak = ?,
                    lapses = ?
                WHERE word_id = ?
                """,
                (
                    merged["last_review_at"],
                    merged["next_review_at"],
                    merged["ease"],
                    merged["interval_days"],
                    merged["streak"],
                    merged["lapses"],
                    target_word_id,
                ),
            )
            conn.execute("DELETE FROM srs_state WHERE word_id = ?", (source_word_id,))
        elif source_state and not target_state:
            conn.execute(
                "UPDATE srs_state SET word_id = ? WHERE word_id = ?",
                (target_word_id, source_word_id),
            )

        source_cards = conn.execute(
            "SELECT id, type, version FROM cards WHERE word_id = ?",
            (source_word_id,),
        ).fetchall()
        for card in source_cards:
            exists = conn.execute(
                """
                SELECT 1 FROM cards
                WHERE word_id = ? AND type = ? AND version = ?
                """,
                (target_word_id, card["type"], card["version"]),
            ).fetchone()
            if exists:
                conn.execute("DELETE FROM cards WHERE id = ?", (card["id"],))
            else:
                conn.execute("UPDATE cards SET word_id = ? WHERE id = ?", (target_word_id, card["id"]))

    def get_due_review_words(self, user_id: int, limit: int) -> list[dict]:
        now = _iso_now()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT w.*, s.next_review_at, s.interval_days, s.streak, s.lapses
                FROM words w
                JOIN srs_state s ON s.word_id = w.id
                WHERE w.user_id = ?
                  AND w.status IN ('LEARNING', 'REVIEWING')
                  AND (s.next_review_at IS NULL OR s.next_review_at <= ?)
                ORDER BY datetime(s.next_review_at) ASC
                LIMIT ?
                """,
                (user_id, now, limit),
            ).fetchall()
        return [_decode_word(row) for row in rows]

    def get_new_words(self, user_id: int, limit: int) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT w.*, s.next_review_at, s.interval_days, s.streak, s.lapses
                FROM words w
                LEFT JOIN srs_state s ON s.word_id = w.id
                WHERE w.user_id = ? AND w.status = 'NEW'
                ORDER BY datetime(w.created_at) ASC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [_decode_word(row) for row in rows]

    def get_today_task(self, user_id: int, limits: DailyLimits) -> dict:
        review_words = self.get_due_review_words(user_id, limits.reviews)
        review_ids = {w["id"] for w in review_words}
        new_words = [w for w in self.get_new_words(user_id, limits.new_words) if w["id"] not in review_ids]
        return {
            "review": review_words,
            "new": new_words,
        }

    def save_review(self, review: ReviewResult) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO reviews (word_id, result, mode, error_type, user_answer, correct_answer, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    review.word_id,
                    review.result,
                    review.mode,
                    review.error_type,
                    review.user_answer,
                    review.correct_answer,
                    review.latency_ms,
                ),
            )

    def get_srs_state(self, word_id: int) -> dict | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM srs_state WHERE word_id = ?", (word_id,)).fetchone()
        return dict(row) if row else None

    def save_srs_state(
        self,
        *,
        word_id: int,
        last_review_at: str | None,
        next_review_at: str,
        ease: float,
        interval_days: int,
        streak: int,
        lapses: int,
    ) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO srs_state (word_id, last_review_at, next_review_at, ease, interval_days, streak, lapses)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(word_id)
                DO UPDATE SET
                  last_review_at = excluded.last_review_at,
                  next_review_at = excluded.next_review_at,
                  ease = excluded.ease,
                  interval_days = excluded.interval_days,
                  streak = excluded.streak,
                  lapses = excluded.lapses
                """,
                (word_id, last_review_at, next_review_at, ease, interval_days, streak, lapses),
            )

    def update_word_status(self, word_id: int, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE words SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (status, word_id)
            )

    def find_words_by_ids(self, user_id: int, word_ids: Sequence[int]) -> list[dict]:
        if not word_ids:
            return []
        placeholders = ",".join(["?"] * len(word_ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM words WHERE user_id = ? AND id IN ({placeholders})",
                (user_id, *word_ids),
            ).fetchall()
        return [_decode_word(row) for row in rows]

    def record_card(
        self,
        *,
        word_id: int,
        card_type: str,
        html_path: str,
        version: str,
        content_hash: str,
        model_used: str = "rule_based_mvp",
    ) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO cards (word_id, type, html_path, version, content_hash, model_used)
                VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (word_id, card_type, html_path, version, content_hash, model_used),
            ).fetchone()
            return int(row[0])

    def get_latest_card(self, word_id: int, card_type: str) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM cards
                WHERE word_id = ? AND type = ?
                ORDER BY datetime(created_at) DESC
                LIMIT 1
                """,
                (word_id, card_type),
            ).fetchone()
        return dict(row) if row else None

    def create_exercise_session(self, user_id: int, session_type: str, html_path: str, word_ids: Sequence[int]) -> int:
        with self.connect() as conn:
            row = conn.execute(
                """
                INSERT INTO exercise_sessions (user_id, type, html_path, word_ids)
                VALUES (?, ?, ?, ?)
                RETURNING id
                """,
                (user_id, session_type, html_path, _json_dumps(list(word_ids))),
            ).fetchone()
            return int(row[0])

    def list_mistakes(self, user_id: int, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT w.lemma,
                       COUNT(*) AS fail_count,
                       SUM(CASE WHEN r.error_type = 'SPELLING' THEN 1 ELSE 0 END) AS spelling_errors,
                       SUM(CASE WHEN r.error_type = 'CONFUSION' THEN 1 ELSE 0 END) AS confusion_errors,
                       SUM(CASE WHEN r.error_type = 'MEANING' THEN 1 ELSE 0 END) AS meaning_errors,
                       SUM(CASE WHEN r.error_type = 'PRONUNCIATION' THEN 1 ELSE 0 END) AS pronunciation_errors
                FROM reviews r
                JOIN words w ON w.id = r.word_id
                WHERE w.user_id = ? AND r.result = 'FAIL'
                GROUP BY w.lemma
                ORDER BY fail_count DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def weekly_report(self, user_id: int, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        start = now - timedelta(days=7)
        start_iso = start.isoformat()
        with self.connect() as conn:
            totals = conn.execute(
                """
                SELECT
                  COUNT(*) AS review_count,
                  SUM(CASE WHEN result = 'PASS' THEN 1 ELSE 0 END) AS pass_count,
                  SUM(CASE WHEN result = 'FAIL' THEN 1 ELSE 0 END) AS fail_count
                FROM reviews r
                JOIN words w ON w.id = r.word_id
                WHERE w.user_id = ? AND r.review_at >= ?
                """,
                (user_id, start_iso),
            ).fetchone()

            new_words = conn.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM words
                WHERE user_id = ? AND created_at >= ?
                """,
                (user_id, start_iso),
            ).fetchone()["cnt"]

            mastered_words = conn.execute(
                "SELECT COUNT(*) AS cnt FROM words WHERE user_id = ? AND status = 'MASTERED'",
                (user_id,),
            ).fetchone()["cnt"]

            studied_days = conn.execute(
                """
                SELECT COUNT(DISTINCT substr(r.review_at, 1, 10)) AS cnt
                FROM reviews r
                JOIN words w ON w.id = r.word_id
                WHERE w.user_id = ? AND r.review_at >= ?
                """,
                (user_id, start_iso),
            ).fetchone()["cnt"]

            practice_rows = conn.execute(
                """
                SELECT w.id,
                       w.lemma,
                       w.status,
                       COUNT(*) AS practice_total,
                       SUM(CASE WHEN r.result = 'PASS' THEN 1 ELSE 0 END) AS correct_count,
                       SUM(CASE WHEN r.mode = 'SPELLING' THEN 1 ELSE 0 END) AS spelling_total,
                       SUM(CASE WHEN r.mode = 'MATCH' THEN 1 ELSE 0 END) AS match_total,
                       MAX(r.review_at) AS last_practice_at
                FROM reviews r
                JOIN words w ON w.id = r.word_id
                WHERE w.user_id = ? AND r.review_at >= ? AND r.mode IN ('SPELLING', 'MATCH')
                GROUP BY w.id, w.lemma, w.status
                ORDER BY practice_total DESC, datetime(last_practice_at) DESC, w.lemma ASC
                """,
                (user_id, start_iso),
            ).fetchall()

        review_count = totals["review_count"] or 0
        pass_count = totals["pass_count"] or 0
        accuracy = round(pass_count / review_count, 3) if review_count else 0.0
        mistakes = self.list_mistakes(user_id=user_id, limit=20)
        practice_stats: list[dict] = []
        for row in practice_rows:
            total_attempts = int(row["practice_total"] or 0)
            correct_attempts = int(row["correct_count"] or 0)
            practice_stats.append(
                {
                    "word_id": int(row["id"]),
                    "lemma": row["lemma"],
                    "status": row["status"],
                    "practice_total": total_attempts,
                    "correct_count": correct_attempts,
                    "accuracy": round(correct_attempts / total_attempts, 3) if total_attempts else 0.0,
                    "spelling_total": int(row["spelling_total"] or 0),
                    "match_total": int(row["match_total"] or 0),
                    "last_practice_at": row["last_practice_at"],
                }
            )

        if accuracy < 0.65:
            suggestion_new_limit = 4
            suggestion_ratio = "Review 75% / New 25%"
        elif accuracy < 0.8:
            suggestion_new_limit = 6
            suggestion_ratio = "Review 65% / New 35%"
        else:
            suggestion_new_limit = 8
            suggestion_ratio = "Review 55% / New 45%"

        if practice_stats:
            sorted_by_risk = sorted(practice_stats, key=lambda item: (item["accuracy"], -item["practice_total"]))
            focus_words = [item["lemma"] for item in sorted_by_risk[:5]]
        else:
            focus_words = [m["lemma"] for m in mistakes[:5]]

        return {
            "window_days": 7,
            "new_words": new_words,
            "review_count": review_count,
            "pass_count": pass_count,
            "fail_count": totals["fail_count"] or 0,
            "accuracy": accuracy,
            "mastered_words": mastered_words,
            "study_streak_days": studied_days,
            "mistakes_top20": mistakes,
            "word_practice_stats": practice_stats,
            "next_week_suggestion": {
                "daily_new_limit": suggestion_new_limit,
                "review_ratio": suggestion_ratio,
                "focus_words": focus_words,
            },
        }


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str | None) -> list:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _sanitize_str_list(values: Sequence[str] | None, *, limit: int = 6) -> list[str]:
    if not values:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value).split()).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _decode_word(row: sqlite3.Row) -> dict:
    obj = dict(row)
    obj["meaning_zh"] = _json_loads(obj.get("meaning_zh"))
    obj["meaning_en"] = _json_loads(obj.get("meaning_en"))
    obj["examples"] = _json_loads(obj.get("examples"))
    obj["tags"] = _json_loads(obj.get("tags"))
    return obj


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_orchestration_mode(value: object) -> str:
    mode = str(value or "OPENCLAW_PREFERRED").strip().upper()
    if mode not in ALLOWED_ORCHESTRATION_MODES:
        return "OPENCLAW_PREFERRED"
    return mode


def _normalize_ocr_strength(value: object) -> str:
    strength = str(value or "BALANCED").strip().upper()
    if strength not in ALLOWED_OCR_STRENGTH:
        return "BALANCED"
    return strength


def _normalize_auto_accept_threshold(value: object) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        threshold = 0.85
    return round(max(0.5, min(threshold, 0.99)), 2)


def _normalize_card_llm_strategy(value: object) -> str:
    strategy = str(value or "QUALITY_FIRST").strip().upper()
    if strategy not in ALLOWED_CARD_LLM_STRATEGY:
        return "QUALITY_FIRST"
    return strategy


def _normalize_model_name(value: object, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    lowered = text.lower()
    if lowered in {"none", "null", "nil"}:
        return default
    return text


def _merge_json_text_lists(*raw_values: object, limit: int = 8) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()

    for raw in raw_values:
        if raw is None:
            continue
        if isinstance(raw, str):
            values = _json_loads(raw)
        elif isinstance(raw, (list, tuple)):
            values = list(raw)
        else:
            continue
        for value in values:
            text = " ".join(str(value).split()).strip()
            if not text:
                continue
            lowered = text.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            merged.append(text)
            if len(merged) >= limit:
                return merged
    return merged


def _merge_status(source: object, target: object) -> str:
    rank = {"SUSPENDED": 0, "NEW": 1, "LEARNING": 2, "REVIEWING": 3, "MASTERED": 4}
    src = str(source or "NEW").upper()
    tgt = str(target or "NEW").upper()
    if src not in rank:
        src = "NEW"
    if tgt not in rank:
        tgt = "NEW"
    return src if rank[src] >= rank[tgt] else tgt


def _merge_srs_state(*, source: sqlite3.Row, target: sqlite3.Row) -> dict:
    source_last = _parse_dt(source["last_review_at"])
    target_last = _parse_dt(target["last_review_at"])
    source_next = _parse_dt(source["next_review_at"])
    target_next = _parse_dt(target["next_review_at"])

    last_dt = max(dt for dt in (source_last, target_last) if dt is not None) if (source_last or target_last) else None
    next_candidates = [dt for dt in (source_next, target_next) if dt is not None]
    next_dt = min(next_candidates) if next_candidates else None

    ease_values = [float(source["ease"] or 2.5), float(target["ease"] or 2.5)]
    merged_ease = round(sum(ease_values) / len(ease_values), 2)

    return {
        "last_review_at": last_dt.isoformat() if last_dt else None,
        "next_review_at": next_dt.isoformat() if next_dt else _iso_now(),
        "ease": max(1.3, min(3.2, merged_ease)),
        "interval_days": max(int(source["interval_days"] or 1), int(target["interval_days"] or 1)),
        "streak": max(int(source["streak"] or 0), int(target["streak"] or 0)),
        "lapses": int(source["lapses"] or 0) + int(target["lapses"] or 0),
    }


def _parse_dt(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _resolve_statuses(*, status: str | None, statuses: Sequence[str] | None) -> list[str]:
    raw_values: list[str] = []
    if statuses is not None:
        raw_values.extend(str(item).strip().upper() for item in statuses if str(item).strip())
    elif status:
        raw_values.append(str(status).strip().upper())

    if not raw_values:
        return []
    allowed = {"NEW", "LEARNING", "REVIEWING", "MASTERED", "SUSPENDED"}
    resolved: list[str] = []
    for value in raw_values:
        if value in allowed and value not in resolved:
            resolved.append(value)
    return resolved
