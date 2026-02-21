from __future__ import annotations

import base64
import binascii
import csv
import math
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from word_assistance.api.schemas import (
    CardRequest,
    ChatRequest,
    DictionaryAddRequest,
    ExerciseRequest,
    HandwritingRecognizeRequest,
    ImportCommitRequest,
    ParentSettingsUpdateRequest,
    ReviewRequest,
    TTSRequest,
    TextImportRequest,
    WordCorrectionRequest,
    WordStatusUpdateRequest,
)
from word_assistance.cards.generator import generate_card, generate_dictionary_card
from word_assistance.commands.handler import handle_chat_message, render_week_report_files
from word_assistance.config import (
    ARTIFACTS_DIR,
    AUDIO_DIR,
    EXPORTS_DIR,
    PROJECT_ROOT,
    UPLOADS_DIR,
    ensure_dirs,
)
from word_assistance.pipeline.importer import (
    build_import_preview_from_file,
    build_import_preview_from_text,
)
from word_assistance.pipeline.extraction import extract_normalized_tokens, extract_text_from_bytes, simple_lemma
from word_assistance.scheduler.srs import next_state, state_from_row
from word_assistance.services.backup import create_backup_bundle, restore_backup_bundle
from word_assistance.services.llm import LLMRoute, LLMService
from word_assistance.services.openclaw import OpenClawAgentService
from word_assistance.services.speech import SpeechService
from word_assistance.storage.db import Database, ReviewResult

UTC = timezone.utc
ORCHESTRATION_MODES = {"OPENCLAW_PREFERRED", "LOCAL_ONLY", "OPENCLAW_ONLY"}

db = Database()
llm_service = LLMService()
speech_service = SpeechService()
openclaw_service = OpenClawAgentService()
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "templates"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_dirs()
    db.initialize()
    yield


app = FastAPI(title="Word Assistance MVP", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "static")), name="static")
app.mount("/artifacts", StaticFiles(directory=str(ARTIFACTS_DIR)), name="artifacts")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/openclaw/status")
def openclaw_status(child_user_id: int = Query(default=2)) -> dict:
    settings = db.get_parent_settings(child_user_id)
    mode = _normalize_orchestration_mode(settings.get("orchestration_mode"))
    return {"ok": True, "mode": mode, **openclaw_service.status()}


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>"
        "<rect width='64' height='64' rx='14' fill='#0f6d53'/>"
        "<text x='32' y='42' text-anchor='middle' font-size='34' fill='white' font-family='Arial'>W</text>"
        "</svg>"
    )
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/dictionary", response_class=HTMLResponse)
def dictionary(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("dictionary.html", {"request": request})


@app.get("/api/today")
def today(
    user_id: int = Query(default=2),
    new_limit: int | None = Query(default=None),
    review_limit: int | None = Query(default=None),
) -> dict:
    limits = db.get_daily_limits(user_id)
    if new_limit is not None:
        limits = type(limits)(new_words=new_limit, reviews=limits.reviews)
    if review_limit is not None:
        limits = type(limits)(new_words=limits.new_words, reviews=review_limit)

    task = db.get_today_task(user_id=user_id, limits=limits)
    return {"ok": True, "task": task, "limits": {"new": limits.new_words, "review": limits.reviews}}


@app.get("/api/words")
def words(
    user_id: int = Query(default=2),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=15, ge=1, le=200),
    limit: int | None = Query(default=None, ge=1, le=500),
) -> dict:
    if limit is not None:
        page = 1
        page_size = int(limit)

    statuses = _resolve_word_status_filters(status)
    total = db.count_words(user_id=user_id, statuses=statuses)
    total_pages = max(1, math.ceil(total / page_size)) if total else 1
    page = min(page, total_pages)
    offset = (page - 1) * page_size
    items = db.list_words(
        user_id=user_id,
        statuses=statuses,
        limit=page_size,
        offset=offset,
    )
    return {
        "ok": True,
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "status_filter": status or "ALL",
    }


@app.get("/api/learn/card-url")
def learn_card_url(
    word: str = Query(...),
    user_id: int = Query(default=2),
    regenerate: int = Query(default=0),
) -> dict:
    normalized = word.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="word is empty")
    try:
        card = generate_card(
            db=db,
            user_id=user_id,
            word=normalized,
            card_type="MUSEUM",
            regenerate=bool(regenerate),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, **card}


@app.post("/api/words/{word_id}/correct")
def correct_word(word_id: int, req: WordCorrectionRequest) -> dict:
    try:
        updated = db.correct_word(
            user_id=req.user_id,
            word_id=word_id,
            new_lemma=req.new_lemma,
            new_surface=req.new_surface,
            reason=req.reason,
            corrected_by_role=req.corrected_by_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {"ok": True, "word": updated}


@app.post("/api/words/{word_id}/status")
def update_word_status(word_id: int, req: WordStatusUpdateRequest) -> dict:
    try:
        normalized_status = _normalize_word_status_for_update(req.status)
        updated = db.set_word_status(
            user_id=req.user_id,
            word_id=word_id,
            status=normalized_status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "word": updated}


@app.delete("/api/words/{word_id}")
def delete_word(
    word_id: int,
    user_id: int = Query(default=2),
    deleted_by_role: str = Query(default="CHILD"),
) -> dict:
    try:
        deleted = db.delete_word(
            user_id=user_id,
            word_id=word_id,
            deleted_by_role=deleted_by_role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "word": deleted}


@app.get("/api/words/corrections")
def word_corrections(user_id: int = Query(default=2), limit: int = Query(default=50)) -> dict:
    return {"ok": True, "items": db.list_word_corrections(user_id=user_id, limit=limit)}


@app.get("/api/dictionary/card")
def dictionary_card(
    word: str = Query(...),
    user_id: int = Query(default=2),
    regenerate: int = Query(default=0),
) -> dict:
    normalized = word.strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="word is empty")

    in_vocab = db.get_word_by_lemma(user_id=user_id, lemma=normalized)
    if in_vocab:
        card = generate_card(
            db=db,
            user_id=user_id,
            word=normalized,
            card_type="MUSEUM",
            regenerate=bool(regenerate),
        )
        return {
            "ok": True,
            "word": normalized,
            "in_vocab": True,
            "source": "vocab",
            **card,
        }

    card = generate_dictionary_card(
        word=normalized,
        regenerate=bool(regenerate),
    )
    return {
        "ok": True,
        "word": normalized,
        "in_vocab": False,
        "source": "lookup-cache",
        **card,
    }


@app.post("/api/dictionary/add")
def dictionary_add(req: DictionaryAddRequest) -> dict:
    normalized = req.word.strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="word is empty")

    existing = db.get_word_by_lemma(user_id=req.user_id, lemma=normalized)
    added = False
    if existing is None:
        import_id = db.create_import(
            user_id=req.user_id,
            source_type="MANUAL",
            source_name="dictionary_lookup",
            source_path=None,
            importer_role="CHILD",
            tags=req.tags or ["dictionary"],
            note="added from dictionary lookup page",
        )
        db.add_import_items(
            import_id,
            [
                {
                    "word_candidate": normalized,
                    "suggested_correction": normalized,
                    "confidence": 1.0,
                    "needs_confirmation": 0,
                    "accepted": 1,
                    "final_lemma": normalized,
                }
            ],
        )
        db.commit_import(import_id)
        added = True

    word_row = db.get_word_by_lemma(user_id=req.user_id, lemma=normalized)
    if word_row is None:
        raise HTTPException(status_code=500, detail="failed to add word into vocabulary")
    card = generate_card(
        db=db,
        user_id=req.user_id,
        word=normalized,
        card_type="MUSEUM",
        regenerate=False,
    )
    return {
        "ok": True,
        "added": added,
        "word": word_row,
        "card_url": card["url"],
    }


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    settings = db.get_parent_settings(req.user_id)
    limits = db.get_daily_limits(req.user_id)
    mode = _normalize_orchestration_mode(settings.get("orchestration_mode"))
    strict_mode = bool(settings.get("strict_mode"))
    llm_enabled = bool(settings.get("llm_enabled"))

    message = req.message.strip()
    if not message:
        return {"ok": True, "reply": "You can start with: show me today's plan."}

    # Explicit slash commands are executed locally unless user enforces OPENCLAW_ONLY.
    if message.startswith("/") and mode != "OPENCLAW_ONLY":
        return _chat_local(
            message=message,
            user_id=req.user_id,
            limits=limits,
            strict_mode=strict_mode,
            llm_enabled=llm_enabled,
            precomputed_route=None,
        )

    precomputed_route: LLMRoute | None = None
    if not message.startswith("/"):
        precomputed_route = llm_service.route_message(
            message,
            strict_mode=strict_mode,
            llm_enabled=llm_enabled,
        )

    if mode != "LOCAL_ONLY":
        openclaw_turn = openclaw_service.run_turn(user_id=req.user_id, message=message)
        if openclaw_turn is not None:
            action_fallback_route = _resolve_action_fallback_route(
                message=message,
                strict_mode=strict_mode,
                base_route=precomputed_route,
            )
            if mode == "OPENCLAW_PREFERRED" and (
                _should_force_local_execution(
                    route=action_fallback_route,
                    openclaw_reply=openclaw_turn.reply,
                    openclaw_links=openclaw_turn.links,
                )
                or (_message_has_learning_action_intent(message) and not openclaw_turn.links)
            ):
                fallback_route = action_fallback_route if action_fallback_route and action_fallback_route.command else precomputed_route
                return _chat_local(
                    message=message,
                    user_id=req.user_id,
                    limits=limits,
                    strict_mode=strict_mode,
                    llm_enabled=llm_enabled,
                    precomputed_route=fallback_route,
                )

            route_command = action_fallback_route.command if action_fallback_route else (message if message.startswith("/") else None)
            return {
                "ok": True,
                "reply": openclaw_turn.reply,
                "links": openclaw_turn.links,
                "route_source": "openclaw",
                "route_command": route_command,
            }

        if mode == "OPENCLAW_ONLY":
            return {
                "ok": True,
                "reply": "OpenClaw is currently unavailable. Please try again later, or switch to Local Only mode in Parent Settings.",
                "route_source": "openclaw_unavailable",
                "route_command": precomputed_route.command if precomputed_route else (message if message.startswith("/") else None),
            }

    return _chat_local(
        message=message,
        user_id=req.user_id,
        limits=limits,
        strict_mode=strict_mode,
        llm_enabled=llm_enabled,
        precomputed_route=precomputed_route,
    )


def _chat_local(
    *,
    message: str,
    user_id: int,
    limits,
    strict_mode: bool,
    llm_enabled: bool,
    precomputed_route: LLMRoute | None = None,
) -> dict:
    if message.startswith("/"):
        result = handle_chat_message(db=db, user_id=user_id, message=message, limits=limits)
        return {"ok": True, **result, "route_source": "direct", "route_command": message}

    route = precomputed_route or llm_service.route_message(
        message,
        strict_mode=strict_mode,
        llm_enabled=llm_enabled,
    )

    if route.command:
        command_result = handle_chat_message(db=db, user_id=user_id, message=route.command, limits=limits)
        reply = command_result.get("reply") or "Done."
        if route.reply and route.reply not in reply:
            reply = f"{route.reply}\n{reply}"
        return {
            "ok": True,
            **command_result,
            "reply": reply,
            "route_source": route.source,
            "route_command": route.command,
        }

    if route.source == "llm":
        fallback_reply = llm_service.chat_reply(message, strict_mode=strict_mode)
        return {"ok": True, "reply": fallback_reply, "route_source": route.source, "route_command": None}

    return {"ok": True, "reply": route.reply, "route_source": route.source, "route_command": None}


def _normalize_orchestration_mode(value: object) -> str:
    mode = str(value or "OPENCLAW_PREFERRED").strip().upper()
    if mode not in ORCHESTRATION_MODES:
        return "OPENCLAW_PREFERRED"
    return mode


def _should_force_local_execution(
    *,
    route: LLMRoute | None,
    openclaw_reply: str,
    openclaw_links: list[str] | None,
) -> bool:
    if route is None or not route.command:
        return False
    if openclaw_links:
        return False
    if _looks_non_operational_openclaw_reply(openclaw_reply):
        return True
    # Guardrail: if OpenClaw produced text-only answer for an executable intent, run local action to guarantee delivery.
    return True


def _looks_non_operational_openclaw_reply(reply: str) -> bool:
    lowered = (reply or "").lower()
    needles = (
        "无法访问",
        "无法直接",
        "抱歉",
        "请告诉我",
        "give me",
        "cannot access",
        "can't access",
        "unable to access",
    )
    return any(token in lowered for token in needles)


def _resolve_action_fallback_route(
    *,
    message: str,
    strict_mode: bool,
    base_route: LLMRoute | None,
) -> LLMRoute | None:
    if base_route and base_route.command:
        return base_route
    if _message_has_learning_action_intent(message):
        return llm_service.heuristic_route(message, strict_mode=strict_mode)
    return base_route


def _message_has_learning_action_intent(message: str) -> bool:
    text = message.strip().lower()
    keywords = (
        "今天任务",
        "今日任务",
        "开始学习",
        "学习词库",
        "单词库",
        "拼写",
        "spell",
        "match",
        "匹配",
        "听写",
        "dictation",
        "卡片",
        "museum",
        "report",
        "周报",
        "mistake",
        "常错",
        "learn these words",
        "today i want to learn",
        "today's words",
    )
    return any(token in text for token in keywords)


@app.post("/api/import/text")
def import_text(req: TextImportRequest) -> dict:
    settings = db.get_parent_settings(req.user_id)
    options = _import_options_from_settings(settings)
    items = build_import_preview_from_text(
        req.text,
        auto_accept_threshold=options["auto_accept_threshold"],
        source_type="TEXT",
        source_name=req.source_name,
    )
    import_id = db.create_import(
        user_id=req.user_id,
        source_type="TEXT",
        source_name=req.source_name,
        source_path=None,
        importer_role=req.importer_role,
        tags=req.tags,
        note=req.note,
    )
    db.add_import_items(import_id, items)
    return {
        "ok": True,
        "import_id": import_id,
        "preview_items": db.list_import_items(import_id),
        "requires_confirmation": sum(1 for item in items if item["needs_confirmation"]),
        "import_profile": options,
        "selection_mode": "standard",
    }


@app.post("/api/import/file")
async def import_file(
    user_id: int = Form(default=2),
    importer_role: str = Form(default="CHILD"),
    tags: str = Form(default=""),
    note: str | None = Form(default=None),
    file: UploadFile = File(...),
) -> dict:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty file")

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    safe_name = file.filename.replace("/", "_") if file.filename else "upload.bin"
    output_path = UPLOADS_DIR / f"{timestamp}_{safe_name}"
    output_path.write_bytes(payload)

    settings = db.get_parent_settings(user_id)
    options = _import_options_from_settings(settings)
    extracted_text, items = build_import_preview_from_file(
        filename=safe_name,
        payload=payload,
        ocr_strength=options["ocr_strength"],
        auto_accept_threshold=options["auto_accept_threshold"],
    )
    source_type = _source_type_from_filename(safe_name)

    import_id = db.create_import(
        user_id=user_id,
        source_type=source_type,
        source_name=safe_name,
        source_path=str(output_path),
        importer_role=importer_role,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
        note=note,
    )
    db.add_import_items(import_id, items)

    return {
        "ok": True,
        "import_id": import_id,
        "source_type": source_type,
        "preview_items": db.list_import_items(import_id),
        "extracted_text_sample": extracted_text[:800],
        "import_profile": options,
        "selection_mode": "smart" if source_type in {"IMAGE", "PDF"} else "standard",
    }


@app.post("/api/import/commit")
def commit_import(req: ImportCommitRequest) -> dict:
    items = db.list_import_items(req.import_id)
    chosen = set(req.accepted_item_ids)
    if chosen:
        for item in items:
            db.update_import_item_acceptance(
                import_item_id=item["id"],
                accepted=item["id"] in chosen,
                final_lemma=item.get("final_lemma") or item.get("suggested_correction"),
            )
    inserted = db.commit_import(req.import_id)
    return {"ok": True, "imported_words": inserted}


@app.post("/api/review")
def review(req: ReviewRequest) -> dict:
    word = db.get_word(req.word_id)
    if not word or word["user_id"] != req.user_id:
        raise HTTPException(status_code=404, detail="word not found")

    db.save_review(
        ReviewResult(
            word_id=req.word_id,
            result="PASS" if req.passed else "FAIL",
            mode=req.mode.upper(),
            error_type=req.error_type.upper(),
            user_answer=req.user_answer,
            correct_answer=req.correct_answer,
            latency_ms=req.latency_ms,
        )
    )

    prev = state_from_row(db.get_srs_state(req.word_id))
    update = next_state(prev, passed=req.passed)
    db.save_srs_state(
        word_id=req.word_id,
        last_review_at=update.state.last_review_at,
        next_review_at=update.state.next_review_at or datetime.now(UTC).isoformat(),
        ease=update.state.ease,
        interval_days=update.state.interval_days,
        streak=update.state.streak,
        lapses=update.state.lapses,
    )
    db.update_word_status(req.word_id, update.status)

    return {"ok": True, "next_review_at": update.state.next_review_at, "status": update.status}


@app.post("/api/card/{word}")
def card(word: str, req: CardRequest) -> dict:
    normalized = word.strip().lower()
    if not normalized:
        raise HTTPException(status_code=400, detail="word is empty")

    word_row = db.get_word_by_lemma(user_id=req.user_id, lemma=normalized)
    if not word_row:
        result = generate_dictionary_card(word=normalized, regenerate=req.regenerate)
        return {
            "ok": True,
            "in_vocab": False,
            "source": "lookup-cache",
            **result,
        }

    result = generate_card(
        db=db,
        user_id=req.user_id,
        word=normalized,
        card_type=req.card_type,
        regenerate=req.regenerate,
    )
    return {"ok": True, "in_vocab": True, **result}


@app.post("/api/exercise")
def exercise(req: ExerciseRequest) -> dict:
    mode = req.mode.lower()
    response = handle_chat_message(db=db, user_id=req.user_id, message=f"/game {mode}", limits=db.get_daily_limits(req.user_id))
    return {"ok": True, **response}


@app.get("/api/report/week")
def report_week(user_id: int = Query(default=2)) -> dict:
    report = db.weekly_report(user_id)
    html_path, csv_path = render_week_report_files(report)
    return {
        "ok": True,
        "report": report,
        "html_url": "/artifacts/" + str(html_path.relative_to(ARTIFACTS_DIR)).replace("\\", "/"),
        "csv_url": "/artifacts/" + str(csv_path.relative_to(ARTIFACTS_DIR)).replace("\\", "/"),
    }


@app.get("/api/parent/settings")
def parent_settings(child_user_id: int = Query(default=2)) -> dict:
    return {"ok": True, "settings": db.get_parent_settings(child_user_id)}


@app.put("/api/parent/settings")
def update_parent_settings(req: ParentSettingsUpdateRequest) -> dict:
    payload = req.model_dump(exclude_none=True)
    child_user_id = payload.pop("child_user_id", 2)
    settings = db.update_parent_settings(child_user_id=child_user_id, settings=payload)
    return {"ok": True, "settings": settings}


@app.post("/api/parent/backup")
def parent_backup() -> dict:
    bundle = create_backup_bundle()
    return {
        "ok": True,
        "backup_url": "/artifacts/" + str(bundle.relative_to(ARTIFACTS_DIR)).replace("\\", "/"),
    }


@app.post("/api/parent/restore")
async def parent_restore(file: UploadFile = File(...)) -> dict:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty backup file")
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    path = ARTIFACTS_DIR / "backups" / f"restore_{ts}.zip"
    path.write_bytes(payload)
    restore_backup_bundle(path)
    db.initialize()
    return {"ok": True, "message": "restore completed"}


@app.get("/api/parent/export/words")
def export_words(user_id: int = Query(default=2), fmt: str = Query(default="csv")) -> dict:
    fmt = fmt.lower()
    records = db.export_words(user_id)
    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S")

    if fmt == "xlsx":
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise HTTPException(status_code=500, detail="openpyxl is required for xlsx export") from exc

        out = EXPORTS_DIR / f"words_{ts}.xlsx"
        wb = Workbook()
        ws = wb.active
        ws.title = "words"
        ws.append(["lemma", "surface", "status", "accuracy", "next_review_at", "tags", "meaning_zh", "meaning_en", "examples"])
        for item in records:
            ws.append(
                [
                    item["lemma"],
                    item["surface"],
                    item["status"],
                    item["accuracy"],
                    item.get("next_review_at") or "",
                    "|".join(item["tags"]),
                    "|".join(item["meaning_zh"]),
                    "|".join(item["meaning_en"]),
                    "|".join(item["examples"]),
                ]
            )
        wb.save(out)
    else:
        out = EXPORTS_DIR / f"words_{ts}.csv"
        with out.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["lemma", "surface", "status", "accuracy", "next_review_at", "tags", "meaning_zh", "meaning_en", "examples"])
            for item in records:
                writer.writerow(
                    [
                        item["lemma"],
                        item["surface"],
                        item["status"],
                        item["accuracy"],
                        item.get("next_review_at") or "",
                        "|".join(item["tags"]),
                        "|".join(item["meaning_zh"]),
                        "|".join(item["meaning_en"]),
                        "|".join(item["examples"]),
                    ]
                )

    return {
        "ok": True,
        "url": "/artifacts/" + str(out.relative_to(ARTIFACTS_DIR)).replace("\\", "/"),
        "count": len(records),
        "format": fmt,
    }


@app.get("/api/speech/voices")
def speech_voices() -> dict:
    return {"ok": True, "voices": speech_service.list_voices()}


@app.post("/api/speech/stt")
async def speech_stt(file: UploadFile = File(...)) -> dict:
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="empty audio")

    ts = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    name = file.filename or f"record_{ts}.webm"
    path = AUDIO_DIR / f"stt_{ts}_{name.replace('/', '_')}"
    path.write_bytes(payload)

    try:
        transcript = speech_service.transcribe(path, filename=name)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"STT unavailable: {exc}") from exc

    return {"ok": True, "text": transcript}


@app.post("/api/speech/tts")
async def speech_tts(req: TTSRequest) -> dict:
    try:
        out = await speech_service.synthesize(text=req.text, accent=req.accent, voice=req.voice)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"TTS unavailable: {exc}") from exc

    return {
        "ok": True,
        "audio_url": "/artifacts/" + str(out.relative_to(ARTIFACTS_DIR)).replace("\\", "/"),
    }


@app.post("/api/handwriting/recognize")
def handwriting_recognize(req: HandwritingRecognizeRequest) -> dict:
    raw = str(req.image_data_url or "").strip()
    if not raw.startswith("data:image/") or "," not in raw:
        raise HTTPException(status_code=400, detail="invalid image_data_url")

    try:
        b64 = raw.split(",", 1)[1]
        payload = base64.b64decode(b64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=400, detail="invalid base64 image payload") from exc

    if not payload:
        return {"ok": True, "text": "", "candidates": []}

    text = extract_text_from_bytes("handwriting.png", payload, ocr_strength="ACCURATE")
    candidates: list[str] = []
    seen: set[str] = set()
    for token in extract_normalized_tokens(text):
        lemma = simple_lemma(str(token or "").strip().lower())
        if not lemma or lemma in seen:
            continue
        if not _is_ascii_word(lemma):
            continue
        seen.add(lemma)
        candidates.append(lemma)
        if len(candidates) >= 5:
            break
    return {"ok": True, "text": (candidates[0] if candidates else ""), "candidates": candidates}


def _source_type_from_filename(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".heic", ".bmp", ".webp"}:
        return "IMAGE"
    if suffix == ".pdf":
        return "PDF"
    if suffix in {".doc", ".docx"}:
        return "WORD"
    if suffix in {".xls", ".xlsx", ".xlsm", ".csv"}:
        return "EXCEL"
    return "TEXT"


def _import_options_from_settings(settings: dict) -> dict:
    return {
        "ocr_strength": str(settings.get("ocr_strength", "BALANCED")).strip().upper(),
        "auto_accept_threshold": float(settings.get("correction_auto_accept_threshold", 0.85)),
    }


def _resolve_word_status_filters(raw_status: str | None) -> list[str] | None:
    if raw_status is None:
        return None
    key = str(raw_status).strip().upper()
    if not key or key == "ALL":
        return None
    mapping = {
        "NEW": ["NEW"],
        "UNLEARNED": ["NEW"],
        "未学习": ["NEW"],
        "LEARNING": ["LEARNING", "REVIEWING"],
        "IN_PROGRESS": ["LEARNING", "REVIEWING"],
        "学习中": ["LEARNING", "REVIEWING"],
        "MASTERED": ["MASTERED"],
        "已掌握": ["MASTERED"],
        "SUSPENDED": ["SUSPENDED"],
    }
    return mapping.get(key)


def _normalize_word_status_for_update(raw_status: str) -> str:
    key = str(raw_status or "").strip().upper()
    mapping = {
        "NEW": "NEW",
        "UNLEARNED": "NEW",
        "未学习": "NEW",
        "LEARNING": "LEARNING",
        "IN_PROGRESS": "LEARNING",
        "学习中": "LEARNING",
        "REVIEWING": "REVIEWING",
        "MASTERED": "MASTERED",
        "已掌握": "MASTERED",
        "SUSPENDED": "SUSPENDED",
    }
    normalized = mapping.get(key)
    if not normalized:
        raise ValueError("invalid status")
    return normalized


def _is_ascii_word(token: str) -> bool:
    value = str(token or "").strip().lower()
    if not value:
        return False
    return bool(value.isascii() and value.replace("-", "").replace("'", "").isalpha())
