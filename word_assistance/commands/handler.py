from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path

from word_assistance.cards.generator import generate_card, generate_dictionary_card
from word_assistance.config import ARTIFACTS_DIR, DailyLimits, REPORTS_DIR
from word_assistance.exercises.generator import build_daily_combo_exercise, build_exercise
from word_assistance.learning.hub import build_learning_hub
from word_assistance.lexicon import ensure_words_enriched
from word_assistance.pipeline.extraction import simple_lemma
from word_assistance.safety.policies import validate_child_request
from word_assistance.services.llm import extract_custom_learning_words
from word_assistance.storage.db import Database

UTC = timezone.utc


def handle_chat_message(db: Database, user_id: int, message: str, limits: DailyLimits | None = None) -> dict:
    limits = limits or DailyLimits()
    message = message.strip()
    if not message:
        return {"reply": "Try /today to view today's plan."}

    check = validate_child_request(message)
    if not check.allowed:
        return {"reply": check.reason}

    if message.startswith("/"):
        return _handle_command(db, user_id, message, limits)

    custom_words = _normalize_learning_words(extract_custom_learning_words(message))
    if custom_words:
        return _cmd_learn_with_words(db, user_id, limits, custom_words, regenerate=False)

    lowered = message.lower()
    if "开始学习" in message or "学习词库" in message or "开始背单词" in message or "start learning" in lowered:
        return _cmd_learn(db, user_id, limits, regenerate=False)
    if "今日任务" in message or "today" in lowered:
        return _cmd_today(db, user_id, limits)
    if "复习" in message or "review" in lowered:
        return _cmd_review(db, user_id, limits)
    if "常错" in message or "mistake" in lowered:
        return _cmd_mistakes(db, user_id)
    if "周报" in message or "report" in lowered:
        return _cmd_report_week(db, user_id)
    if "解释" in message and _last_english_token(message):
        word = _last_english_token(message)
        if db.get_word_by_lemma(user_id=user_id, lemma=word):
            card = generate_card(
                db=db,
                user_id=user_id,
                word=word,
                card_type="KIDS",
                regenerate=False,
            )
            return {
                "reply": f"I generated a Kids card for {word}. You can generate a Museum card next.",
                "links": [card["url"]],
            }
        card = generate_dictionary_card(word=word, regenerate=False)
        return {
            "reply": f"{word} is not in vocabulary yet. I generated a lookup card (not auto-added). Use 'Add to Vocabulary' if needed.",
            "links": [card["url"]],
        }

    return {
        "reply": "I can execute: /learn /today /words /review /card <word> /game spelling /game match /report week",
    }


def _handle_command(db: Database, user_id: int, command: str, limits: DailyLimits) -> dict:
    parts = command.split()
    cmd = parts[0].lower()

    if cmd == "/learn":
        learn_words = _parse_learn_words_from_command(command)
        if learn_words:
            regenerate = "--new" in parts or "--regenerate" in parts
            return _cmd_learn_with_words(db, user_id, limits, learn_words, regenerate=regenerate)
        regenerate = "--new" in parts or "--regenerate" in parts
        return _cmd_learn(db, user_id, limits, regenerate=regenerate)
    if cmd == "/today":
        return _cmd_today(db, user_id, limits)
    if cmd == "/words":
        return _cmd_words(db, user_id)
    if cmd == "/review":
        return _cmd_review(db, user_id, limits)
    if cmd == "/new":
        count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else limits.new_words
        custom = DailyLimits(new_words=max(1, min(count, 20)), reviews=limits.reviews)
        return _cmd_today(db, user_id, custom)
    if cmd == "/mistakes":
        return _cmd_mistakes(db, user_id)
    if cmd == "/fix":
        if len(parts) < 3:
            return {"reply": "Usage: /fix wrong correct (example: /fix antena antenna)"}
        return _cmd_fix(db, user_id=user_id, wrong=parts[1], correct=parts[2])
    if cmd == "/card":
        if len(parts) < 2:
            return {"reply": "Usage: /card antenna"}
        word = parts[1]
        regenerate = "--new" in parts or "--regenerate" in parts
        normalized = word.strip().lower()
        if db.get_word_by_lemma(user_id=user_id, lemma=normalized):
            card = generate_card(
                db=db,
                user_id=user_id,
                word=normalized,
                card_type="MUSEUM",
                regenerate=regenerate,
            )
            info = "Loaded cached version" if card["cached"] else "Generated new version"
            return {"reply": f"{info}: Museum card for {normalized}", "links": [card["url"]]}
        card = generate_dictionary_card(word=normalized, regenerate=regenerate)
        info = "Loaded cached version" if card["cached"] else "Generated new version"
        return {
            "reply": f"{info}: Lookup card for {normalized} (not auto-added to vocabulary)",
            "links": [card["url"]],
        }
    if cmd == "/game":
        regenerate = "--new" in parts or "--regenerate" in parts
        mode = next((part.lower() for part in parts[1:] if not part.startswith("--")), "spelling")
        return _cmd_game(db, user_id, mode, limits=limits, regenerate=regenerate)
    if cmd == "/report" and len(parts) >= 2 and parts[1].lower() == "week":
        return _cmd_report_week(db, user_id)

    return {
        "reply": (
            "Unsupported command. Available commands: "
            "/learn /learn --words appraise,bolster /today /words /review /new 8 /mistakes "
            "/fix wrong correct /card /game spelling|match|daily /report week"
        )
    }


def _cmd_learn(db: Database, user_id: int, limits: DailyLimits, *, regenerate: bool = False) -> dict:
    task = db.get_today_task(user_id, limits)
    learning_pool = _collect_today_learning_pool(task)
    if not learning_pool:
        return {
            "reply": "Your vocabulary is empty. Import words first, then I can generate cards and practice."
        }
    learning_pool = ensure_words_enriched(db, user_id=user_id, words=learning_pool)

    ranked = _rank_learning_words(db, user_id, learning_pool)
    focus_word = ranked[0]["lemma"]
    exercise_words = ranked
    practice_path, practice_meta = build_daily_combo_exercise(
        user_id=user_id,
        words=exercise_words,
        regenerate=regenerate,
    )
    practice_url = _artifact_url(practice_path)
    hub_path, hub_meta = build_learning_hub(
        user_id=user_id,
        words=ranked,
        practice_url=practice_url,
        regenerate=regenerate,
    )
    hub_url = _artifact_url(hub_path)

    return {
        "reply": (
            f"Learning flow is ready: left word list + right card workspace ({len(ranked)} words). "
            f"Connected to today's spelling + definition match practice. Current priority word: {focus_word}."
        ),
        "links": [hub_url, f"{practice_url}#spell", f"{practice_url}#match"],
        "data": {
            "focus_word": focus_word,
            "word_count": len(ranked),
            "hub_cached": hub_meta["cached"],
            "practice_cached": practice_meta["cached"],
        },
    }


def _cmd_learn_with_words(
    db: Database,
    user_id: int,
    limits: DailyLimits,
    words: list[str],
    *,
    regenerate: bool = False,
) -> dict:
    requested = _normalize_learning_words(words)
    if not requested:
        return {"reply": "No valid words detected. Please provide an English word list and retry."}

    inserted = _ensure_words_in_vocabulary(db, user_id=user_id, words=requested)
    selected_rows: list[dict] = []
    for lemma in requested:
        row = db.get_word_by_lemma(user_id=user_id, lemma=lemma)
        if row is not None:
            selected_rows.append(row)
    if not selected_rows:
        return {"reply": "Failed to insert the requested words. Please try again."}

    selected_rows = ensure_words_enriched(db, user_id=user_id, words=selected_rows)
    by_lemma = {str(item.get("lemma", "")).lower(): item for item in selected_rows}
    ordered = [by_lemma[lemma] for lemma in requested if lemma in by_lemma]
    if not ordered:
        return {"reply": "Failed to insert the requested words. Please try again."}

    practice_path, practice_meta = build_daily_combo_exercise(
        user_id=user_id,
        words=ordered,
        regenerate=regenerate,
    )
    practice_url = _artifact_url(practice_path)
    hub_path, hub_meta = build_learning_hub(
        user_id=user_id,
        words=ordered,
        practice_url=practice_url,
        regenerate=regenerate,
    )
    hub_url = _artifact_url(hub_path)
    focus_word = ordered[0]["lemma"]

    return {
        "reply": (
            f"Generated a custom learning flow from your requested list: {len(ordered)} words, {inserted} newly added. "
            f"Current priority word: {focus_word}."
        ),
        "links": [hub_url, f"{practice_url}#spell", f"{practice_url}#match"],
        "data": {
            "focus_word": focus_word,
            "word_count": len(ordered),
            "inserted_words": inserted,
            "hub_cached": hub_meta["cached"],
            "practice_cached": practice_meta["cached"],
            "selected_words": [item["lemma"] for item in ordered],
            "source": "custom-word-list",
            "limits": {"new": limits.new_words, "review": limits.reviews},
        },
    }


def _cmd_today(db: Database, user_id: int, limits: DailyLimits) -> dict:
    task = db.get_today_task(user_id, limits)
    review_words = [w["lemma"] for w in task["review"]]
    new_words = [w["lemma"] for w in task["new"]]
    reply = (
        f"Today's plan: {len(review_words)} review words, {len(new_words)} new words.\n"
        f"Review: {', '.join(review_words[:12]) or 'none'}\n"
        f"New: {', '.join(new_words[:12]) or 'none'}"
    )
    return {"reply": reply, "data": task}


def _cmd_review(db: Database, user_id: int, limits: DailyLimits) -> dict:
    task = db.get_today_task(user_id, limits)
    review_words = [w["lemma"] for w in task["review"]]
    if not review_words:
        return {"reply": "No review words are due today. Run /today to see new words."}
    return {"reply": f"Start review: {', '.join(review_words[:15])}"}


def _cmd_words(db: Database, user_id: int) -> dict:
    words = db.list_words(user_id=user_id, limit=200)
    if not words:
        return {"reply": "Vocabulary is still empty. Import a word list first."}

    lines = [
        f"{idx + 1}. {item['lemma']} ({item['status']})"
        for idx, item in enumerate(words[:20])
    ]
    suffix = "" if len(words) <= 20 else f"\n...total {len(words)}, showing first 20."
    return {
        "reply": "Vocabulary words:\n" + "\n".join(lines) + suffix,
        "data": {"count": len(words)},
    }


def _cmd_mistakes(db: Database, user_id: int) -> dict:
    mistakes = db.list_mistakes(user_id=user_id, limit=20)
    if not mistakes:
        return {"reply": "No mistake records yet."}
    lines = [f"{idx + 1}. {m['lemma']} (wrong {m['fail_count']} times)" for idx, m in enumerate(mistakes[:10])]
    return {"reply": "Top mistake words:\n" + "\n".join(lines), "data": mistakes}


def _cmd_fix(db: Database, user_id: int, wrong: str, correct: str) -> dict:
    wrong_norm = wrong.strip().lower()
    correct_norm = correct.strip().lower()
    if not _is_word_token(wrong_norm) or not _is_word_token(correct_norm):
        return {"reply": "Fix failed: please provide valid English words, e.g. /fix antena antenna"}

    target = db.get_word_by_lemma(user_id=user_id, lemma=wrong_norm)
    if target is None:
        return {"reply": f"Word not found: {wrong_norm}. Please confirm it exists in vocabulary."}

    try:
        updated = db.correct_word(
            user_id=user_id,
            word_id=target["id"],
            new_lemma=correct_norm,
            new_surface=correct_norm,
            reason="chat_fix_command",
            corrected_by_role="CHILD",
        )
    except ValueError as exc:
        return {"reply": f"Fix failed: {exc}"}

    return {"reply": f"Updated: {wrong_norm} -> {updated['lemma']}", "data": updated}


def _cmd_game(db: Database, user_id: int, mode: str, *, limits: DailyLimits, regenerate: bool = False) -> dict:
    mapping = {
        "spelling": "SPELL",
        "spell": "SPELL",
        "match": "MATCH",
        "daily": "DAILY",
        "today": "DAILY",
        "combo": "DAILY",
        "dictation": "DICTATION",
        "cloze": "CLOZE",
    }
    session_type = mapping.get(mode, "SPELL")
    task = db.get_today_task(user_id, limits)
    words = _collect_today_learning_pool(task)
    if not words:
        words = db.list_words(user_id=user_id, limit=40)
    if not words:
        return {"reply": "Vocabulary is still empty. Import words before starting practice."}
    words = ensure_words_enriched(db, user_id=user_id, words=words)

    if session_type in {"SPELL", "MATCH", "DAILY"}:
        html_path, meta = build_daily_combo_exercise(
            user_id=user_id,
            words=words,
            regenerate=regenerate,
        )
        mode_hash = "#match" if session_type == "MATCH" else "#spell"
    else:
        html_path, meta = build_exercise(session_type=session_type, words=words)
        mode_hash = ""

    session_id = db.create_exercise_session(
        user_id=user_id,
        session_type=session_type,
        html_path=str(html_path),
        word_ids=[w["id"] for w in words],
    )
    url = _artifact_url(html_path) + mode_hash
    cached_note = "(cache hit)" if meta.get("cached") else "(updated)"
    mode_name = "Spelling + Definition Match" if session_type in {"SPELL", "MATCH", "DAILY"} else session_type
    return {
        "reply": f"{mode_name} is ready. {meta['questions']} items {cached_note}.",
        "links": [url],
        "data": {"session_id": session_id, **meta},
    }


def _cmd_report_week(db: Database, user_id: int) -> dict:
    report = db.weekly_report(user_id)
    html_path, csv_path = render_week_report_files(report)
    return {
        "reply": (
            f"Weekly report ready: new {report['new_words']}, reviews {report['review_count']}, "
            f"accuracy {round(report['accuracy'] * 100)}%, practiced words {len(report.get('word_practice_stats', []))}."
        ),
        "links": [_artifact_url(html_path), _artifact_url(csv_path)],
        "data": report,
    }


def render_week_report_files(report: dict) -> tuple[Path, Path]:
    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    html_path = REPORTS_DIR / f"weekly_{timestamp}.html"
    csv_path = REPORTS_DIR / f"weekly_{timestamp}.csv"

    html_rows = "".join(
        f"<tr><td>{item['lemma']}</td><td>{item['fail_count']}</td><td>{item['spelling_errors']}</td>"
        f"<td>{item['confusion_errors']}</td><td>{item['meaning_errors']}</td></tr>"
        for item in report["mistakes_top20"]
    )
    practice_rows = "".join(
        f"<tr><td>{item['lemma']}</td><td>{item['status']}</td><td>{item['practice_total']}</td>"
        f"<td>{item['correct_count']}</td><td>{round(item['accuracy']*100)}%</td>"
        f"<td>{item['spelling_total']}</td><td>{item['match_total']}</td></tr>"
        for item in report.get("word_practice_stats", [])
    )
    if not practice_rows:
        practice_rows = "<tr><td colspan='7'>No spelling/definition-match practice records this week.</td></tr>"
    html = f"""<!DOCTYPE html>
<html lang=\"en\"><head><meta charset=\"UTF-8\"><title>Weekly Report</title>
<style>
body{{font-family:'Avenir Next',Arial,sans-serif;background:#f8fafc;color:#102a43;padding:20px;}}
.card{{background:#fff;border:1px solid #d7e2ec;border-radius:12px;padding:18px;max-width:980px;margin:auto;}}
table{{width:100%;border-collapse:collapse;margin-top:10px;}}
th,td{{border:1px solid #d7e2ec;padding:8px;text-align:left;}}
</style></head><body>
<div class=\"card\"><h1>Weekly Report</h1>
<p>New words: {report['new_words']} | Review count: {report['review_count']} | Avg accuracy: {round(report['accuracy']*100)}%</p>
<p>Mastered words: {report['mastered_words']} | Study streak days: {report['study_streak_days']}</p>
<h3>Word Practice Stats (Spelling + Definition Match)</h3>
<table><thead><tr><th>Word</th><th>Status</th><th>Total Attempts</th><th>Correct</th><th>Accuracy</th><th>Spelling</th><th>Definition Match</th></tr></thead>
<tbody>{practice_rows}</tbody></table>
<h3>Top 20 Mistake Words</h3>
<table><thead><tr><th>Word</th><th>Total Wrong</th><th>Spelling</th><th>Confusion</th><th>Meaning</th></tr></thead>
<tbody>{html_rows}</tbody></table>
<h3>Suggestions for Next Week</h3>
<p>Daily new-word limit: {report['next_week_suggestion']['daily_new_limit']}</p>
<p>Review ratio: {report['next_week_suggestion']['review_ratio']}</p>
<p>Focus words: {', '.join(report['next_week_suggestion']['focus_words']) or 'none'}</p>
</div></body></html>"""
    html_path.write_text(html, encoding="utf-8")

    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "section",
                "lemma",
                "status",
                "practice_total",
                "correct_count",
                "accuracy",
                "spelling_total",
                "match_total",
                "fail_count",
                "spelling_errors",
                "confusion_errors",
                "meaning_errors",
                "pronunciation_errors",
            ]
        )
        for item in report.get("word_practice_stats", []):
            writer.writerow(
                [
                    "practice",
                    item["lemma"],
                    item["status"],
                    item["practice_total"],
                    item["correct_count"],
                    round(item["accuracy"], 3),
                    item["spelling_total"],
                    item["match_total"],
                    "",
                    "",
                    "",
                    "",
                    "",
                ]
            )
        for item in report["mistakes_top20"]:
            writer.writerow(
                [
                    "mistake",
                    item["lemma"],
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    item["fail_count"],
                    item["spelling_errors"],
                    item["confusion_errors"],
                    item["meaning_errors"],
                    item["pronunciation_errors"],
                ]
            )

    return html_path, csv_path


def _collect_today_learning_pool(task: dict) -> list[dict]:
    review = list(task.get("review") or [])
    new_words = list(task.get("new") or [])
    return review + new_words


def _rank_learning_words(db: Database, user_id: int, words: list[dict]) -> list[dict]:
    mistake_rows = db.list_mistakes(user_id=user_id, limit=200)
    fail_counts = {row["lemma"]: int(row.get("fail_count", 0) or 0) for row in mistake_rows}

    def score(item: dict) -> float:
        lemma = str(item.get("lemma", "")).lower()
        status = str(item.get("status", "NEW")).upper()
        lapses = int(item.get("lapses", 0) or 0)
        streak = int(item.get("streak", 0) or 0)
        fail_count = fail_counts.get(lemma, 0)
        base = 10 if status in {"LEARNING", "REVIEWING"} else 6 if status == "NEW" else 2
        return base + fail_count * 2.5 + lapses * 1.8 - streak * 0.6

    ranked = sorted(words, key=score, reverse=True)
    return ranked


def _last_english_token(text: str) -> str | None:
    tokens = text.replace("?", " ").replace("！", " ").replace("，", " ").split()
    for tok in reversed(tokens):
        if tok.isascii() and tok.isalpha():
            return tok.lower()
    return None


def _artifact_url(path: Path) -> str:
    rel = path.relative_to(ARTIFACTS_DIR)
    return "/artifacts/" + str(rel).replace("\\", "/")


def _is_word_token(token: str) -> bool:
    return bool(re.fullmatch(r"[a-zA-Z][a-zA-Z'-]{0,32}", token))


def _parse_learn_words_from_command(command: str) -> list[str]:
    compact = " ".join(str(command or "").split())
    parts = compact.split()
    lowered_parts = [part.lower() for part in parts]
    if "--words" not in lowered_parts:
        return []
    idx = lowered_parts.index("--words")
    collected: list[str] = []
    for part in parts[idx + 1 :]:
        if part.startswith("--"):
            break
        collected.append(part)
    if not collected:
        return []
    raw_tokens = re.findall(r"[A-Za-z][A-Za-z'-]{1,32}", " ".join(collected))
    return _normalize_learning_words(raw_tokens)


def _normalize_learning_words(tokens: list[str]) -> list[str]:
    words: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        normalized = simple_lemma(str(token or "").strip().lower())
        if not normalized:
            continue
        if not _is_word_token(normalized):
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        words.append(normalized)
    return words


def _ensure_words_in_vocabulary(db: Database, *, user_id: int, words: list[str]) -> int:
    missing = [lemma for lemma in words if db.get_word_by_lemma(user_id=user_id, lemma=lemma) is None]
    if not missing:
        return 0

    import_id = db.create_import(
        user_id=user_id,
        source_type="TEXT",
        source_name="chat_custom_word_list",
        source_path=None,
        importer_role="CHILD",
        tags=["custom-learn"],
        note="added from chat custom learn words",
    )
    db.add_import_items(
        import_id,
        [
            {
                "word_candidate": lemma,
                "suggested_correction": lemma,
                "confidence": 1.0,
                "needs_confirmation": 0,
                "accepted": 1,
                "final_lemma": lemma,
            }
            for lemma in missing
        ],
    )
    return db.commit_import(import_id)
