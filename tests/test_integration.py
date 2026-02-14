from __future__ import annotations

from word_assistance.commands.handler import handle_chat_message
from word_assistance.config import DailyLimits
from word_assistance.pipeline.importer import build_import_preview_from_text
from word_assistance.scheduler.srs import next_state, state_from_row
from word_assistance.storage.db import ReviewResult


def test_import_to_today_task_flow(temp_db):
    preview = build_import_preview_from_text("antenna through because take off")
    import_id = temp_db.create_import(
        user_id=2,
        source_type="TEXT",
        source_name="lesson1",
        source_path=None,
        importer_role="CHILD",
        tags=["Reading"],
        note="week 1",
    )
    temp_db.add_import_items(import_id, preview)
    inserted = temp_db.commit_import(import_id)

    task = temp_db.get_today_task(user_id=2, limits=DailyLimits(new_words=8, reviews=20))

    assert inserted >= 3
    assert len(task["new"]) >= 3


def test_week_report_contains_links_and_fields(temp_db):
    preview = build_import_preview_from_text("antenna")
    import_id = temp_db.create_import(
        user_id=2,
        source_type="TEXT",
        source_name="seed",
        source_path=None,
        importer_role="CHILD",
        tags=["Reading"],
        note=None,
    )
    temp_db.add_import_items(import_id, preview)
    temp_db.commit_import(import_id)

    word = temp_db.get_word_by_lemma(2, "antenna")
    temp_db.save_review(
        ReviewResult(
            word_id=word["id"],
            result="FAIL",
            mode="SPELLING",
            error_type="SPELLING",
            user_answer="antena",
            correct_answer="antenna",
            latency_ms=2200,
        )
    )

    current = state_from_row(temp_db.get_srs_state(word["id"]))
    updated = next_state(current, passed=False)
    temp_db.save_srs_state(
        word_id=word["id"],
        last_review_at=updated.state.last_review_at,
        next_review_at=updated.state.next_review_at,
        ease=updated.state.ease,
        interval_days=updated.state.interval_days,
        streak=updated.state.streak,
        lapses=updated.state.lapses,
    )

    response = handle_chat_message(temp_db, user_id=2, message="/report week")

    assert "links" in response
    assert len(response["links"]) == 2
    assert "next_week_suggestion" in response["data"]
