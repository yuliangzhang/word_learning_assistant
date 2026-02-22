from __future__ import annotations

import hashlib
import json
import os
import re
from collections import OrderedDict
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from word_assistance.cards.templates import (
    KIDS_HTML_TEMPLATE,
    MUSEUM_HTML_TEMPLATE,
    ensure_museum_payload,
    html_list,
    render_card,
)
from word_assistance.config import ARTIFACTS_DIR, CARDS_DIR, DICTIONARY_DIR
from word_assistance.lexicon import ensure_words_enriched
from word_assistance.pipeline.extraction import simple_lemma
from word_assistance.services.llm import LLMService
from word_assistance.storage.db import Database

UTC = timezone.utc

FALLBACK_MUSEUM_KB = {
    "accommodate": {
        "phonetic": "əˈkɒmədeɪt",
        "origin_scene": "把原本放不下的人或事，重新安排出空间与秩序。",
        "origin_scene_en": "Rearrange space and order so people or things that do not fit can be included.",
        "core_formula": "空间 + 调整 + 需求 = accommodate",
        "core_formula_en": "space + adjustment + needs = accommodate",
        "explanation": "它强调“让条件适配对象”而不是“对象硬去适应环境”。",
        "explanation_en": "It means adjusting conditions to people and needs, rather than forcing people to fit the system.",
        "etymology": "来自拉丁语 accommodare（ad- + commodus），核心含义是“使之合适、便利”。",
        "etymology_en": "From Latin accommodare (ad- + commodus), meaning to make something fit or suitable.",
        "cognates": ["commodity", "convenient", "incommode"],
        "nuance_points": [
            "accommodate 偏“提供条件并包容差异”。",
            "adapt 偏“主体主动改变自己”。",
            "fit 偏“结果上匹配”，不强调调整过程。",
        ],
        "nuance_points_en": [
            "accommodate focuses on creating conditions that include differences.",
            "adapt focuses on the subject changing itself.",
            "fit focuses on the result of matching, not the adjustment process.",
        ],
        "example_sentence": "The teacher slowed the pace to accommodate students who were new to academic writing.",
        "epiphany": "真正的成长，不是硬撑，而是学会调整系统去容纳新需求。 | Growth is not force; it is design that makes room.",
        "mermaid_code": """graph TD
  A[accommodare: make fit] --> B[adjust conditions]
  B --> C[make room for people]
  B --> D[adapt plans to needs]
  C --> E[learning inclusion]
  D --> E
""",
    },
    "antenna": {
        "phonetic": "ænˈtenə",
        "origin_scene": "昆虫头上不断试探环境的触角。",
        "origin_scene_en": "The feelers on an insect that constantly probe the surrounding world.",
        "core_formula": "感知 + 接收 + 连接 = antenna",
        "core_formula_en": "sensing + receiving + connection = antenna",
        "explanation": "现代语境中它既是生物触角，也指无线信号的接收与传输装置。",
        "explanation_en": "In modern usage, it means both an insect feeler and a device that receives and transmits signals.",
        "etymology": "来自拉丁语 antenna，原指船帆横杆，后延展为“伸出用于感知/接收”的结构。",
        "etymology_en": "From Latin antenna, first meaning a sail yard, later extended to a projecting structure for sensing/receiving.",
        "cognates": ["antennae", "antennal", "transceiver"],
        "nuance_points": [
            "antenna 强调“接收/探测”的功能。",
            "sensor 更强调“检测并转成数据”。",
            "receiver 强调“信号终端接收端”。",
        ],
        "nuance_points_en": [
            "antenna emphasizes receiving or probing.",
            "sensor emphasizes detection and data conversion.",
            "receiver emphasizes the terminal side of signal reception.",
        ],
        "example_sentence": "The tiny antenna helps the robot detect obstacles before it bumps into anything.",
        "epiphany": "感知能力决定你能连接到多大的世界。 | Your range of perception sets your range of connection.",
        "mermaid_code": """graph TD
  A[触角/天线] --> B[感知输入]
  B --> C[信号接收]
  C --> D[信息理解]
  D --> E[行动决策]
""",
    },
}


def build_museum_payload(
    word: str,
    *,
    word_row: dict | None = None,
    regenerate: bool = False,
    llm_model: str | None = None,
    card_llm_quality_model: str | None = None,
    card_llm_fast_model: str | None = None,
    card_llm_strategy: str | None = None,
) -> dict:
    llm_payload = _build_museum_payload_with_llm(
        word=word,
        word_row=word_row,
        regenerate=regenerate,
        llm_model=llm_model,
        card_llm_quality_model=card_llm_quality_model,
        card_llm_fast_model=card_llm_fast_model,
        card_llm_strategy=card_llm_strategy,
    )
    if llm_payload is not None:
        return llm_payload
    return _build_museum_payload_fallback(word=word, word_row=word_row, regenerate=regenerate)


def build_kids_payload(word: str) -> dict:
    titled = word.capitalize()
    return {
        "word": titled,
        "phonetic": _phonetic_stub(word),
        "core_semantics": f"{titled} is a practical word you can use right away in school reading and writing.",
        "examples": [
            f"I saw the word {word} in my reading homework.",
            f"I can use {word} when I explain this idea.",
        ],
        "today_action": "Break it into sounds, read it 3 times, then write one sentence with it.",
    }


def generate_card(
    *,
    db: Database,
    user_id: int,
    word: str,
    card_type: str = "MUSEUM",
    regenerate: bool = False,
    auto_create_missing: bool = False,
) -> dict:
    normalized = simple_lemma(word.strip().lower())
    if not normalized:
        raise ValueError("word is empty")

    word_row = db.get_word_by_lemma(user_id=user_id, lemma=normalized)
    if word_row is None:
        if not auto_create_missing:
            raise ValueError("word not found in vocabulary")
        import_id = db.create_import(
            user_id=user_id,
            source_type="MANUAL",
            source_name="manual_card_request",
            source_path=None,
            importer_role="CHILD",
            tags=["manual"],
            note="auto created by /card",
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
        word_row = db.get_word_by_lemma(user_id=user_id, lemma=normalized)
        if word_row is None:
            raise RuntimeError("failed to create word for card")

    enriched_rows = ensure_words_enriched(db, user_id=user_id, words=[word_row])
    if enriched_rows:
        word_row = enriched_rows[0]

    card_type_normalized = card_type.upper()
    existing = db.get_latest_card(word_row["id"], card_type_normalized)
    if existing and not regenerate and _is_cache_compatible(existing, card_type=card_type_normalized):
        return {
            "cached": True,
            "card_id": existing["id"],
            "type": existing["type"],
            "version": existing["version"],
            "html_path": existing["html_path"],
            "url": _as_url(Path(existing["html_path"])),
        }

    version = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
    card_dir = CARDS_DIR / normalized
    card_dir.mkdir(parents=True, exist_ok=True)
    html_path = card_dir / f"{version}.html"

    if card_type_normalized == "MUSEUM":
        settings = db.get_parent_settings(user_id)
        preferred_model = str(settings.get("llm_model") or "").strip() or None
        card_llm_quality_model = str(settings.get("card_llm_quality_model") or "").strip() or None
        card_llm_fast_model = str(settings.get("card_llm_fast_model") or "").strip() or None
        card_llm_strategy = str(settings.get("card_llm_strategy") or "").strip().lower() or None
        payload = build_museum_payload(
            normalized,
            word_row=word_row,
            regenerate=regenerate,
            llm_model=preferred_model,
            card_llm_quality_model=card_llm_quality_model,
            card_llm_fast_model=card_llm_fast_model,
            card_llm_strategy=card_llm_strategy,
        )
        ensure_museum_payload(payload)
        if regenerate and existing:
            latest_hash = str(existing.get("content_hash") or "")
            draft_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()
            if latest_hash and draft_hash == latest_hash:
                payload["epiphany"] = _trim_text(f"{payload['epiphany']} (regenerated angle)", 220)
        html = _render_museum_html(payload)
    else:
        payload = build_kids_payload(normalized)
        html = _render_kids_html(payload)

    content_hash = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()
    html_path.write_text(html, encoding="utf-8")

    card_id = db.record_card(
        word_id=word_row["id"],
        card_type=card_type_normalized,
        html_path=str(html_path),
        version=version,
        content_hash=content_hash,
    )
    return {
        "cached": False,
        "card_id": card_id,
        "type": card_type_normalized,
        "version": version,
        "html_path": str(html_path),
        "url": _as_url(html_path),
    }


def generate_dictionary_card(
    *,
    word: str,
    word_row: dict | None = None,
    regenerate: bool = False,
) -> dict:
    normalized = simple_lemma(word.strip().lower())
    if not normalized:
        raise ValueError("word is empty")

    DICTIONARY_DIR.mkdir(parents=True, exist_ok=True)
    html_path = DICTIONARY_DIR / f"{normalized}.html"
    if html_path.exists() and not regenerate:
        return {
            "cached": True,
            "type": "MUSEUM",
            "html_path": str(html_path),
            "url": _as_url(html_path),
        }

    payload = build_museum_payload(normalized, word_row=word_row, regenerate=regenerate)
    ensure_museum_payload(payload)
    html = _render_museum_html(payload)
    html_path.write_text(html, encoding="utf-8")
    return {
        "cached": False,
        "type": "MUSEUM",
        "html_path": str(html_path),
        "url": _as_url(html_path),
    }


def _build_museum_payload_with_llm(
    word: str,
    *,
    word_row: dict | None,
    regenerate: bool,
    llm_model: str | None = None,
    card_llm_quality_model: str | None = None,
    card_llm_fast_model: str | None = None,
    card_llm_strategy: str | None = None,
) -> dict | None:
    llm = LLMService(
        model_override=llm_model,
        museum_quality_model=card_llm_quality_model,
        museum_fast_model=card_llm_fast_model,
        museum_strategy=card_llm_strategy,
    )
    switch = os.getenv("WORD_ASSISTANCE_CARD_LLM_ENABLED", "").strip().lower()
    if switch in {"0", "false", "no", "off"}:
        return None
    if switch not in {"1", "true", "yes", "on"} and not llm.available():
        return None

    hints = _word_hints(word_row)
    meaning_hint_en = _meaning_hint(word_row, prefer="en")
    meaning_hint_zh = _meaning_hint(word_row, prefer="zh")
    model_payload = llm.museum_word_payload(word=word, hints=hints, regenerate=regenerate)
    if not model_payload:
        return None

    origin_scene_zh = _pick_text(model_payload, "origin_scene_zh", "origin_scene", limit=120)
    origin_scene_en = _pick_text(
        model_payload,
        "origin_scene_en",
        default=f'Place "{word}" in a real scene and observe the concrete action it carries.',
        limit=160,
    )
    core_formula_zh = _pick_text(model_payload, "core_formula_zh", "core_formula", limit=96)
    core_formula_en = _pick_text(
        model_payload,
        "core_formula_en",
        default="core meaning + context constraints + collocations = stable mastery",
        limit=140,
    )
    explanation_zh = _pick_text(model_payload, "explanation_zh", "explanation", limit=260)
    explanation_en = _pick_text(
        model_payload,
        "explanation_en",
        default=f"{word.capitalize()} is best learned through real context and high-frequency collocations.",
        limit=280,
    )
    definition_deep = _render_bilingual_core(
        origin_scene_zh=origin_scene_zh,
        origin_scene_en=origin_scene_en,
        core_formula_zh=core_formula_zh,
        core_formula_en=core_formula_en,
        explanation_zh=explanation_zh,
        explanation_en=explanation_en,
    )
    etymology_zh = _pick_text(model_payload, "etymology_zh", "etymology", limit=260)
    etymology_en = _pick_text(
        model_payload,
        "etymology_en",
        default="This etymology is a learning-oriented simplification and should be cross-checked with authoritative dictionaries.",
        limit=280,
    )
    etymology = _render_bilingual_etymology(
        zh_text=etymology_zh,
        en_text=etymology_en,
        cognates=_to_str_list(model_payload.get("cognates"), limit=4),
    )
    nuance_points_zh = _to_str_list(model_payload.get("nuance_points_zh"), limit=4) or _to_str_list(
        model_payload.get("nuance_points"), limit=4
    )
    nuance_points_en = _to_str_list(model_payload.get("nuance_points_en"), limit=4)
    nuance_text = _render_bilingual_bullets(zh_items=nuance_points_zh, en_items=nuance_points_en, cls="nuance-list")
    example_sentence = _trim_text(str(model_payload.get("example_sentence") or ""), 220)
    mermaid_code = _normalize_mermaid_graph_td(str(model_payload.get("mermaid_code") or ""))
    llm_model_used = str(model_payload.get("_meta_model") or "").strip()
    topology_source = f"llm:{llm_model_used}" if llm_model_used else "llm"
    if mermaid_code and _is_low_signal_mermaid_topology(mermaid_code, word=word):
        mermaid_code = None
    if not mermaid_code:
        topology_source = "fallback"
        mermaid_code = _build_semantic_topology(
            word=word,
            etymology=etymology_zh or etymology_en,
            core_action=core_formula_zh or core_formula_en,
            modern_usage=explanation_zh or explanation_en,
            meaning_hint=meaning_hint_zh or meaning_hint_en or origin_scene_zh or origin_scene_en,
            regenerate=regenerate,
        )
    epiphany = _trim_text(str(model_payload.get("epiphany") or ""), 220)

    payload = {
        "word": word.capitalize(),
        "phonetic": _trim_text(str(model_payload.get("phonetic") or _phonetic_stub(word)), 80),
        "definition_deep": definition_deep,
        "etymology": etymology,
        "nuance_text": nuance_text,
        "example_sentence": example_sentence,
        "mermaid_code": mermaid_code,
        "topology_source": topology_source,
        "epiphany": epiphany,
        "confidence_note": "Etymology may include learning-oriented approximations. Please cross-check with authoritative dictionaries. / 词源解释可能含教学化近似，建议与权威词典交叉核验。",
    }
    try:
        ensure_museum_payload(payload)
    except ValueError:
        return None
    return payload


def _build_museum_payload_fallback(word: str, *, word_row: dict | None, regenerate: bool) -> dict:
    info = FALLBACK_MUSEUM_KB.get(word, {})
    meaning_hint_en = _meaning_hint(word_row, prefer="en")
    meaning_hint_zh = _meaning_hint(word_row, prefer="zh")
    meaning_zh_items = [str(v).strip() for v in (word_row or {}).get("meaning_zh", []) if str(v).strip()]
    meaning_en_items = [str(v).strip() for v in (word_row or {}).get("meaning_en", []) if str(v).strip()]

    variant = _fallback_variant(word=word, regenerate=regenerate)
    origin_scene_zh = _trim_text(str(info.get("origin_scene") or variant["origin_scene"]), 120)
    origin_scene_en = _trim_text(
        str(info.get("origin_scene_en") or f'Place "{word}" in a practical learning scene and observe its role in the sentence.'),
        160,
    )
    core_formula_zh = _trim_text(str(info.get("core_formula") or variant["core_formula"]), 96)
    core_formula_en = _trim_text(
        str(info.get("core_formula_en") or "core meaning + context constraints + collocations = stable mastery"),
        140,
    )
    if info.get("explanation"):
        explanation_zh = str(info["explanation"])
    elif meaning_hint_zh:
        explanation_zh = (
            f"{word.capitalize()} 的高频义项是：{meaning_hint_zh}。"
            "学习时优先锁定它的典型搭配，再迁移到自己的表达中。"
        )
    else:
        explanation_zh = f"{word.capitalize()} 常在学习与表达语境中出现，建议结合真实句子记忆。"
    if info.get("explanation_en"):
        explanation_en = str(info["explanation_en"])
    elif meaning_hint_en:
        explanation_en = (
            f"A high-frequency meaning of {word} is: {meaning_hint_en}. "
            "Learn it first through collocations, then transfer it into your own writing."
        )
    else:
        explanation_en = f"{word.capitalize()} is best mastered through real contexts and high-frequency collocations."

    definition_deep = _render_bilingual_core(
        origin_scene_zh=origin_scene_zh,
        origin_scene_en=origin_scene_en,
        core_formula_zh=core_formula_zh,
        core_formula_en=core_formula_en,
        explanation_zh=_trim_text(explanation_zh, 260),
        explanation_en=_trim_text(explanation_en, 280),
    )

    etymology_text_zh = str(info.get("etymology") or "词源使用教学级近似解释，建议与词典交叉核验。")
    etymology_text_en = str(
        info.get("etymology_en")
        or "This etymology is a learning-oriented simplification and should be cross-checked with authoritative dictionaries."
    )
    cognates = info.get("cognates") or [f"{word}ly", f"{word}ness"]
    etymology = _render_bilingual_etymology(
        zh_text=_trim_text(etymology_text_zh, 260),
        en_text=_trim_text(etymology_text_en, 280),
        cognates=cognates,
    )

    nuance_points_zh = info.get("nuance_points") or [
        f"先确认 {word} 在句子里承担的具体语义角色。",
        "优先记住一个高频搭配，再扩展到写作表达。",
    ]
    nuance_points_en = info.get("nuance_points_en") or [
        f"First identify the semantic role that {word} plays in a sentence.",
        "Lock one high-frequency collocation first, then expand to writing output.",
    ]
    nuance_text = _render_bilingual_bullets(zh_items=nuance_points_zh, en_items=nuance_points_en, cls="nuance-list")

    example_sentence = info.get("example_sentence") or f"I used {word} in my own sentence to make the meaning clear."
    epiphany = info.get("epiphany") or (
        f"Mastering {word.capitalize()} is not about rote memory; it is about using it in your own sentence. / "
        f"掌握 {word.capitalize()} 不是死记，而是把它放进你自己的句子。"
    )
    mermaid_code = _normalize_mermaid_graph_td(str(info.get("mermaid_code") or ""))
    if not mermaid_code:
        mermaid_code = _build_semantic_topology(
            word=word,
            etymology=etymology_text_zh or etymology_text_en,
            core_action=core_formula_zh or core_formula_en,
            modern_usage=explanation_zh or explanation_en,
            meaning_hint=meaning_hint_zh or meaning_hint_en or origin_scene_zh or origin_scene_en,
            meaning_zh_items=meaning_zh_items,
            meaning_en_items=meaning_en_items,
            regenerate=regenerate,
        )

    return {
        "word": word.capitalize(),
        "phonetic": info.get("phonetic") or _phonetic_stub(word),
        "definition_deep": definition_deep,
        "etymology": etymology,
        "nuance_text": nuance_text,
        "example_sentence": example_sentence,
        "mermaid_code": mermaid_code,
        "topology_source": "fallback",
        "epiphany": epiphany,
        "confidence_note": "Etymology may include learning-oriented approximations. Please cross-check with authoritative dictionaries. / 词源解释可能含教学化近似，建议与权威词典交叉核验。",
    }


def _render_museum_html(payload: dict) -> str:
    mapping = {
        "WORD": escape(payload["word"]),
        "WORD_RAW": escape(payload["word"]),
        "PHONETIC": escape(payload["phonetic"]),
        "DEFINITION_DEEP": payload["definition_deep"],
        "ETYMOLOGY": payload["etymology"],
        "NUANCE_TEXT": payload["nuance_text"],
        "EXAMPLE_SENTENCE": escape(payload["example_sentence"]),
        "MERMAID_CODE": payload["mermaid_code"],
        "EPIPHANY": escape(payload["epiphany"]),
        "CONFIDENCE_NOTE": escape(payload["confidence_note"]),
    }
    html = render_card(MUSEUM_HTML_TEMPLATE, mapping)
    topology_source = str(payload.get("topology_source") or "unknown")
    return f"{html}\n<!-- topology-source:{escape(topology_source)} -->\n"


def _render_kids_html(payload: dict) -> str:
    mapping = {
        "WORD": escape(payload["word"]),
        "PHONETIC": escape(payload["phonetic"]),
        "CORE_SEMANTICS": escape(payload["core_semantics"]),
        "EXAMPLE_LIST": html_list(payload["examples"]),
        "ACTION_TODAY": escape(payload["today_action"]),
    }
    return render_card(KIDS_HTML_TEMPLATE, mapping)


def _as_url(path: Path) -> str:
    rel = path.relative_to(ARTIFACTS_DIR)
    return "/artifacts/" + str(rel).replace("\\", "/")


def _phonetic_stub(word: str) -> str:
    return word.replace("a", "æ").replace("e", "e").replace("i", "ɪ").replace("o", "oʊ").replace("u", "ʌ")


def _word_hints(word_row: dict | None) -> dict:
    if not word_row:
        return {}
    return {
        "meaning_zh": word_row.get("meaning_zh") or [],
        "meaning_en": word_row.get("meaning_en") or [],
        "examples": word_row.get("examples") or [],
        "tags": word_row.get("tags") or [],
    }


def _meaning_hint(word_row: dict | None, *, prefer: str = "en") -> str:
    hints = _word_hints(word_row)
    if prefer == "zh":
        meanings = hints.get("meaning_zh") or hints.get("meaning_en") or []
    else:
        meanings = hints.get("meaning_en") or hints.get("meaning_zh") or []
    if isinstance(meanings, list) and meanings:
        return _trim_text(str(meanings[0]), 80)
    return ""


def _pick_text(payload: dict, preferred_key: str, fallback_key: str | None = None, *, default: str = "", limit: int = 160) -> str:
    raw = payload.get(preferred_key)
    if not raw and fallback_key:
        raw = payload.get(fallback_key)
    text = str(raw or default).strip()
    return _trim_text(text, limit)


def _render_bilingual_core(
    *,
    origin_scene_zh: str,
    origin_scene_en: str,
    core_formula_zh: str,
    core_formula_en: str,
    explanation_zh: str,
    explanation_en: str,
) -> str:
    return "".join(
        [
            f"<div class=\"bi-en\"><b>Origin Scene</b>: {escape(origin_scene_en)}</div><br>",
            f"<div class=\"bi-zh\"><b>原始画面</b>: {escape(origin_scene_zh)}</div><br>",
            f"<div class=\"bi-en\"><b>Core Formula</b>: {escape(core_formula_en)}</div><br>",
            f"<div class=\"bi-zh\"><b>核心意象</b>: {escape(core_formula_zh)}</div><br>",
            f"<div class=\"bi-en\">{escape(explanation_en)}</div>",
            f"<div class=\"bi-zh\">{escape(explanation_zh)}</div>",
        ]
    )


def _render_bilingual_etymology(*, zh_text: str, en_text: str, cognates: list[str]) -> str:
    cognates_html = _render_bullets(cognates, cls="nuance-list")
    return "".join(
        [
            f"<div class=\"bi-en\"><b>English</b>: {escape(en_text)}</div>",
            f"<div class=\"bi-zh\"><b>中文</b>: {escape(zh_text)}</div>",
            cognates_html,
        ]
    )


def _render_bilingual_bullets(*, zh_items: list[str], en_items: list[str], cls: str) -> str:
    if not zh_items and not en_items:
        return ""
    rows: list[str] = []
    total = max(len(zh_items), len(en_items))
    for idx in range(total):
        zh = _trim_text(str(zh_items[idx]), 140) if idx < len(zh_items) else "在真实语境里使用该词并复述一次。"
        en = (
            _trim_text(str(en_items[idx]), 180)
            if idx < len(en_items)
            else "Use the word in one real context and restate it in your own sentence."
        )
        rows.append(
            "".join(
                [
                    "<li class=\"nuance-item\">",
                    f"<div class=\"bi-en\">{escape(en)}</div>",
                    f"<div class=\"bi-zh\">{escape(zh)}</div>",
                    "</li>",
                ]
            )
        )
    return f"<ul class=\"{cls}\">{''.join(rows)}</ul>"


def _render_bullets(items: list[str], *, cls: str) -> str:
    cleaned = [escape(_trim_text(str(item), 140)) for item in items if str(item).strip()]
    if not cleaned:
        return ""
    rows = "".join(f"<li class=\"nuance-item\">{item}</li>" for item in cleaned[:5])
    return f"<ul class=\"{cls}\">{rows}</ul>"


def _to_str_list(value: object, *, limit: int = 4) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:limit]:
        text = str(item).strip()
        if text:
            items.append(text)
    return items


def _trim_text(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _fallback_variant(*, word: str, regenerate: bool) -> dict:
    default_origin = f"把“{word}”放到真实场景里，观察它在句子中承担的动作。"
    variants = [
        {
            "origin_scene": default_origin,
            "core_formula": "语义核心 + 语境限制 + 搭配 = 稳定掌握",
        },
        {
            "origin_scene": f"把“{word}”放进课堂、阅读、写作三个场景，看它各自承担的作用。",
            "core_formula": "词义锚点 + 搭配网络 + 复述输出 = 长时记忆",
        },
        {
            "origin_scene": f"先问“{word} 在句子里做了什么”，再问“它和哪些词最常并肩出现”。",
            "core_formula": "动作识别 + 句法位置 + 场景迁移 = 真正会用",
        },
    ]
    if not regenerate:
        return variants[0]
    idx = datetime.now(UTC).microsecond % len(variants)
    return variants[idx]


def _build_semantic_topology(
    *,
    word: str,
    etymology: str,
    core_action: str,
    modern_usage: str,
    meaning_hint: str = "",
    meaning_zh_items: list[str] | None = None,
    meaning_en_items: list[str] | None = None,
    regenerate: bool = False,
) -> str:
    etymon = _safe_mermaid_label(_derive_etymon_anchor(word=word, etymology=etymology), limit=28)
    action = _safe_mermaid_label(
        _derive_action_anchor(word=word, core_action=core_action, modern_usage=modern_usage, meaning_hint=meaning_hint),
        limit=24,
    )
    abstract = _safe_mermaid_label(
        _derive_abstract_anchor(
            word=word,
            modern_usage=modern_usage,
            meaning_hint=meaning_hint,
            meaning_zh_items=meaning_zh_items or [],
            meaning_en_items=meaning_en_items or [],
        ),
        limit=26,
    )
    raw_usage_nodes = _derive_usage_nodes(
        word=word,
        modern_usage=modern_usage,
        meaning_hint=meaning_hint,
        meaning_zh_items=meaning_zh_items or [],
        meaning_en_items=meaning_en_items or [],
    )
    usage_nodes = _dedupe_mermaid_labels(
        raw_usage_nodes,
        banned=[etymon, action, abstract],
    )
    if len(usage_nodes) < 3:
        usage_nodes.append(_derive_contrast_anchor(word=word, modern_usage=modern_usage, meaning_hint=meaning_hint))
    usage_nodes = _dedupe_mermaid_labels(
        usage_nodes,
        banned=[etymon, action, abstract],
    )
    fallback_usage = [
        f"{word.capitalize()} 场景迁移",
        f"{word.capitalize()} 语境扩展",
        f"{word.capitalize()} 句子化输出",
    ]
    for fallback_label in fallback_usage:
        if len(usage_nodes) >= 4:
            break
        usage_nodes.append(fallback_label)
        usage_nodes = _dedupe_mermaid_labels(
            usage_nodes,
            banned=[etymon, action, abstract],
        )
    usage_1 = _safe_mermaid_label(usage_nodes[0], limit=22)
    usage_2 = _safe_mermaid_label(usage_nodes[1], limit=22)
    usage_3 = _safe_mermaid_label(usage_nodes[2], limit=22)
    transfer = _safe_mermaid_label(_derive_transfer_anchor(word=word, meaning_hint=meaning_hint, modern_usage=modern_usage), limit=24)
    metaphor = _safe_mermaid_label(_derive_metaphor_anchor(word=word, modern_usage=modern_usage, meaning_hint=meaning_hint), limit=24)

    salt = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f") if regenerate else ""
    variant_seed = int(hashlib.sha1(f"{word}|{salt}".encode("utf-8")).hexdigest(), 16)
    variant = variant_seed % 4
    if variant == 0:
        lines = [
            "graph TD",
            f"  A[{etymon}] --> B[{action}]",
            f"  B --> C[{abstract}]",
            f"  C --> D[{usage_1}]",
            f"  C --> E[{usage_2}]",
            f"  D --> F[{transfer}]",
            "  E --> F",
        ]
    elif variant == 1:
        lines = [
            "graph TD",
            f"  A[{etymon}] --> B[{action}]",
            f"  B --> C[{abstract}]",
            f"  B --> D[{usage_3}]",
            f"  C --> E[{usage_1}]",
            f"  D --> F[{usage_2}]",
            f"  E --> G[{metaphor}]",
            "  F --> G",
        ]
    elif variant == 2:
        lines = [
            "graph TD",
            f"  A[{etymon}] --> B[{action}]",
            f"  B --> C[{usage_1}]",
            f"  B --> D[{usage_2}]",
            f"  C --> E[{abstract}]",
            f"  D --> F[{usage_3}]",
            f"  E --> G[{transfer}]",
            "  F --> G",
        ]
    else:
        lines = [
            "graph TD",
            f"  A[{etymon}] --> B[{action}]",
            f"  B --> C[{abstract}]",
            f"  C --> D[{usage_1}]",
            f"  C --> E[{usage_2}]",
            f"  D --> H[{usage_3}]",
            f"  E --> F[{transfer}]",
            "  H --> F",
            f"  F --> G[{metaphor}]",
        ]
    return "\n".join(lines)


def _normalize_mermaid_graph_td(raw_code: str) -> str | None:
    if not raw_code or not raw_code.strip():
        return None
    code = _strip_mermaid_fence(raw_code)
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.strip() for line in code.split("\n") if line.strip()]
    if not lines:
        return None

    graph_idx = next((idx for idx, line in enumerate(lines) if re.match(r"^graph\s+td\b", line, flags=re.IGNORECASE)), -1)
    if graph_idx < 0:
        return None
    lines = lines[graph_idx:]
    lines[0] = "graph TD"

    node_labels: OrderedDict[str, str] = OrderedDict()
    edges: list[tuple[str, str]] = []
    for line in lines[1:]:
        lower = line.lower()
        if lower.startswith(("%%", "classdef", "class ", "style ", "click ", "linkstyle", "subgraph", "end")):
            continue

        # Normalize advanced link text / styles into basic arrows.
        normalized_line = (
            line.replace("-.->", "-->")
            .replace("==>", "-->")
            .replace("--->", "-->")
        )
        normalized_line = re.sub(r"-->\s*\|[^|]{0,120}\|\s*", "--> ", normalized_line)
        normalized_line = re.sub(r"--\s*[^-<>|]{1,100}\s*-->", "-->", normalized_line)

        if "-->" in normalized_line:
            parts = [part.strip() for part in normalized_line.split("-->") if part.strip()]
            if len(parts) < 2:
                continue
            parsed: list[tuple[str, str | None]] = []
            for part in parts:
                node = _parse_mermaid_node_expr(part)
                if not node:
                    parsed = []
                    break
                parsed.append(node)
            if not parsed:
                continue
            for node_id, node_label in parsed:
                if node_id not in node_labels:
                    node_labels[node_id] = _safe_mermaid_label(node_label or node_id, limit=28)
            for idx in range(len(parsed) - 1):
                left_id = parsed[idx][0]
                right_id = parsed[idx + 1][0]
                edges.append((left_id, right_id))
            continue

        node_decl = _parse_mermaid_node_expr(normalized_line.strip())
        if not node_decl:
            continue
        node_id, node_label = node_decl
        if node_id not in node_labels:
            node_labels[node_id] = _safe_mermaid_label(node_label or node_id, limit=28)

    if len(edges) < 2:
        return None
    if len(node_labels) > 16 or len(edges) > 26:
        return None

    normalized = ["graph TD"]
    for node_id, label in node_labels.items():
        normalized.append(f"  {node_id}[{label}]")
    for left, right in edges:
        normalized.append(f"  {left} --> {right}")
    return "\n".join(normalized)


def _strip_mermaid_fence(text: str) -> str:
    content = text.strip()
    fenced = re.match(r"^```(?:mermaid)?\s*(.*?)\s*```$", content, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    return content


def _extract_phrase(text: str, *, limit: int) -> str:
    compact = " ".join(str(text or "").split())
    if not compact:
        return "语义节点"
    parts = re.split(r"[。.!?;；:：|,，\n]+", compact)
    candidate = next((part.strip() for part in parts if part.strip()), compact)
    return _trim_text(candidate, limit)


def _parse_mermaid_node_expr(expr: str) -> tuple[str, str | None] | None:
    if not expr:
        return None
    compact = expr.strip().rstrip(";").strip()
    if not compact:
        return None
    head = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*(.*)$", compact)
    if not head:
        return None
    node_id = head.group(1)
    tail = head.group(2).strip()
    if not tail:
        return node_id, None

    if tail.startswith("((") and tail.endswith("))"):
        return node_id, tail[2:-2].strip()
    if tail.startswith("{{") and tail.endswith("}}"):
        return node_id, tail[2:-2].strip()

    pair_shapes = [("[", "]"), ("(", ")"), ("{", "}"), ("\"", "\""), ("'", "'")]
    for left, right in pair_shapes:
        if tail.startswith(left) and tail.endswith(right) and len(tail) >= 2:
            label = tail[len(left) : len(tail) - len(right)].strip()
            return node_id, label
    return node_id, tail


def _derive_etymon_anchor(*, word: str, etymology: str) -> str:
    compact = " ".join(str(etymology or "").split())
    if compact and "教学级近似" not in compact:
        roots = [r.lower() for r in re.findall(r"[A-Za-z]{3,}", compact) if r.lower() not in {"english", "latin", "greek"}]
        uniq_roots: list[str] = []
        for root in roots:
            if root not in uniq_roots:
                uniq_roots.append(root)
            if len(uniq_roots) >= 2:
                break
        if len(uniq_roots) >= 2:
            return f"{uniq_roots[0]} + {uniq_roots[1]}"
        if uniq_roots:
            return uniq_roots[0]
        return _extract_phrase(compact, limit=24)

    prefix_map = {
        "re": "re- 再次",
        "pre": "pre- 预先",
        "sub": "sub- 下层",
        "inter": "inter- 之间",
        "trans": "trans- 转移",
        "con": "con- 共同",
        "de": "de- 去除",
    }
    suffix_map = {
        "tion": "词尾 -tion 行为/过程",
        "ity": "词尾 -ity 性质/状态",
        "ment": "词尾 -ment 结果/状态",
        "able": "词尾 -able 可被...",
        "ize": "词尾 -ize 使成为",
        "ous": "词尾 -ous 具有...性质",
        "ive": "词尾 -ive 倾向/性质",
    }
    prefix = next((v for k, v in prefix_map.items() if word.startswith(k) and len(word) > len(k) + 2), "")
    suffix = next((v for k, v in suffix_map.items() if word.endswith(k) and len(word) > len(k) + 2), "")
    if prefix and suffix:
        return f"{prefix} + {suffix}"
    if prefix:
        return prefix
    if suffix:
        return suffix
    return _trim_text(f"{word[:5]}* 词干线索", 24)


def _derive_action_anchor(*, word: str, core_action: str, modern_usage: str, meaning_hint: str) -> str:
    candidate = _extract_phrase(core_action, limit=28)
    generic_markers = (
        "语义核心",
        "core meaning",
        "语境限制",
        "搭配",
        "stable mastery",
        "动作识别",
        "句法位置",
        "场景迁移",
        "真正会用",
        "词义锚点",
        "请在词库中补充释义",
        "词典暂缺",
        "definition unavailable",
        "definition pending",
        "verify spelling",
        "高频义项是",
    )
    if not any(marker in candidate.lower() for marker in [m.lower() for m in generic_markers]):
        return candidate
    pool = f"{word} {modern_usage} {meaning_hint}".lower()
    mapping = [
        (("need", "necessary", "必须", "需要"), "满足关键条件"),
        (("govern", "government", "治理", "管理"), "协调并治理"),
        (("environ", "环境", "surround"), "围绕并影响"),
        (("definite", "definitely", "肯定", "确定"), "确认并断言"),
        (("adapt", "适应", "调整"), "调整以匹配"),
        (("accommod", "容纳", "空间"), "调整并容纳"),
        (("antenna", "信号", "接收"), "接收并传递"),
        (("crime", "criminal", "纵火", "犯罪"), "实施犯罪行为"),
        (("attack", "assault", "攻击"), "发动攻击"),
        (("corrupt", "bribe", "贿赂", "腐败"), "利用权力谋利"),
        (("happy", "joy", "快乐"), "表达积极情绪"),
        (("angry", "anger", "愤怒"), "表达强烈不满"),
        (("rough", "粗糙"), "以粗略方式处理"),
    ]
    for keys, action in mapping:
        if any(k in pool for k in keys):
            return action
    zh_chunks = re.findall(r"[\u4e00-\u9fff]{2,8}", f"{meaning_hint} {modern_usage}")
    for chunk in zh_chunks:
        if chunk in {"语境", "学习", "表达", "相关", "使用", "词典", "解释"}:
            continue
        if "的" in chunk and len(chunk) >= 4:
            chunk = chunk.replace("的", "")
        if len(chunk) >= 2:
            if "词典暂缺" in chunk or "补充释" in chunk or "高频义项是" in chunk:
                continue
            return _trim_text(f"围绕{chunk}展开", 18)

    en_match = re.search(r"\bto\s+([a-z]{3,}(?:\s+[a-z]{3,}){0,2})", pool)
    if en_match:
        return _trim_text(f"{en_match.group(1)}", 20)

    fallback_phrase = _extract_phrase(meaning_hint or modern_usage, limit=18)
    if (
        fallback_phrase
        and "词典暂缺" not in fallback_phrase
        and "补充释" not in fallback_phrase
        and "高频义项是" not in fallback_phrase
        and "definition unavailable" not in fallback_phrase.lower()
        and "definition pending" not in fallback_phrase.lower()
    ):
        return fallback_phrase
    return "提炼关键动作"


def _derive_abstract_anchor(
    *,
    word: str,
    modern_usage: str,
    meaning_hint: str,
    meaning_zh_items: list[str],
    meaning_en_items: list[str],
) -> str:
    for item in list(meaning_zh_items[1:3]) + list(meaning_en_items[1:3]):
        usage = _extract_phrase(item, limit=28)
        if usage:
            return usage
    usage = _extract_phrase(meaning_hint or modern_usage, limit=28)
    if usage and "词典暂缺" not in usage and "definition unavailable" not in usage.lower():
        return usage
    usage = _extract_phrase(modern_usage, limit=28)
    if usage and "词典暂缺" not in usage and "definition unavailable" not in usage.lower():
        return usage
    return _trim_text(f"{word} 的抽象语义", 24)


def _derive_usage_nodes(
    *,
    word: str,
    modern_usage: str,
    meaning_hint: str,
    meaning_zh_items: list[str],
    meaning_en_items: list[str],
) -> list[str]:
    nodes: list[str] = []
    for item in meaning_zh_items[:2]:
        text = _extract_phrase(item, limit=24)
        if text and text not in nodes:
            nodes.append(text)
    for item in meaning_en_items[:2]:
        text = _extract_phrase(item, limit=24)
        if text and text not in nodes:
            nodes.append(text)
    fallback_pool = [
        _extract_phrase(meaning_hint, limit=24),
        _extract_phrase(modern_usage, limit=24),
        f"{word.capitalize()} 场景用法",
    ]
    for item in fallback_pool:
        if item and item not in nodes:
            nodes.append(item)
        if len(nodes) >= 3:
            break
    return nodes


def _derive_transfer_anchor(*, word: str, meaning_hint: str, modern_usage: str) -> str:
    base = _extract_phrase(meaning_hint or modern_usage, limit=20)
    if base:
        return f"迁移输出 {base}"
    return f"迁移输出 {word.capitalize()}"


def _derive_contrast_anchor(*, word: str, modern_usage: str, meaning_hint: str) -> str:
    pool = f"{modern_usage} {meaning_hint}".lower()
    if any(k in pool for k in ("necessary", "must", "必须", "需要")):
        return "必要 vs 可选"
    if any(k in pool for k in ("accommod", "容纳", "适配")):
        return "适配 vs 硬塞"
    if any(k in pool for k in ("environment", "surround", "环境")):
        return "环境影响路径"
    if any(k in pool for k in ("government", "govern", "治理")):
        return "治理对象与边界"
    if any(k in pool for k in ("antenna", "signal", "信号")):
        return "接收 vs 发射"
    return f"{word.capitalize()} 对比语境"


def _derive_metaphor_anchor(*, word: str, modern_usage: str, meaning_hint: str) -> str:
    phrase = _extract_phrase(meaning_hint or modern_usage, limit=20)
    if phrase and "词典暂缺" not in phrase and "definition unavailable" not in phrase.lower():
        return f"隐喻迁移 {phrase}"
    return f"{word.capitalize()} 抽象迁移"


def _dedupe_mermaid_labels(items: list[str], *, banned: list[str] | None = None) -> list[str]:
    banned = banned or []
    seen: set[str] = set()
    blocked = {_mermaid_label_key(item) for item in banned}
    cleaned: list[str] = []
    for item in items:
        key = _mermaid_label_key(item)
        if not key or key in blocked or key in seen:
            continue
        seen.add(key)
        cleaned.append(item)
    return cleaned


def _mermaid_label_key(label: str) -> str:
    compact = re.sub(r"\s+", "", str(label or "").lower())
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", compact)


def _safe_mermaid_label(text: str, *, limit: int) -> str:
    compact = " ".join(text.split())
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff\s+/&-]", "", compact).strip()
    if not cleaned:
        return "语义节点"
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 1].rstrip() + "…"
    return cleaned


def _is_low_signal_mermaid_topology(mermaid_code: str, *, word: str) -> bool:
    labels = [str(item).strip() for item in re.findall(r"\[(.*?)\]", mermaid_code) if str(item).strip()]
    if len(labels) < 3:
        return True

    generic_anchors = {
        "词源",
        "本义",
        "词源本义",
        "核心动作",
        "抽象含义",
        "现代用法",
        "抽象含义现代用法",
        "语义节点",
        "etymology",
        "coreaction",
        "coremeaning",
        "abstractmeaning",
        "modernusage",
        "rootorigin",
        "semanticnode",
    }

    word_seed = re.sub(r"[^a-z]", "", word.lower())[:5]
    informative = 0
    generic = 0
    for label in labels:
        normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", label.lower())
        if not normalized:
            generic += 1
            continue
        if normalized in generic_anchors:
            generic += 1
            continue

        # e.g. "词源/本义", "核心动作 + 现代用法"
        compact = normalized
        for token in (
            "词源",
            "本义",
            "核心动作",
            "抽象含义",
            "现代用法",
            "etymology",
            "coreaction",
            "coremeaning",
            "abstractmeaning",
            "modernusage",
            "rootorigin",
        ):
            compact = compact.replace(token, "")
        compact = compact.strip()
        if not compact:
            generic += 1
            continue

        if word_seed and word_seed in compact:
            informative += 1
            continue
        if re.search(r"[\u4e00-\u9fff]{2,}", compact) or re.search(r"[a-z]{4,}", compact):
            informative += 1
            continue
        generic += 1

    if informative <= 1:
        return True
    return generic >= max(2, len(labels) - 1)


def _is_cache_compatible(existing: dict, *, card_type: str) -> bool:
    html_path = Path(str(existing.get("html_path", "")))
    if not html_path.exists():
        return False
    if card_type != "MUSEUM":
        return True
    try:
        html = html_path.read_text(encoding="utf-8")
    except Exception:
        return False
    # Invalidate legacy generic cards generated before museum-v2 implementation.
    legacy_markers = (
        "核心意象公式: 识别 + 场景 + 复述 = 稳定记忆。",
        "Nuance 语感辨析",
        "语义核心 + 语境限制 + 搭配 = 稳定掌握",
        "常用于描述与学习、表达或任务执行相关的语境",
        "复习强化]",
        "词源/本义 词源/本义",
    )
    if any(marker in html for marker in legacy_markers):
        return False
    mermaid_match = re.search(r'<div class="mermaid">\s*(.*?)\s*</div>', html, flags=re.DOTALL)
    if mermaid_match:
        mermaid_code = _normalize_mermaid_graph_td(mermaid_match.group(1).strip())
        word_hint = html_path.parent.name if html_path.parent else ""
        if not mermaid_code or _is_low_signal_mermaid_topology(mermaid_code, word=word_hint):
            return False
    return (
        "NUANCE & CONTEXT (语感与语境)" in html
        and "class=\"bi-zh\"" in html
        and "class=\"bi-en\"" in html
        and "graph TD" in html
    )
