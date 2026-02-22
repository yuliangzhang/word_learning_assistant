from __future__ import annotations

import re

from word_assistance.config import PROJECT_ROOT
from word_assistance.pipeline.corrections import suggest_correction
from word_assistance.services.llm import LLMService
from word_assistance.storage.db import Database

SKILL_PROMPT_PATH = PROJECT_ROOT / "skill" / "word-lexicon-enricher" / "prompts" / "lookup.md"

KNOWN_CORRECTIONS = {
    "enviroment": "environment",
    "goverment": "government",
    "govemment": "government",
    "definately": "definitely",
    "neccessary": "necessary",
    "accomodate": "accommodate",
    "acommodate": "accommodate",
    "antena": "antenna",
}

# Keep a reliable local backbone so practice generation works even when external model is unavailable.
BUILTIN_LEXICON = {
    "accommodate": {
        "phonetic": "əˈkɒmədeɪt",
        "meaning_en": ["to provide enough space for someone or something", "to adapt or adjust to meet a need"],
        "meaning_zh": ["容纳；给…提供空间", "使适应；调整以满足需求"],
        "examples": [
            "Our classroom can accommodate thirty students.",
            "The teacher adjusted the schedule to accommodate the new students.",
        ],
    },
    "antenna": {
        "phonetic": "ænˈtenə",
        "meaning_en": ["a structure that receives or sends radio signals", "an insect feeler used to sense the world"],
        "meaning_zh": ["天线；用于收发无线信号的装置", "触角；昆虫用来感知环境的器官"],
        "examples": [
            "The antenna on the roof receives the TV signal.",
            "A butterfly uses its antennae to detect scent in the air.",
        ],
    },
    "necessary": {
        "phonetic": "ˈnesəsəri",
        "meaning_en": ["needed in order to do something", "essential; required"],
        "meaning_zh": ["必要的；必须的", "必不可少的"],
        "examples": [
            "Water is necessary for all living things.",
            "It is necessary to check your spelling before submission.",
        ],
    },
    "definitely": {
        "phonetic": "ˈdefɪnətli",
        "meaning_en": ["without any doubt", "certainly; clearly yes"],
        "meaning_zh": ["肯定地；明确地", "当然；无疑地"],
        "examples": [
            "I will definitely finish my reading tonight.",
            "This is definitely the best answer in the set.",
        ],
    },
    "environment": {
        "phonetic": "ɪnˈvaɪrənmənt",
        "meaning_en": ["the natural world around us", "the conditions in which a person learns or lives"],
        "meaning_zh": ["环境；周围自然条件", "学习或生活的环境与氛围"],
        "examples": [
            "Plants depend on a healthy environment to grow.",
            "A calm classroom environment helps students focus.",
        ],
    },
    "government": {
        "phonetic": "ˈɡʌvənmənt",
        "meaning_en": ["the group of people who rule a country", "the system used to control public affairs"],
        "meaning_zh": ["政府；治理国家的机构", "政体；公共事务管理体系"],
        "examples": [
            "The government announced a new education policy.",
            "Students learned how local government works in civics class.",
        ],
    },
}


class WordLexiconEnricher:
    def __init__(self) -> None:
        self.llm = LLMService()
        self.skill_prompt = _load_skill_prompt()

    def lookup(self, lemma: str, *, hints: dict | None = None) -> dict | None:
        token = lemma.strip().lower()
        if not token:
            return None

        mapped = KNOWN_CORRECTIONS.get(token)
        if mapped and mapped in BUILTIN_LEXICON:
            entry = _normalize_entry(mapped, BUILTIN_LEXICON[mapped])
            return {
                **entry,
                "canonical_lemma": mapped,
                "is_valid": False,
                "note": f"Possible misspelling: {token} -> {mapped}",
                "source": "builtin-correction",
            }

        if token in BUILTIN_LEXICON:
            return {
                **_normalize_entry(token, BUILTIN_LEXICON[token]),
                "canonical_lemma": token,
                "is_valid": True,
                "source": "builtin",
            }

        model_entry = self.llm.word_lexicon_profile(word=token, hints=hints or {}, prompt=self.skill_prompt)
        if model_entry:
            normalized = _normalize_model_entry(token, model_entry)
            if normalized:
                return normalized

        correction = suggest_correction(token)
        candidate = correction.get("suggested_correction")
        if isinstance(candidate, str) and candidate in BUILTIN_LEXICON and candidate != token:
            entry = _normalize_entry(candidate, BUILTIN_LEXICON[candidate])
            return {
                **entry,
                "canonical_lemma": candidate,
                "is_valid": False,
                "note": f"Possible misspelling: {token} -> {candidate}",
                "source": "heuristic-correction",
            }
        return None


def ensure_words_enriched(
    db: Database,
    *,
    user_id: int,
    words: list[dict],
    force: bool = False,
) -> list[dict]:
    if not words:
        return words

    enricher = WordLexiconEnricher()
    changed_ids: list[int] = []

    for word in words:
        word_id = int(word.get("id") or 0)
        lemma = str(word.get("lemma") or "").strip().lower()
        if not word_id or not lemma:
            continue
        if not force and not _needs_enrichment(word):
            continue

        entry = enricher.lookup(
            lemma,
            hints={
                "meaning_en": word.get("meaning_en") or [],
                "meaning_zh": word.get("meaning_zh") or [],
                "examples": word.get("examples") or [],
                "tags": word.get("tags") or [],
            },
        )
        if not entry:
            suggestion = suggest_correction(lemma)
            suggested = str(suggestion.get("suggested_correction") or lemma).strip().lower()
            pending_note = (
                f"Definition unavailable right now. Verify spelling and regenerate. Suggested spelling: {suggested}."
                if suggested and suggested != lemma
                else "Definition unavailable right now. Verify spelling and regenerate."
            )
            db.update_word_learning_fields(
                word_id=word_id,
                meaning_zh=[],
                meaning_en=[pending_note],
                examples=[],
            )
            changed_ids.append(word_id)
            continue

        meaning_zh = list(entry.get("meaning_zh") or [])
        meaning_en = list(entry.get("meaning_en") or [])
        examples = list(entry.get("examples") or [])
        note = str(entry.get("note") or "").strip()
        if note:
            if meaning_zh:
                meaning_zh = [f"{meaning_zh[0]}（{note}）"] + meaning_zh[1:]
            else:
                meaning_zh = [note]

        db.update_word_learning_fields(
            word_id=word_id,
            phonetic=str(entry.get("phonetic") or word.get("phonetic") or "").strip() or None,
            meaning_zh=meaning_zh,
            meaning_en=meaning_en,
            examples=examples,
        )
        changed_ids.append(word_id)

    if not changed_ids:
        return words

    refreshed_rows = db.find_words_by_ids(user_id=user_id, word_ids=changed_ids)
    refreshed_by_id = {int(row["id"]): row for row in refreshed_rows}
    merged: list[dict] = []
    for item in words:
        wid = int(item.get("id") or 0)
        merged.append(refreshed_by_id.get(wid, item))
    return merged


def _needs_enrichment(word: dict) -> bool:
    meaning_zh = [str(v).strip() for v in (word.get("meaning_zh") or []) if str(v).strip()]
    meaning_en = [str(v).strip() for v in (word.get("meaning_en") or []) if str(v).strip()]
    examples = [str(v).strip() for v in (word.get("examples") or []) if str(v).strip()]
    if not meaning_zh or not meaning_en:
        return True
    if not examples:
        return True
    if any(_looks_template_text(text) for text in meaning_en[:2]):
        return True
    if any(_looks_template_text(text) for text in meaning_zh[:2]):
        return True
    return False


def _looks_template_text(text: str) -> bool:
    lowered = text.lower()
    template_markers = (
        "used in learning",
        "learning, expression",
        "definition pending",
        "definition unavailable",
        "please verify spelling",
        "词典暂缺",
        "补充释义",
        "语义核心",
    )
    return any(marker in lowered for marker in template_markers)


def _normalize_entry(lemma: str, entry: dict) -> dict:
    return {
        "canonical_lemma": lemma,
        "phonetic": _clean_phonetic(entry.get("phonetic") or ""),
        "meaning_en": _sanitize_list(entry.get("meaning_en") or []),
        "meaning_zh": _sanitize_list(entry.get("meaning_zh") or []),
        "examples": _sanitize_list(entry.get("examples") or [], limit=3),
    }


def _normalize_model_entry(original: str, payload: dict) -> dict | None:
    canonical = str(payload.get("canonical_lemma") or original).strip().lower()
    if not re.fullmatch(r"[a-z][a-z'-]{1,32}", canonical):
        canonical = original

    meaning_en = _sanitize_list(payload.get("meaning_en") or [])
    meaning_zh = _sanitize_list(payload.get("meaning_zh") or [])
    examples = _sanitize_list(payload.get("examples") or [], limit=3)
    phonetic = _clean_phonetic(payload.get("phonetic") or "")

    if not meaning_en or not meaning_zh:
        return None

    is_valid = bool(payload.get("is_valid", True))
    note = ""
    if not is_valid and canonical != original:
        note = f"Possible misspelling: {original} -> {canonical}"

    return {
        "canonical_lemma": canonical,
        "phonetic": phonetic,
        "meaning_en": meaning_en,
        "meaning_zh": meaning_zh,
        "examples": examples,
        "is_valid": is_valid,
        "note": note,
        "source": "llm",
    }


def _sanitize_list(values: list | tuple, *, limit: int = 5) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value).split()).strip()
        if not text:
            continue
        lower = text.lower()
        if lower in seen:
            continue
        seen.add(lower)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _clean_phonetic(text: str) -> str:
    value = " ".join(str(text).split()).strip()
    if not value:
        return ""
    return value.strip("/")


def _load_skill_prompt() -> str:
    if not SKILL_PROMPT_PATH.exists():
        return ""
    try:
        return SKILL_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return ""
