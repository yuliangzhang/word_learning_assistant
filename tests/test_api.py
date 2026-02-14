from __future__ import annotations


def test_api_import_today_and_report_flow(client):
    preview = client.post(
        "/api/import/text",
        json={"user_id": 2, "text": "antenna because", "source_name": "api_test"},
    )
    assert preview.status_code == 200
    data = preview.json()
    assert data["preview_items"]

    chosen = [item["id"] for item in data["preview_items"]]
    commit = client.post("/api/import/commit", json={"import_id": data["import_id"], "accepted_item_ids": chosen})
    assert commit.status_code == 200
    assert commit.json()["imported_words"] >= 2

    today = client.get("/api/today", params={"user_id": 2})
    assert today.status_code == 200
    assert "task" in today.json()

    report = client.get("/api/report/week", params={"user_id": 2})
    assert report.status_code == 200
    report_payload = report.json()
    assert report_payload["html_url"].startswith("/artifacts/")
    assert report_payload["csv_url"].startswith("/artifacts/")


def test_parent_settings_persist_card_llm_config(client):
    current = client.get("/api/parent/settings", params={"child_user_id": 2})
    assert current.status_code == 200
    payload = {
        "child_user_id": 2,
        "card_llm_quality_model": "gpt-4.1-mini",
        "card_llm_fast_model": "gpt-4o-mini",
        "card_llm_strategy": "FAST_FIRST",
    }
    updated = client.put("/api/parent/settings", json=payload)
    assert updated.status_code == 200
    settings = updated.json()["settings"]
    assert settings["card_llm_quality_model"] == "gpt-4.1-mini"
    assert settings["card_llm_fast_model"] == "gpt-4o-mini"
    assert settings["card_llm_strategy"] == "FAST_FIRST"
