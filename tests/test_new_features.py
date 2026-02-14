from __future__ import annotations

from pathlib import Path

from word_assistance.config import ARTIFACTS_DIR


def _seed_wrong_word(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "wrognword", "source_name": "seed_wrong"},
    )
    assert preview.status_code == 200
    items = preview.json()["preview_items"]
    commit = client.post(
        "/api/import/commit",
        json={"import_id": preview.json()["import_id"], "accepted_item_ids": [x["id"] for x in items]},
    )
    assert commit.status_code == 200


def test_word_correction_entry_and_history(client):
    _seed_wrong_word(client)

    words = client.get("/api/words", params={"user_id": 2}).json()["items"]
    wrong = next((w for w in words if w["lemma"] == "wrognword"), None)
    assert wrong is not None

    corrected = client.post(
        f"/api/words/{wrong['id']}/correct",
        json={
            "user_id": 2,
            "new_lemma": "wrongword",
            "new_surface": "wrongword",
            "reason": "test_fix",
            "corrected_by_role": "CHILD",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["word"]["lemma"] == "wrongword"

    history = client.get("/api/words/corrections", params={"user_id": 2}).json()["items"]
    assert any(item["old_lemma"] == "wrognword" and item["new_lemma"] == "wrongword" for item in history)


def test_word_correction_merges_when_target_already_exists(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "wrognword wrongword", "source_name": "seed_merge_fix"},
    )
    assert preview.status_code == 200
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    commit = client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})
    assert commit.status_code == 200

    words = client.get("/api/words", params={"user_id": 2}).json()["items"]
    wrong = next((w for w in words if w["lemma"] == "wrognword"), None)
    assert wrong is not None

    corrected = client.post(
        f"/api/words/{wrong['id']}/correct",
        json={
            "user_id": 2,
            "new_lemma": "wrongword",
            "new_surface": "wrongword",
            "reason": "merge_fix",
            "corrected_by_role": "CHILD",
        },
    )
    assert corrected.status_code == 200
    assert corrected.json()["word"]["lemma"] == "wrongword"

    after_words = client.get("/api/words", params={"user_id": 2}).json()["items"]
    lemmas = [item["lemma"] for item in after_words]
    assert "wrognword" not in lemmas
    assert lemmas.count("wrongword") == 1


def test_word_delete_entry(client):
    _seed_wrong_word(client)
    words = client.get("/api/words", params={"user_id": 2}).json()["items"]
    wrong = next((w for w in words if w["lemma"] == "wrognword"), None)
    assert wrong is not None

    deleted = client.delete(
        f"/api/words/{wrong['id']}",
        params={"user_id": 2, "deleted_by_role": "CHILD"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["word"]["lemma"] == "wrognword"

    words_after = client.get("/api/words", params={"user_id": 2}).json()["items"]
    assert all(item["lemma"] != "wrognword" for item in words_after)


def test_words_pagination_filter_and_status_update(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "alpha bravo charlie delta", "source_name": "seed_status"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})

    words = client.get("/api/words", params={"user_id": 2, "page": 1, "page_size": 2}).json()
    assert words["page_size"] == 2
    assert words["total"] >= 4
    first_word = words["items"][0]

    updated = client.post(
        f"/api/words/{first_word['id']}/status",
        json={"user_id": 2, "status": "MASTERED"},
    )
    assert updated.status_code == 200
    assert updated.json()["word"]["status"] == "MASTERED"

    mastered = client.get("/api/words", params={"user_id": 2, "status": "MASTERED"})
    assert mastered.status_code == 200
    assert any(item["id"] == first_word["id"] for item in mastered.json()["items"])


def test_chat_uses_llm_router_to_command(client):
    _seed_wrong_word(client)

    resp = client.post(
        "/api/chat",
        json={"user_id": 2, "message": "把 wrognword 改成 wrongword"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_command"] is not None
    assert payload["route_command"].startswith("/fix")


def test_chat_learn_flow_links_card_and_exercises(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "antenna because science school", "source_name": "seed_learn"},
    )
    assert preview.status_code == 200
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    commit = client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})
    assert commit.status_code == 200

    client.put(
        "/api/parent/settings",
        json={"child_user_id": 2, "orchestration_mode": "LOCAL_ONLY"},
    )
    resp = client.post("/api/chat", json={"user_id": 2, "message": "开始学习词库中的单词吧"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_command"] == "/learn"
    assert isinstance(payload.get("links"), list)
    assert len(payload["links"]) >= 3
    assert any("/artifacts/learning/" in link for link in payload["links"])
    assert any("/artifacts/exercises/" in link for link in payload["links"])


def test_chat_custom_word_list_adds_vocab_and_generates_target_links(client):
    client.put(
        "/api/parent/settings",
        json={"child_user_id": 2, "orchestration_mode": "LOCAL_ONLY"},
    )
    message = (
        "今日要学习如下单词，请将其加入到词库，并开始这些单词的学习："
        "appraise, bolster, expedite, exploits, fanatical, felicity, gruesome, incessant, ingenuous"
    )
    resp = client.post("/api/chat", json={"user_id": 2, "message": message})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_command"].startswith("/learn --words ")
    assert isinstance(payload.get("links"), list) and len(payload["links"]) >= 3
    assert any("/artifacts/learning/" in link for link in payload["links"])
    assert any("/artifacts/exercises/" in link for link in payload["links"])
    assert payload["data"]["source"] == "custom-word-list"
    assert payload["data"]["word_count"] == 9
    selected = set(payload["data"]["selected_words"])
    assert "appraise" in selected
    assert "bolster" in selected
    assert "expedite" in selected
    # exploits is normalized into exploit for consistent vocabulary storage
    assert "exploit" in selected

    words = client.get("/api/words", params={"user_id": 2, "limit": 200}).json()["items"]
    lemmas = {item["lemma"] for item in words}
    assert {"appraise", "bolster", "expedite", "fanatical", "felicity", "gruesome", "incessant", "ingenuous"}.issubset(lemmas)


def test_learn_card_url_endpoint(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "accommodate", "source_name": "seed_card_url"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})

    resp = client.get("/api/learn/card-url", params={"user_id": 2, "word": "accommodate"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["url"].startswith("/artifacts/cards/accommodate/")


def test_chat_can_list_words_from_natural_language(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "antenna because", "source_name": "seed_words"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})

    client.put(
        "/api/parent/settings",
        json={"child_user_id": 2, "orchestration_mode": "LOCAL_ONLY"},
    )
    resp = client.post("/api/chat", json={"user_id": 2, "message": "单词库所有的单词"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_command"] == "/words"
    assert "词库单词如下" in payload["reply"]


def test_game_spell_and_match_share_cached_daily_page(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "antenna because science", "source_name": "seed_game"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})

    client.put("/api/parent/settings", json={"child_user_id": 2, "orchestration_mode": "LOCAL_ONLY"})

    spell = client.post("/api/chat", json={"user_id": 2, "message": "/game spelling"}).json()
    match = client.post("/api/chat", json={"user_id": 2, "message": "/game match"}).json()
    spell_url = spell["links"][0]
    match_url = match["links"][0]
    assert "#spell" in spell_url
    assert "#match" in match_url
    assert spell_url.split("#")[0] == match_url.split("#")[0]


def test_learning_hub_sidebar_scroll_card_fit_and_pron_button(client):
    words = " ".join(
        [
            "accommodate",
            "necessary",
            "definitely",
            "environment",
            "government",
            "antenna",
            "discipline",
            "sentence",
            "forgery",
            "perjury",
            "fraud",
            "penalty",
            "vandalism",
            "reformatory",
            "burglary",
            "criminal",
            "bribery",
            "corruption",
            "assault",
            "conviction",
            "assassination",
            "accomplice",
            "arson",
            "slander",
        ]
    )
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": words, "source_name": "seed_hub_scroll_fit"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})

    client.put("/api/parent/settings", json={"child_user_id": 2, "orchestration_mode": "LOCAL_ONLY"})
    payload = client.post("/api/chat", json={"user_id": 2, "message": "/learn --new"}).json()
    hub_url = next(link for link in payload["links"] if "/artifacts/learning/" in link)
    hub_path = ARTIFACTS_DIR / hub_url.replace("/artifacts/", "")
    html = Path(hub_path).read_text(encoding="utf-8")

    assert "overflow-y: auto;" in html
    assert 'id="play-pron"' in html
    assert "fitCardFrame" in html
    assert "doc.body.style.transform = 'none'" in html
    assert "doc.body.style.overflowY = 'auto'" in html
    assert "html.style.overflowY = 'auto'" in html
    assert "scaleW" not in html


def test_daily_spell_page_hides_answer_word_and_uses_audio_trigger(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "accommodate necessary", "source_name": "seed_spell_audio"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})

    payload = client.post("/api/chat", json={"user_id": 2, "message": "/game spelling"}).json()
    spell_url = payload["links"][0]
    html_url = spell_url.split("#")[0]
    html_path = ARTIFACTS_DIR / html_url.replace("/artifacts/", "")
    html = Path(html_path).read_text(encoding="utf-8")

    assert "Spell the word for:" not in html
    assert "audio-btn" in html
    assert "/api/speech/tts" in html
    assert "/api/review" in html


def test_daily_match_page_is_definition_matching_with_pagination(client):
    words = " ".join(f"term{chr(97 + i)}{chr(97 + (i // 26))}" for i in range(25))
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": words, "source_name": "seed_match_paging"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})

    payload = client.post("/api/chat", json={"user_id": 2, "message": "/game match"}).json()
    match_url = payload["links"][0]
    html_url = match_url.split("#")[0]
    html_path = ARTIFACTS_DIR / html_url.replace("/artifacts/", "")
    html = Path(html_path).read_text(encoding="utf-8")

    assert "释义匹配" in html
    assert "match-shell" in html
    assert "line-layer" in html
    assert "data.match_page_size" in html
    assert "select data-idx" not in html


def test_learn_flow_persists_meanings_for_question_bank(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "necessary environment government", "source_name": "seed_meaning"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})

    chat = client.post("/api/chat", json={"user_id": 2, "message": "/learn"})
    assert chat.status_code == 200

    words = client.get("/api/words", params={"user_id": 2}).json()["items"]
    by_lemma = {item["lemma"]: item for item in words}
    assert by_lemma["necessary"]["meaning_en"]
    assert by_lemma["necessary"]["meaning_zh"]


def test_parent_settings_export_backup_and_voices(client):
    get_settings = client.get("/api/parent/settings", params={"child_user_id": 2})
    assert get_settings.status_code == 200

    update = client.put(
        "/api/parent/settings",
        json={
            "child_user_id": 2,
            "daily_new_limit": 5,
            "daily_review_limit": 12,
            "orchestration_mode": "LOCAL_ONLY",
            "ocr_strength": "ACCURATE",
            "correction_auto_accept_threshold": 0.93,
            "strict_mode": True,
            "llm_enabled": True,
            "voice_accent": "en-GB",
            "tts_voice": "en-GB-RyanNeural",
            "auto_tts": True,
        },
    )
    assert update.status_code == 200
    settings = update.json()["settings"]
    assert settings["daily_new_limit"] == 5
    assert settings["strict_mode"] is True
    assert settings["orchestration_mode"] == "LOCAL_ONLY"
    assert settings["ocr_strength"] == "ACCURATE"
    assert settings["correction_auto_accept_threshold"] == 0.93

    today = client.get("/api/today", params={"user_id": 2})
    assert today.status_code == 200
    assert today.json()["limits"]["new"] == 5

    exported = client.get("/api/parent/export/words", params={"user_id": 2, "fmt": "csv"})
    assert exported.status_code == 200
    assert exported.json()["url"].startswith("/artifacts/exports/")

    backup = client.post("/api/parent/backup")
    assert backup.status_code == 200
    assert backup.json()["backup_url"].startswith("/artifacts/backups/")

    voices = client.get("/api/speech/voices")
    assert voices.status_code == 200
    assert "en-GB" in voices.json()["voices"]


def test_week_report_contains_word_practice_stats(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "antenna", "source_name": "seed_report_stats"},
    )
    item_ids = [x["id"] for x in preview.json()["preview_items"]]
    client.post("/api/import/commit", json={"import_id": preview.json()["import_id"], "accepted_item_ids": item_ids})
    word = client.get("/api/words", params={"user_id": 2}).json()["items"][0]

    client.post(
        "/api/review",
        json={
            "user_id": 2,
            "word_id": word["id"],
            "passed": True,
            "mode": "SPELLING",
            "error_type": "SPELLING",
            "user_answer": "antenna",
            "correct_answer": "antenna",
        },
    )
    client.post(
        "/api/review",
        json={
            "user_id": 2,
            "word_id": word["id"],
            "passed": False,
            "mode": "MATCH",
            "error_type": "MEANING",
            "user_answer": "wrong",
            "correct_answer": "antenna",
        },
    )

    report = client.get("/api/report/week", params={"user_id": 2})
    assert report.status_code == 200
    stats = report.json()["report"]["word_practice_stats"]
    target = next((item for item in stats if item["lemma"] == "antenna"), None)
    assert target is not None
    assert target["practice_total"] >= 2
    assert target["correct_count"] >= 1


def test_dictionary_lookup_and_add_flow(client):
    lookup = client.get(
        "/api/dictionary/card",
        params={"user_id": 2, "word": "interstellar"},
    )
    assert lookup.status_code == 200
    payload = lookup.json()
    assert payload["in_vocab"] is False
    assert payload["url"].startswith("/artifacts/dictionary/")

    add = client.post("/api/dictionary/add", json={"user_id": 2, "word": "interstellar"})
    assert add.status_code == 200
    assert add.json()["ok"] is True

    lookup_after = client.get("/api/dictionary/card", params={"user_id": 2, "word": "interstellar"})
    assert lookup_after.status_code == 200
    assert lookup_after.json()["in_vocab"] is True


def test_card_command_unknown_word_does_not_auto_insert_into_vocab(client):
    resp = client.post("/api/chat", json={"user_id": 2, "message": "/card intergalactic"})
    assert resp.status_code == 200
    payload = resp.json()
    assert "未自动新增" in payload["reply"]
    assert payload["links"]
    assert "/artifacts/dictionary/" in payload["links"][0]

    words_after = client.get("/api/words", params={"user_id": 2}).json()["items"]
    assert all(item["lemma"] != "intergalactic" for item in words_after)


def test_import_text_respects_auto_accept_threshold(client):
    client.put(
        "/api/parent/settings",
        json={
            "child_user_id": 2,
            "correction_auto_accept_threshold": 0.98,
        },
    )
    high_threshold = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "book"},
    )
    assert high_threshold.status_code == 200
    high_item = high_threshold.json()["preview_items"][0]
    assert high_item["accepted"] == 0
    assert high_item["needs_confirmation"] is True

    client.put(
        "/api/parent/settings",
        json={
            "child_user_id": 2,
            "correction_auto_accept_threshold": 0.8,
        },
    )
    low_threshold = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "book"},
    )
    assert low_threshold.status_code == 200
    low_item = low_threshold.json()["preview_items"][0]
    assert low_item["accepted"] == 1
    assert low_item["needs_confirmation"] is False
