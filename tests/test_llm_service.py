from __future__ import annotations

from word_assistance.services.llm import (
    LLMService,
    _is_high_signal_museum_payload,
    extract_custom_learning_words,
    sanitize_command,
)


def test_museum_model_chain_balanced_prefers_fast_then_quality(monkeypatch):
    monkeypatch.setenv("WORD_ASSISTANCE_LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("WORD_ASSISTANCE_LLM_MODEL", "gpt-4o-mini")
    monkeypatch.setenv("WORD_ASSISTANCE_CARD_LLM_QUALITY_MODEL", "gpt-4.1-mini")
    monkeypatch.delenv("WORD_ASSISTANCE_CARD_LLM_FAST_MODEL", raising=False)
    monkeypatch.setenv("WORD_ASSISTANCE_CARD_LLM_STRATEGY", "balanced")

    service = LLMService()
    chain_normal = service._museum_model_chain(regenerate=False, strategy="balanced")
    chain_regen = service._museum_model_chain(regenerate=True, strategy="balanced")

    assert chain_normal == ["gpt-4o-mini", "gpt-4.1-mini"]
    assert chain_regen == ["gpt-4.1-mini", "gpt-4o-mini"]


def test_high_signal_museum_payload_detection():
    low_signal = {
        "origin_scene_zh": "测试",
        "origin_scene_en": "test",
        "core_formula_zh": "测试",
        "core_formula_en": "test",
        "explanation_zh": "测试",
        "explanation_en": "test",
        "etymology_zh": "测试",
        "etymology_en": "test",
        "cognates": ["a", "b"],
        "nuance_points_zh": ["测试"],
        "nuance_points_en": ["test"],
        "example_sentence": "test",
        "mermaid_code": "graph TD\nA[词源]-->B[核心动作]\nB-->C[抽象含义]\nB-->D[现代用法]",
        "epiphany": "test",
    }
    assert _is_high_signal_museum_payload(low_signal, word="penitentiary") is False

    high_signal = {
        "origin_scene_zh": "修道院里反省者被隔离并改造",
        "origin_scene_en": "A secluded place where offenders are confined and reformed.",
        "core_formula_zh": "惩戒 + 改造 = penitentiary",
        "core_formula_en": "penalty + reform = penitentiary",
        "explanation_zh": "强调惩戒与改造并存的长期监禁机构。",
        "explanation_en": "It denotes a long-term prison focused on punishment and rehabilitation.",
        "etymology_zh": "源自拉丁语 paenitentia（悔恨）。",
        "etymology_en": "From Latin paenitentia (repentance).",
        "cognates": ["penitent", "penitence"],
        "nuance_points_zh": ["区别于普通 jail，语义更偏改造"],
        "nuance_points_en": ["Unlike jail, it stresses rehabilitation."],
        "example_sentence": "The penitentiary combines confinement with reform programs.",
        "mermaid_code": (
            "graph TD\n"
            "A[paenitentia 悔恨] --> B[惩戒并改造]\n"
            "B --> C[长期监禁机构]\n"
            "B --> D[rehabilitation over revenge]"
        ),
        "epiphany": "惩罚若不导向改造，只会复制伤害。 | Punishment without reform repeats harm.",
    }
    assert _is_high_signal_museum_payload(high_signal, word="penitentiary") is True


def test_sanitize_command_supports_learn_custom_word_list():
    cmd = sanitize_command("/learn --words appraise, bolster, expedite")
    assert cmd == "/learn --words appraise,bolster,expedite"


def test_extract_custom_learning_words_from_message():
    words = extract_custom_learning_words(
        "今日要学习如下单词，请加入词库：appraise, bolster, expedite, fanatical"
    )
    assert words == ["appraise", "bolster", "expedite", "fanatical"]
