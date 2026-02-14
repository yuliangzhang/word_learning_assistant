from __future__ import annotations

import re

from word_assistance.pipeline.corrections import suggest_correction
from word_assistance.pipeline.extraction import (
    PHRASAL_PARTICLES,
    extract_document_vocab_candidates,
    extract_normalized_tokens,
    extract_text_from_bytes,
    simple_lemma,
)
from word_assistance.safety.policies import sanitize_untrusted_text
from word_assistance.services.llm import LLMService

SMART_IMPORT_SOURCE_TYPES = {"IMAGE", "PDF"}


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
    threshold = _normalize_auto_accept_threshold(auto_accept_threshold)

    items: list[dict] = []
    seen_lemmas: set[str] = set()

    for token in tokens_with_phrases:
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
        llm_tokens = _llm_filter_tokens(text=text, source_name=source_name, fallback_tokens=heuristic_tokens)
        selected = llm_tokens or heuristic_tokens
        if selected:
            return selected
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


def _is_import_token(token: str) -> bool:
    return bool(re.fullmatch(r"[a-z][a-z'-]{1,32}(?: [a-z][a-z'-]{1,16})?", token))


def _source_type_from_filename(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".heic", ".bmp", ".webp")):
        return "IMAGE"
    if lowered.endswith(".pdf"):
        return "PDF"
    if lowered.endswith((".xls", ".xlsx", ".xlsm", ".csv")):
        return "EXCEL"
    return "TEXT"
