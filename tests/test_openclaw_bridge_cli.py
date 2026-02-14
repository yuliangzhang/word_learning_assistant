from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "openclaw_workspace"
    / "skills"
    / "word-assistant"
    / "scripts"
    / "word_assistance_cli.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("word_assistance_cli", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_import_text_commit_all_calls_commit(monkeypatch):
    module = _load_module()
    calls: list[tuple[str, str, dict | None]] = []

    def fake_api_request(*, base_url, method, path, params=None, payload=None):
        calls.append((method, path, payload))
        if path == "/api/import/text":
            return {
                "import_id": 9,
                "preview_items": [
                    {"id": 100},
                    {"id": 101},
                ],
            }
        if path == "/api/import/commit":
            return {"ok": True, "imported_words": 2}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(module, "api_request", fake_api_request)

    args = argparse.Namespace(
        cmd="import-text",
        base_url="http://127.0.0.1:8000",
        user_id=2,
        text="antenna because",
        source_name="pytest",
        tags="Reading,Science",
        importer_role="CHILD",
        note=None,
        commit_all=True,
    )

    result = module.run(args)
    assert result["commit"]["imported_words"] == 2
    assert calls[1][1] == "/api/import/commit"
    assert calls[1][2]["accepted_item_ids"] == [100, 101]


def test_fix_lemma_raises_when_word_missing(monkeypatch):
    module = _load_module()

    def fake_api_request(*, base_url, method, path, params=None, payload=None):
        if path == "/api/words":
            return {"items": [{"id": 1, "lemma": "antenna"}]}
        raise AssertionError(f"unexpected path {path}")

    monkeypatch.setattr(module, "api_request", fake_api_request)

    args = argparse.Namespace(
        cmd="fix-lemma",
        base_url="http://127.0.0.1:8000",
        user_id=2,
        wrong="antena",
        correct="antenna",
        limit=200,
        reason="pytest",
        corrected_by_role="CHILD",
    )

    with pytest.raises(module.ApiError, match="word not found"):
        module.run(args)


def test_parent_settings_set_requires_fields():
    module = _load_module()
    args = argparse.Namespace(
        cmd="parent-settings-set",
        base_url="http://127.0.0.1:8000",
        child_user_id=2,
        daily_new_limit=None,
        daily_review_limit=None,
        strict_mode=None,
        llm_enabled=None,
        auto_tts=None,
        voice_accent=None,
        tts_voice=None,
    )
    with pytest.raises(module.ApiError, match="no setting fields provided"):
        module.run(args)


def test_parse_bool_variants():
    module = _load_module()
    assert module.parse_bool("true") is True
    assert module.parse_bool("0") is False
    with pytest.raises(argparse.ArgumentTypeError):
        module.parse_bool("maybe")
