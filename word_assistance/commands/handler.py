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
        return {"reply": "你可以先输入 /today 看今日任务。"}

    check = validate_child_request(message)
    if not check.allowed:
        return {"reply": check.reason}

    if message.startswith("/"):
        return _handle_command(db, user_id, message, limits)

    custom_words = _normalize_learning_words(extract_custom_learning_words(message))
    if custom_words:
        return _cmd_learn_with_words(db, user_id, limits, custom_words, regenerate=False)

    lowered = message.lower()
    if "开始学习" in message or "学习词库" in message or "开始背单词" in message:
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
                "reply": f"我先给你做了 {word} 的 Kids 卡。下一步可以继续生成 Museum 卡。",
                "links": [card["url"]],
            }
        card = generate_dictionary_card(word=word, regenerate=False)
        return {
            "reply": f"{word} 当前不在词库中。我先生成了查阅卡（不会自动入库），需要的话可在查词页点击“加入词库”。",
            "links": [card["url"]],
        }

    return {
        "reply": "我能帮你做这些：/learn /today /words /review /card <word> /game spelling /game match /report week",
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
            return {"reply": "用法: /fix wrong correct，例如 /fix antena antenna"}
        return _cmd_fix(db, user_id=user_id, wrong=parts[1], correct=parts[2])
    if cmd == "/card":
        if len(parts) < 2:
            return {"reply": "用法: /card antenna"}
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
            info = "已返回历史版本" if card["cached"] else "已生成新版本"
            return {"reply": f"{info} Museum 卡片：{normalized}", "links": [card["url"]]}
        card = generate_dictionary_card(word=normalized, regenerate=regenerate)
        info = "已返回历史版本" if card["cached"] else "已生成新版本"
        return {
            "reply": f"{info} 查阅卡：{normalized}（当前未入词库，未自动新增）",
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
            "暂不支持该命令。可用命令: "
            "/learn /learn --words appraise,bolster /today /words /review /new 8 /mistakes "
            "/fix wrong correct /card /game spelling|match|daily /report week"
        )
    }


def _cmd_learn(db: Database, user_id: int, limits: DailyLimits, *, regenerate: bool = False) -> dict:
    task = db.get_today_task(user_id, limits)
    learning_pool = _collect_today_learning_pool(task)
    if not learning_pool:
        return {
            "reply": "词库暂时为空。先上传单词后，我可以自动生成卡片和练习。"
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
            f"学习链路已准备好：左侧单词列表 + 右侧词卡工作台（共 {len(ranked)} 词），"
            f"并已连接今日拼写/释义匹配练习。排序已按历史错题与复习状态自适应优化，当前优先词：{focus_word}。"
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
        return {"reply": "没有识别到有效单词，请用英文单词列表重试。"}

    inserted = _ensure_words_in_vocabulary(db, user_id=user_id, words=requested)
    selected_rows: list[dict] = []
    for lemma in requested:
        row = db.get_word_by_lemma(user_id=user_id, lemma=lemma)
        if row is not None:
            selected_rows.append(row)
    if not selected_rows:
        return {"reply": "指定单词暂未成功入库，请重试。"}

    selected_rows = ensure_words_enriched(db, user_id=user_id, words=selected_rows)
    by_lemma = {str(item.get("lemma", "")).lower(): item for item in selected_rows}
    ordered = [by_lemma[lemma] for lemma in requested if lemma in by_lemma]
    if not ordered:
        return {"reply": "指定单词暂未成功入库，请重试。"}

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
            f"已按你的指定单词生成学习链路：共 {len(ordered)} 词，新增入库 {inserted} 词。"
            f"当前优先词：{focus_word}。"
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
        f"今日任务：复习 {len(review_words)} 个，新词 {len(new_words)} 个。\n"
        f"复习词：{', '.join(review_words[:12]) or '暂无'}\n"
        f"新词：{', '.join(new_words[:12]) or '暂无'}"
    )
    return {"reply": reply, "data": task}


def _cmd_review(db: Database, user_id: int, limits: DailyLimits) -> dict:
    task = db.get_today_task(user_id, limits)
    review_words = [w["lemma"] for w in task["review"]]
    if not review_words:
        return {"reply": "今天到期复习词为 0，可以先输入 /today 看新词任务。"}
    return {"reply": f"开始复习：{', '.join(review_words[:15])}"}


def _cmd_words(db: Database, user_id: int) -> dict:
    words = db.list_words(user_id=user_id, limit=200)
    if not words:
        return {"reply": "词库还是空的，先上传一批单词吧。"}

    lines = [
        f"{idx + 1}. {item['lemma']} ({item['status']})"
        for idx, item in enumerate(words[:20])
    ]
    suffix = "" if len(words) <= 20 else f"\n...共 {len(words)} 个，已展示前 20 个。"
    return {
        "reply": "词库单词如下：\n" + "\n".join(lines) + suffix,
        "data": {"count": len(words)},
    }


def _cmd_mistakes(db: Database, user_id: int) -> dict:
    mistakes = db.list_mistakes(user_id=user_id, limit=20)
    if not mistakes:
        return {"reply": "目前还没有错题记录。"}
    lines = [f"{idx + 1}. {m['lemma']} (错 {m['fail_count']} 次)" for idx, m in enumerate(mistakes[:10])]
    return {"reply": "常错词 Top:\n" + "\n".join(lines), "data": mistakes}


def _cmd_fix(db: Database, user_id: int, wrong: str, correct: str) -> dict:
    wrong_norm = wrong.strip().lower()
    correct_norm = correct.strip().lower()
    if not _is_word_token(wrong_norm) or not _is_word_token(correct_norm):
        return {"reply": "修正失败：请输入英文单词，例如 /fix antena antenna"}

    target = db.get_word_by_lemma(user_id=user_id, lemma=wrong_norm)
    if target is None:
        return {"reply": f"没有找到单词 {wrong_norm}，请先确认词库中是否存在。"}

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
        return {"reply": f"修正失败：{exc}"}

    return {"reply": f"已修正：{wrong_norm} -> {updated['lemma']}", "data": updated}


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
        return {"reply": "词库还是空的，先上传单词再开始练习。"}
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
    cached_note = "（缓存命中）" if meta.get("cached") else "（已更新）"
    mode_name = "拼写+释义匹配联合练习" if session_type in {"SPELL", "MATCH", "DAILY"} else session_type
    return {
        "reply": f"{mode_name}已准备好，题量 {meta['questions']} 题{cached_note}。",
        "links": [url],
        "data": {"session_id": session_id, **meta},
    }


def _cmd_report_week(db: Database, user_id: int) -> dict:
    report = db.weekly_report(user_id)
    html_path, csv_path = render_week_report_files(report)
    return {
        "reply": (
            f"周报完成：新增 {report['new_words']}，复习 {report['review_count']}，"
            f"正确率 {round(report['accuracy'] * 100)}%，练习词 {len(report.get('word_practice_stats', []))} 个。"
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
        practice_rows = "<tr><td colspan='7'>本周暂无拼写/释义匹配练习记录</td></tr>"
    html = f"""<!DOCTYPE html>
<html lang=\"zh-CN\"><head><meta charset=\"UTF-8\"><title>Weekly Report</title>
<style>
body{{font-family:'Avenir Next',Arial,sans-serif;background:#f8fafc;color:#102a43;padding:20px;}}
.card{{background:#fff;border:1px solid #d7e2ec;border-radius:12px;padding:18px;max-width:980px;margin:auto;}}
table{{width:100%;border-collapse:collapse;margin-top:10px;}}
th,td{{border:1px solid #d7e2ec;padding:8px;text-align:left;}}
</style></head><body>
<div class=\"card\"><h1>周报</h1>
<p>新增词数: {report['new_words']} | 复习次数: {report['review_count']} | 平均正确率: {round(report['accuracy']*100)}%</p>
<p>掌握词数: {report['mastered_words']} | 连续学习天数: {report['study_streak_days']}</p>
<h3>单词练习统计（拼写 + 释义匹配）</h3>
<table><thead><tr><th>单词</th><th>状态</th><th>练习总次数</th><th>正确次数</th><th>正确率</th><th>拼写次数</th><th>释义匹配次数</th></tr></thead>
<tbody>{practice_rows}</tbody></table>
<h3>常错词 Top20</h3>
<table><thead><tr><th>单词</th><th>错误次数</th><th>拼写</th><th>混淆</th><th>释义</th></tr></thead>
<tbody>{html_rows}</tbody></table>
<h3>下周建议</h3>
<p>每日新词上限: {report['next_week_suggestion']['daily_new_limit']}</p>
<p>复习占比: {report['next_week_suggestion']['review_ratio']}</p>
<p>重点词: {', '.join(report['next_week_suggestion']['focus_words']) or '暂无'}</p>
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
