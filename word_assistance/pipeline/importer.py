from __future__ import annotations

import re

from word_assistance.pipeline.corrections import suggest_correction
from word_assistance.pipeline.extraction import (
    IMPORT_NOISE_WORDS,
    PHRASAL_PARTICLES,
    extract_document_vocab_candidates,
    extract_normalized_tokens,
    extract_text_from_bytes,
    simple_lemma,
)
from word_assistance.safety.policies import sanitize_untrusted_text
from word_assistance.services.llm import LLMService

SMART_IMPORT_SOURCE_TYPES = {"IMAGE", "PDF"}
IMPORT_EXTRA_NOISE_WORDS = {
    "coach",
    "coaches",
    "college",
    "skill",
    "skills",
    "weekly",
    "website",
    "student",
}


def build_import_preview_from_text(
    text: str,
    *,
    auto_accept_threshold: float = 0.85,
    source_type: str | None = None,
    source_name: str | None = None,
) -> list[dict]:
    sanitized = sanitize_untrusted_text(text)
    tokens = _select_import_tokens(
        sanitized,
        source_type=(source_type or "").strip().upper(),
        source_name=source_name or "",
    )
    tokens_with_phrases = _expand_phrasal(tokens)
    return _build_items_from_tokens(tokens_with_phrases, auto_accept_threshold=auto_accept_threshold)


def _build_items_from_tokens(tokens: list[str], *, auto_accept_threshold: float = 0.85) -> list[dict]:
    threshold = _normalize_auto_accept_threshold(auto_accept_threshold)

    items: list[dict] = []
    seen_lemmas: set[str] = set()

    for token in tokens:
        correction = suggest_correction(token)
        final_lemma = simple_lemma(correction["suggested_correction"])
        if not final_lemma or final_lemma in seen_lemmas:
            continue

        seen_lemmas.add(final_lemma)
        confidence = float(correction["confidence"])
        needs_confirmation = bool(correction["needs_confirmation"]) or confidence < threshold
        items.append(
            {
                **correction,
                "needs_confirmation": needs_confirmation,
                "final_lemma": final_lemma,
                "accepted": 0 if needs_confirmation else 1,
            }
        )

    return items


def build_import_preview_from_file(
    filename: str,
    payload: bytes,
    *,
    ocr_strength: str = "BALANCED",
    auto_accept_threshold: float = 0.85,
) -> tuple[str, list[dict]]:
    extracted_text = extract_text_from_bytes(filename=filename, payload=payload, ocr_strength=ocr_strength)
    source_type = _source_type_from_filename(filename)
    items = build_import_preview_from_text(
        extracted_text,
        auto_accept_threshold=auto_accept_threshold,
        source_type=source_type,
        source_name=filename,
    )
    # OCR may fail on low-quality photos; fallback to direct vision-based vocabulary extraction.
    if not items and source_type in SMART_IMPORT_SOURCE_TYPES:
        fallback_tokens = _llm_extract_tokens_from_image(
            filename=filename,
            payload=payload,
            max_words=220,
        )
        if fallback_tokens:
            fallback_tokens = _expand_phrasal(fallback_tokens)
            items = _build_items_from_tokens(
                fallback_tokens,
                auto_accept_threshold=auto_accept_threshold,
            )
            if fallback_tokens:
                extracted_text = (extracted_text.strip() + "\n" if extracted_text.strip() else "") + "\n".join(fallback_tokens)
    return extracted_text, items


def _expand_phrasal(tokens: list[str]) -> list[str]:
    expanded: list[str] = []
    for idx, token in enumerate(tokens):
        expanded.append(token)
        if idx + 1 < len(tokens) and tokens[idx + 1] in PHRASAL_PARTICLES:
            expanded.append(f"{token} {tokens[idx + 1]}")
    return expanded


def _normalize_auto_accept_threshold(value: float) -> float:
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        threshold = 0.85
    return round(max(0.5, min(threshold, 0.99)), 2)


def _select_import_tokens(text: str, *, source_type: str, source_name: str) -> list[str]:
    if source_type in SMART_IMPORT_SOURCE_TYPES:
        heuristic_tokens = extract_document_vocab_candidates(text)
        left_column_tokens = _extract_left_column_tokens(text)
        fallback_tokens = _merge_unique_tokens(left_column_tokens, heuristic_tokens)
        llm_tokens = _llm_filter_tokens(text=text, source_name=source_name, fallback_tokens=fallback_tokens)
        selected = llm_tokens or fallback_tokens
        if selected:
            return selected
        # Keep smart-import strict for document images to avoid importing OCR noise.
        return []
    return extract_normalized_tokens(text)


def _llm_filter_tokens(text: str, *, source_name: str, fallback_tokens: list[str]) -> list[str]:
    service = LLMService()
    llm_words = service.select_import_words_from_text(
        text=text,
        source_name=source_name,
        max_words=220,
    )
    if not llm_words:
        return []

    raw_tokens = set(extract_normalized_tokens(text))
    fallback_set = set(fallback_tokens)
    merged: list[str] = []
    seen: set[str] = set()
    for candidate in llm_words:
        lemma = simple_lemma(candidate.strip().lower())
        if not lemma or lemma in seen or not _is_import_token(lemma):
            continue
        if lemma not in raw_tokens and lemma not in fallback_set:
            continue
        seen.add(lemma)
        merged.append(lemma)
    return merged


def _llm_extract_tokens_from_image(*, filename: str, payload: bytes, max_words: int = 220) -> list[str]:
    source_type = _source_type_from_filename(filename)
    if source_type not in SMART_IMPORT_SOURCE_TYPES:
        return []
    mime = _mime_from_filename(filename)
    service = LLMService()
    words = service.select_import_words_from_image(
        payload=payload,
        mime_type=mime,
        source_name=filename,
        max_words=max_words,
    )
    merged: list[str] = []
    seen: set[str] = set()
    for candidate in words:
        lemma = simple_lemma(candidate.strip().lower())
        if not lemma or lemma in seen or not _is_import_token(lemma):
            continue
        seen.add(lemma)
        merged.append(lemma)
    return merged


def _extract_left_column_tokens(text: str, *, max_words: int = 300) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    words: list[str] = []
    seen: set[str] = set()

    for line in lines:
        match = re.match(r"^\s*(?:\d+\s*[\).:-]\s*)?([A-Za-z][A-Za-z'-]{2,})\b", line)
        if not match:
            continue
        token = simple_lemma(match.group(1).strip().lower())
        if not _is_import_token(token) or token in seen:
            continue

        remainder = line[match.end() :].strip().lower()
        looks_like_row = (
            not remainder
            or ":" in remainder
            or ";" in remainder
            or bool(re.search(r"\b(to|a|an|the|of|for|with|in|on|by|that|who|where|when|is|are|was|were)\b", remainder))
        )
        if not looks_like_row:
            continue

        seen.add(token)
        words.append(token)
        if len(words) >= max_words:
            break
    return words


def _merge_unique_tokens(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for token in list(primary) + list(secondary):
        if not token or token in seen:
            continue
        seen.add(token)
        merged.append(token)
    return merged


def _is_import_token(token: str) -> bool:
    if not re.fullmatch(r"[a-z][a-z'-]{1,32}(?: [a-z][a-z'-]{1,16})?", token):
        return False
    head = token.split(" ", 1)[0]
    return head not in IMPORT_NOISE_WORDS and head not in IMPORT_EXTRA_NOISE_WORDS


def _source_type_from_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".heic", ".bmp", ".webp")):
        return "IMAGE"
    if lowered.endswith(".pdf"):
        return "PDF"
    if lowered.endswith((".xls", ".xlsx", ".xlsm", ".csv")):
        return "EXCEL"
    return "TEXT"


def _mime_from_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".png"):
        return "image/png"
    if lowered.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lowered.endswith(".webp"):
        return "image/webp"
    if lowered.endswith(".bmp"):
        return "image/bmp"
    if lowered.endswith(".heic"):
        return "image/heic"
    return "image/jpeg"
