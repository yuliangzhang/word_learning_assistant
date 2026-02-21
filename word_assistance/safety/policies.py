from __future__ import annotations

import re
from dataclasses import dataclass

DISABLED_CAPABILITIES = {
    "web_search",
    "web_fetch",
    "browser",
    "shell_exec",
    "third_party_skill_auto_install",
}

TOOL_WHITELIST = {
    "text_extractor",
    "ocr_parser",
    "word_normalizer",
    "card_renderer",
    "exercise_renderer",
    "sqlite_storage",
}

PROMPT_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(previous|system)\s+instructions", re.IGNORECASE),
    re.compile(r"reveal\s+(the\s+)?(secret|token|api[_ -]?key|password)", re.IGNORECASE),
    re.compile(r"run\s+(shell|terminal|bash|zsh|powershell)\s+command", re.IGNORECASE),
    re.compile(r"install\s+.*skill", re.IGNORECASE),
]


@dataclass
class SafetyCheck:
    allowed: bool
    reason: str | None = None


def sanitize_untrusted_text(text: str) -> str:
    """Reader Agent stage: remove likely malicious instruction lines."""
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if any(pattern.search(line) for pattern in PROMPT_INJECTION_PATTERNS):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


def is_prompt_injection(text: str) -> bool:
    return any(pattern.search(text) for pattern in PROMPT_INJECTION_PATTERNS)


def validate_child_request(message: str) -> SafetyCheck:
    lowered = message.lower()
    blocked_terms = ["api key", "token", "shell", "终端", "命令行", "安装第三方"]
    if any(term in lowered for term in blocked_terms):
        return SafetyCheck(
            allowed=False,
            reason="This action requires parent approval. Please use the parent account in safety settings.",
        )
    return SafetyCheck(allowed=True)


def allowed_tools_for_role(role: str) -> set[str]:
    if role.upper() == "CHILD":
        return TOOL_WHITELIST
    return TOOL_WHITELIST
