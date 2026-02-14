from __future__ import annotations

import word_assistance.app as app_module
from word_assistance.services.llm import LLMRoute


def test_chat_prefers_openclaw_when_available(client, monkeypatch):
    called: dict[str, str] = {}

    class FakeOpenClaw:
        def run_turn(self, *, user_id: int, message: str):
            called["message"] = message
            return type(
                "Turn",
                (),
                {
                    "reply": "OpenClaw 已执行今日任务。",
                    "links": ["/artifacts/reports/weekly_fake.html"],
                    "meta": {},
                },
            )()

    monkeypatch.setattr(app_module, "openclaw_service", FakeOpenClaw())
    resp = client.post("/api/chat", json={"user_id": 2, "message": "帮我开始今天任务"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_source"] == "openclaw"
    assert payload["route_command"] == "/today"
    assert called["message"] == "帮我开始今天任务"
    assert "/artifacts/reports/weekly_fake.html" in payload["links"]


def test_chat_falls_back_to_local_when_openclaw_is_text_only_for_action(client, monkeypatch):
    class FakeOpenClaw:
        def run_turn(self, *, user_id: int, message: str):
            return type(
                "Turn",
                (),
                {
                    "reply": "抱歉，我无法访问你的任务。",
                    "links": [],
                    "meta": {},
                },
            )()

    monkeypatch.setattr(app_module, "openclaw_service", FakeOpenClaw())
    resp = client.post("/api/chat", json={"user_id": 2, "message": "帮我开始今天任务"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_source"] in {"heuristic", "llm"}
    assert payload["route_command"] == "/today"
    assert "今日任务" in payload["reply"]


def test_chat_falls_back_when_openclaw_unavailable(client, monkeypatch):
    class FakeOpenClaw:
        def run_turn(self, *, user_id: int, message: str):
            return None

    monkeypatch.setattr(app_module, "openclaw_service", FakeOpenClaw())
    monkeypatch.setattr(
        app_module.llm_service,
        "route_message",
        lambda message, strict_mode=False, llm_enabled=True: LLMRoute(
            command="/mistakes",
            reply="我先帮你拉取常错词。",
            source="heuristic",
        ),
    )

    resp = client.post("/api/chat", json={"user_id": 2, "message": "看下我常错的词"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_source"] == "heuristic"
    assert payload["route_command"] == "/mistakes"
    assert "常错词" in payload["reply"]


def test_openclaw_status_endpoint(client, monkeypatch):
    class FakeOpenClaw:
        def status(self):
            return {"enabled": True, "available": True, "gateway": "up"}

    monkeypatch.setattr(app_module, "openclaw_service", FakeOpenClaw())
    resp = client.get("/api/openclaw/status")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True
    assert payload["gateway"] == "up"


def test_chat_today_phrase_routes_to_today(client, monkeypatch):
    class FakeOpenClaw:
        def run_turn(self, *, user_id: int, message: str):
            return None

    monkeypatch.setattr(app_module, "openclaw_service", FakeOpenClaw())
    resp = client.post("/api/chat", json={"user_id": 2, "message": "帮我开始今天任务"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_command"] == "/today"


def test_chat_local_only_mode_skips_openclaw(client, monkeypatch):
    client.put(
        "/api/parent/settings",
        json={"child_user_id": 2, "orchestration_mode": "LOCAL_ONLY"},
    )

    class FakeOpenClaw:
        def run_turn(self, *, user_id: int, message: str):
            raise AssertionError("openclaw should not be called in LOCAL_ONLY mode")

    monkeypatch.setattr(app_module, "openclaw_service", FakeOpenClaw())
    resp = client.post("/api/chat", json={"user_id": 2, "message": "帮我开始今天任务"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_command"] == "/today"
    assert payload["route_source"] != "openclaw"


def test_chat_openclaw_only_mode_returns_unavailable(client, monkeypatch):
    client.put(
        "/api/parent/settings",
        json={"child_user_id": 2, "orchestration_mode": "OPENCLAW_ONLY"},
    )

    class FakeOpenClaw:
        def run_turn(self, *, user_id: int, message: str):
            return None

    monkeypatch.setattr(app_module, "openclaw_service", FakeOpenClaw())
    resp = client.post("/api/chat", json={"user_id": 2, "message": "帮我开始今天任务"})
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["route_source"] == "openclaw_unavailable"
