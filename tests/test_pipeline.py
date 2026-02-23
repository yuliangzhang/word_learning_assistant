from __future__ import annotations

import word_assistance.pipeline.importer as importer_module
from word_assistance.pipeline.importer import build_import_preview_from_file, build_import_preview_from_text


def test_extract_and_normalize_with_phrasal_and_dedup():
    text = "Running runs ran. Take off and take off."
    preview = build_import_preview_from_text(text)
    lemmas = [item["final_lemma"] for item in preview]

    assert "run" in lemmas
    assert "take off" in lemmas
    assert lemmas.count("take off") == 1


def test_ocr_error_has_correction_candidates():
    text = "becau5e sc1ence"
    preview = build_import_preview_from_text(text)
    mapping = {item["word_candidate"]: item for item in preview}

    assert mapping["becau5e"]["suggested_correction"] == "because"
    assert mapping["becau5e"]["confidence"] <= 0.82
    assert mapping["becau5e"]["needs_confirmation"] is True


def test_common_word_edit_distance_correction():
    preview = build_import_preview_from_text("antena")
    mapping = {item["word_candidate"]: item for item in preview}

    assert mapping["antena"]["suggested_correction"] == "antenna"
    assert mapping["antena"]["needs_confirmation"] is True


def test_smart_import_from_ocr_text_filters_header_noise():
    text = """
    NORTH SHORE Coaching College
    Develop Your English Skills
    Level: 5 Lesson: 4 Page: 0
    SPELLING LIST & WORD DEFINITIONS
    arson the crime of setting fire to a building
    accomplice a person who helps another especially in crime
    assassination a murder especially for political reasons
    """
    preview = build_import_preview_from_text(text, source_type="IMAGE", source_name="sheet.jpg")
    lemmas = [item["final_lemma"] for item in preview]

    assert "arson" in lemmas
    assert "accomplice" in lemmas
    assert "assassination" in lemmas
    assert "north" not in lemmas
    assert "shore" not in lemmas
    assert "develop" not in lemmas
    assert "english" not in lemmas


def test_import_preview_preserves_ous_words_and_lemmatizes_plural_safely():
    preview = build_import_preview_from_text("ingenuous exploits")
    lemmas = [item["final_lemma"] for item in preview]

    assert "ingenuous" in lemmas
    assert "exploit" in lemmas


def test_smart_import_image_does_not_fallback_to_all_ocr_noise():
    text = """
    NORTH SHORE Coaching College
    Develop Your English Skills
    Level: 6 Lesson: 4 Page: 0
    """
    preview = build_import_preview_from_text(text, source_type="IMAGE", source_name="sheet.jpg")
    assert preview == []


def test_import_preview_file_uses_llm_image_fallback_when_ocr_empty(monkeypatch):
    monkeypatch.setattr(importer_module, "extract_text_from_bytes", lambda **_kwargs: "")
    monkeypatch.setattr(
        importer_module.LLMService,
        "select_import_words_from_image",
        lambda *_args, **_kwargs: ["accomplish", "altitude", "north", "concession", "equitation"],
    )

    extracted, preview = build_import_preview_from_file(
        filename="wordlist.jpg",
        payload=b"fake-image-bytes",
        ocr_strength="BALANCED",
        auto_accept_threshold=0.85,
    )
    lemmas = [item["final_lemma"] for item in preview]

    assert "accomplish" in lemmas
    assert "altitude" in lemmas
    assert "concession" in lemmas
    assert "equitation" in lemmas
    assert "north" not in lemmas
    assert extracted
