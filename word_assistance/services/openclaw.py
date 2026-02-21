from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class OpenClawTurnResult:
    reply: str
    links: list[str]
    meta: dict[str, Any]


class OpenClawAgentService:
    def __init__(self) -> None:
        self.enabled = os.getenv("WORD_ASSISTANCE_OPENCLAW_ENABLED", "1").strip() not in {"0", "false", "False"}
        self.profile = os.getenv("WORD_ASSISTANCE_OPENCLAW_PROFILE", "word-assistant").strip() or "word-assistant"
        self.agent_id = os.getenv("WORD_ASSISTANCE_OPENCLAW_AGENT_ID", "main").strip() or "main"
        self.session_prefix = os.getenv("WORD_ASSISTANCE_OPENCLAW_SESSION_PREFIX", "word-assistance").strip() or "word-assistance"
        self.timeout_sec = max(10, int(os.getenv("WORD_ASSISTANCE_OPENCLAW_TIMEOUT_SEC", "45")))
        self.failure_cooldown_sec = max(5, int(os.getenv("WORD_ASSISTANCE_OPENCLAW_FAILURE_COOLDOWN_SEC", "30")))
        self.gateway_health_timeout_ms = max(1000, int(os.getenv("WORD_ASSISTANCE_OPENCLAW_HEALTH_TIMEOUT_MS", "6000")))

        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._last_failure_at: float | None = None

        self.openclaw_bin = (
            shutil.which("openclaw")
            or shutil.which("/opt/homebrew/bin/openclaw")
            or shutil.which("/usr/local/bin/openclaw")
        )

    def status(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "enabled": self.enabled,
            "available": bool(self.enabled and self.openclaw_bin),
            "profile": self.profile,
            "agent_id": self.agent_id,
        }
        if not self.enabled:
            data["reason"] = "disabled_by_env"
            return data
        if not self.openclaw_bin:
            data["reason"] = "openclaw_not_found"
            return data

        if self._cooldown_active():
            data["cooldown"] = True
            data["last_error"] = self._last_error

        cmd = [
            self.openclaw_bin,
            "--profile",
            self.profile,
            "health",
            "--json",
            "--timeout",
            str(self.gateway_health_timeout_ms),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=self._runtime_env())
        if proc.returncode != 0:
            data["gateway"] = "down"
            data["reason"] = self._first_non_empty_line(proc.stderr) or "health_check_failed"
            return data

        data["gateway"] = "up"
        parsed = self._extract_json(proc.stdout)
        if isinstance(parsed, dict):
            data["health_ok"] = bool(parsed.get("ok", True))
            default_agent = parsed.get("defaultAgentId")
            if isinstance(default_agent, str) and default_agent:
                data["default_agent_id"] = default_agent
        return data

    def run_turn(self, *, user_id: int, message: str) -> OpenClawTurnResult | None:
        if not self.enabled or not self.openclaw_bin:
            return None

        text = message.strip()
        if not text:
            return None

        if self._cooldown_active():
            return None

        session_id = f"{self.session_prefix}-{user_id}"
        cmd = [
            self.openclaw_bin,
            "--profile",
            self.profile,
            "agent",
            "--local",
            "--agent",
            self.agent_id,
            "--session-id",
            session_id,
            "--message",
            text,
            "--json",
            "--timeout",
            str(self.timeout_sec),
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec + 10,
                env=self._runtime_env(),
            )
        except Exception as exc:
            self._record_failure(f"openclaw_subprocess_error: {exc}")
            return None

        if proc.returncode != 0:
            self._record_failure(self._first_non_empty_line(proc.stderr) or "openclaw_agent_failed")
            return None

        payload = self._extract_json(proc.stdout)
        if not isinstance(payload, dict):
            self._record_failure("openclaw_output_not_json")
            return None

        reply, links = self._extract_reply_and_links(payload)
        if not reply and not links:
            self._record_failure("openclaw_empty_payload")
            return None

        self._clear_failure()
        return OpenClawTurnResult(reply=reply or "Done.", links=links, meta=payload)

    def _runtime_env(self) -> dict[str, str]:
        env = os.environ.copy()
        path_items = ["/opt/homebrew/opt/node@22/bin", "/opt/homebrew/bin", env.get("PATH", "")]
        env["PATH"] = ":".join(item for item in path_items if item)
        return env

    def _extract_reply_and_links(self, payload: dict[str, Any]) -> tuple[str, list[str]]:
        container = payload
        if isinstance(payload.get("result"), dict):
            container = payload["result"]

        payloads = container.get("payloads")
        if not isinstance(payloads, list):
            payloads = []

        texts: list[str] = []
        links: list[str] = []
        for item in payloads:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            if text:
                texts.append(text)
            media_url = item.get("mediaUrl")
            if isinstance(media_url, str) and media_url.strip():
                links.append(media_url.strip())
            media_urls = item.get("mediaUrls")
            if isinstance(media_urls, list):
                for url in media_urls:
                    if isinstance(url, str) and url.strip():
                        links.append(url.strip())

        reply = "\n\n".join(texts).strip()
        if not reply:
            summary = container.get("summary") or payload.get("summary")
            if isinstance(summary, str):
                reply = summary.strip()

        dedup_links = list(dict.fromkeys(links))
        return reply, dedup_links

    def _extract_json(self, text: str) -> Any:
        raw = text.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        lines = [line for line in raw.splitlines() if line.strip()]
        for idx in range(len(lines)):
            candidate = "\n".join(lines[idx:])
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
        return None

    def _first_non_empty_line(self, text: str) -> str:
        for line in text.splitlines():
            if line.strip():
                return line.strip()
        return ""

    def _cooldown_active(self) -> bool:
        with self._lock:
            if self._last_failure_at is None:
                return False
            return (time.time() - self._last_failure_at) < self.failure_cooldown_sec

    def _record_failure(self, error_message: str) -> None:
        with self._lock:
            self._last_error = error_message
            self._last_failure_at = time.time()

    def _clear_failure(self) -> None:
        with self._lock:
            self._last_error = None
            self._last_failure_at = None
