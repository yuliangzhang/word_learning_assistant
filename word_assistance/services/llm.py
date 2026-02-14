from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass

import httpx


@dataclass
class LLMRoute:
    command: str | None
    reply: str
    source: str


class LLMService:
    def __init__(
        self,
        *,
        model_override: str | None = None,
        museum_quality_model: str | None = None,
        museum_fast_model: str | None = None,
        museum_strategy: str | None = None,
    ) -> None:
        self.provider = os.getenv("WORD_ASSISTANCE_LLM_PROVIDER", "openai").strip().lower()
        self.base_url = os.getenv("WORD_ASSISTANCE_LLM_BASE_URL")
        self.model = os.getenv("WORD_ASSISTANCE_LLM_MODEL")
        if model_override:
            self.model = str(model_override).strip()

        if self.provider == "deepseek":
            self.api_key = os.getenv("DEEPSEEK_API_KEY")
            self.base_url = self.base_url or "https://api.deepseek.com/v1"
            self.model = self.model or "deepseek-chat"
            self.museum_quality_model = (
                os.getenv("WORD_ASSISTANCE_CARD_LLM_QUALITY_MODEL")
                or os.getenv("WORD_ASSISTANCE_MUSEUM_MODEL")
                or self.model
            )
            self.museum_fast_model = (
                os.getenv("WORD_ASSISTANCE_CARD_LLM_FAST_MODEL")
                or self.model
            )
            self.museum_strategy = os.getenv("WORD_ASSISTANCE_CARD_LLM_STRATEGY", "quality_first")
        else:
            self.api_key = os.getenv("OPENAI_API_KEY")
            self.base_url = self.base_url or "https://api.openai.com/v1"
            self.model = self.model or "gpt-4o-mini"
            # Card generation uses a stronger model by default, while preserving a fast fallback.
            self.museum_quality_model = (
                os.getenv("WORD_ASSISTANCE_CARD_LLM_QUALITY_MODEL")
                or os.getenv("WORD_ASSISTANCE_MUSEUM_MODEL")
                or "gpt-4.1-mini"
            )
            self.museum_fast_model = (
                os.getenv("WORD_ASSISTANCE_CARD_LLM_FAST_MODEL")
                or self.model
            )
            self.museum_strategy = os.getenv("WORD_ASSISTANCE_CARD_LLM_STRATEGY", "quality_first")

        if museum_quality_model:
            self.museum_quality_model = str(museum_quality_model).strip()
        if museum_fast_model:
            self.museum_fast_model = str(museum_fast_model).strip()
        if museum_strategy:
            self.museum_strategy = str(museum_strategy).strip().lower()
        else:
            self.museum_strategy = str(getattr(self, "museum_strategy", "quality_first")).strip().lower()

    def available(self) -> bool:
        return bool(self.api_key)

    def route_message(self, message: str, *, strict_mode: bool = False, llm_enabled: bool = True) -> LLMRoute:
        custom_words = extract_custom_learning_words(message)
        if not llm_enabled:
            if custom_words:
                return LLMRoute(
                    command=f"/learn --words {','.join(custom_words)}",
                    reply=f"已识别 {len(custom_words)} 个指定单词，先入词库并生成专属学习链接。",
                    source="heuristic",
                )
            return self._heuristic_route(message, strict_mode=strict_mode)
        if not self.available():
            if custom_words:
                return LLMRoute(
                    command=f"/learn --words {','.join(custom_words)}",
                    reply=f"已识别 {len(custom_words)} 个指定单词，先入词库并生成专属学习链接。",
                    source="heuristic",
                )
            return self._heuristic_route(message, strict_mode=strict_mode)

        try:
            plan = self._route_with_model(message, strict_mode=strict_mode)
            cmd = sanitize_command(plan.get("command", ""))
            if custom_words and (not cmd or cmd in {"/learn", "/today", "/words", "/review"}):
                cmd = f"/learn --words {','.join(custom_words)}"
            reply = str(plan.get("reply") or "").strip()
            if not reply:
                reply = "我理解了你的需求，马上帮你执行。" if cmd else "我来帮你继续学词。"
            return LLMRoute(command=cmd, reply=reply, source="llm")
        except Exception:
            return self._heuristic_route(message, strict_mode=strict_mode)

    def heuristic_route(self, message: str, *, strict_mode: bool = False) -> LLMRoute:
        return self._heuristic_route(message, strict_mode=strict_mode)

    def chat_reply(self, message: str, *, strict_mode: bool = False) -> str:
        if not self.available():
            return "我可以继续帮你做单词学习任务，比如 /today、/card antenna、/game spelling。"

        system = (
            "你是儿童词汇学习助手，输出中文短句，默认 2-4 句。"
            "不要让孩子执行命令行或暴露密钥。"
        )
        if strict_mode:
            system += "家长已开启严格模式：减少闲聊，聚焦学习动作。"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": message},
            ],
            "temperature": 0.4,
        }
        data = self._chat_completion(payload)
        content = _extract_content(data)
        return content or "我理解了，我们继续做单词学习任务。"

    def ocr_from_image_bytes(self, payload: bytes, mime_type: str) -> str:
        if not self.available():
            return ""
        if self.provider != "openai":
            return ""

        b64 = base64.b64encode(payload).decode("ascii")
        data_url = f"data:{mime_type};base64,{b64}"
        request = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You extract English words from images. Return plain text only.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Extract all English words only. Keep one line per phrase."},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                },
            ],
            "temperature": 0,
        }
        try:
            data = self._chat_completion(request)
            return _extract_content(data)
        except Exception:
            return ""

    def museum_word_payload(self, *, word: str, hints: dict | None = None, regenerate: bool = False) -> dict | None:
        if not self.available():
            return None

        hint_lines: list[str] = []
        hints = hints or {}
        for key in ("meaning_en", "meaning_zh", "examples", "tags"):
            value = hints.get(key)
            if isinstance(value, list) and value:
                hint_lines.append(f"{key}: " + "; ".join(str(v) for v in value[:3]))
        hint_text = "\n".join(hint_lines) if hint_lines else "none"

        instruction = (
            "你是英语词汇深度解构助手。"
            "请输出一个 JSON，用于生成博物馆级单词卡片。"
            "字段必须包含："
            "phonetic, "
            "origin_scene_zh, origin_scene_en, "
            "core_formula_zh, core_formula_en, "
            "explanation_zh, explanation_en, "
            "etymology_zh, etymology_en, "
            "cognates, nuance_points_zh, nuance_points_en, "
            "example_sentence, mermaid_code, epiphany。"
            "要求："
            "1) 内容必须与输入单词强相关，不得泛化模板化。"
            "2) 每个字段简洁：origin_scene<=40字，core_formula<=28字，explanation<=120字。"
            "3) cognates 为 2-4 个字符串；nuance_points_zh/nuance_points_en 各 2-4 条。"
            "4) mermaid_code 必须是 graph TD 开头的可渲染代码，且节点文字简练。"
            "5) semantic topology 结构必须体现：[词源/本义] -> [核心动作] -> [抽象含义/现代用法]，可有1-2个分支。"
            "6) mermaid 仅输出基础节点与箭头，不要 classDef/style/click/subgraph/HTML。"
            "7) epiphany 为中英双语一句话。"
        )
        if regenerate:
            instruction += "8) 这是重生成请求，请使用不同于常见教学模板的新叙事角度。"
        payload = {
            "messages": [
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": (
                        f"word={word}\n"
                        f"reference_hints:\n{hint_text}\n"
                        "输出 JSON，不要输出 Markdown。"
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.45 if regenerate else 0.2,
        }
        models = self._museum_model_chain(regenerate=regenerate, strategy=self.museum_strategy)
        best_candidate: dict | None = None
        for idx, model_name in enumerate(models):
            timeout = 42 if idx == 0 else 28
            try:
                data = self._chat_completion({**payload, "model": model_name}, timeout=timeout)
                content = _extract_content(data)
                if not content:
                    continue
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    continue
                parsed["_meta_model"] = model_name
                best_candidate = parsed
                if _is_high_signal_museum_payload(parsed, word=word):
                    return parsed
            except Exception:
                continue
        return best_candidate

    def word_lexicon_profile(self, *, word: str, hints: dict | None = None, prompt: str = "") -> dict | None:
        if not self.available():
            return None

        hint_lines: list[str] = []
        hints = hints or {}
        for key in ("meaning_en", "meaning_zh", "examples", "tags"):
            value = hints.get(key)
            if isinstance(value, list) and value:
                hint_lines.append(f"{key}: " + "; ".join(str(v) for v in value[:3]))
        hint_text = "\n".join(hint_lines) if hint_lines else "none"

        instruction = prompt.strip() or (
            "Return one JSON object only. "
            "Fields: canonical_lemma, is_valid, phonetic, meaning_en, meaning_zh, examples. "
            "meaning_en and meaning_zh each must contain 2-4 common meanings."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": f"word={word}\nreference_hints:\n{hint_text}\nJSON only."},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
        }
        try:
            data = self._chat_completion(payload)
            content = _extract_content(data)
            if not content:
                return None
            parsed = json.loads(content)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def select_import_words_from_text(self, *, text: str, source_name: str = "", max_words: int = 200) -> list[str]:
        if not self.available():
            return []
        if len(text.strip()) < 8:
            return []

        clipped = text.strip()
        if len(clipped) > 12000:
            clipped = clipped[:12000]

        instruction = (
            "You extract target vocabulary terms for student word-learning import. "
            "Return only actual learnable English vocabulary words from the source list/table. "
            "Exclude headings, school names, instructions, UI words, and sentence fragments. "
            "If rows are in format <word + definition>, keep only the left-side word. "
            "Return strict JSON with one field: words (array of lowercase strings)."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instruction},
                {
                    "role": "user",
                    "content": f"source={source_name or 'unknown'}\nmax_words={max_words}\ntext:\n{clipped}\nJSON only.",
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        try:
            data = self._chat_completion(payload)
            content = _extract_content(data)
            if not content:
                return []
            parsed = json.loads(content)
            raw_words = parsed.get("words") if isinstance(parsed, dict) else None
            return _sanitize_import_words(raw_words, limit=max_words)
        except Exception:
            return []

    def _route_with_model(self, message: str, *, strict_mode: bool) -> dict:
        instruction = (
            "你是命令规划器，目标是把用户自然语言转换为可执行命令。"
            "只允许命令: /learn, /learn --words WORD1,WORD2,..., /today, /words, /review, /new N, /mistakes, /card WORD, "
            "/game spelling|match|daily|dictation|cloze, /report week, /fix WRONG CORRECT。"
            "如果不需要执行命令，command 输出空字符串。"
            "输出 JSON，字段: command, reply。"
            "reply 要自然、简短、中文。"
        )
        if strict_mode:
            instruction += "严格模式：减少闲聊，优先给训练步骤。"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instruction},
                {"role": "user", "content": message},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        data = self._chat_completion(payload)
        content = _extract_content(data)
        if not content:
            raise RuntimeError("empty routing content")
        return json.loads(content)

    def _museum_model_chain(self, *, regenerate: bool, strategy: str) -> list[str]:
        quality = str(self.museum_quality_model or self.model).strip()
        fast = str(self.museum_fast_model or self.model).strip()
        if not quality and not fast:
            return [self.model]
        if not fast:
            return [quality]
        if not quality:
            return [fast]

        if strategy == "quality_first":
            ordered = [quality, fast]
        elif strategy == "fast_first":
            ordered = [fast, quality]
        else:
            # balanced: regenerate uses quality first; normal generation prefers speed first.
            ordered = [quality, fast] if regenerate else [fast, quality]
        # de-dup while preserving order
        deduped: list[str] = []
        for item in ordered:
            if item and item not in deduped:
                deduped.append(item)
        return deduped or [self.model]

    def _chat_completion(self, payload: dict, *, timeout: int = 40) -> dict:
        if not self.api_key:
            raise RuntimeError("missing llm api key")

        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    def _heuristic_route(self, message: str, *, strict_mode: bool) -> LLMRoute:
        text = message.strip()
        lowered = text.lower()
        custom_words = extract_custom_learning_words(text)
        if custom_words:
            return LLMRoute(
                command=f"/learn --words {','.join(custom_words)}",
                reply=f"已识别 {len(custom_words)} 个指定单词，先入词库并生成专属学习链接。",
                source="heuristic",
            )

        fix_match = re.search(r"把\s*([a-zA-Z'-]+)\s*改成\s*([a-zA-Z'-]+)", text)
        if not fix_match:
            fix_match = re.search(r"\b([a-zA-Z'-]+)\s*->\s*([a-zA-Z'-]+)\b", text)
        if fix_match:
            wrong = fix_match.group(1).lower()
            correct = fix_match.group(2).lower()
            return LLMRoute(
                command=f"/fix {wrong} {correct}",
                reply=f"收到，我会把 {wrong} 修正为 {correct}。",
                source="heuristic",
            )

        if "开始学习" in text or "学习词库" in text or "开始背单词" in text:
            return LLMRoute(command="/learn", reply="好的，我为你准备一条完整学习链路。", source="heuristic")
        if "所有单词" in text or "单词库" in text or "词库里" in text:
            return LLMRoute(command="/words", reply="我先把词库单词列给你。", source="heuristic")
        if "今日任务" in text or "今天任务" in text or "today" in lowered:
            return LLMRoute(command="/today", reply="我先帮你拉取今天任务。", source="heuristic")
        if "复习" in text or "review" in lowered:
            return LLMRoute(command="/review", reply="好的，马上开始复习。", source="heuristic")
        if "常错" in text or "mistake" in lowered:
            return LLMRoute(command="/mistakes", reply="我来列出常错词。", source="heuristic")
        if "周报" in text or "report" in lowered:
            return LLMRoute(command="/report week", reply="我会生成本周学习报告。", source="heuristic")
        if "拼写" in text or "spell" in lowered or "spelling" in lowered:
            return LLMRoute(command="/game spelling", reply="我们开始拼写训练。", source="heuristic")
        if "图文" in text or "匹配" in text or "match" in lowered:
            return LLMRoute(command="/game match", reply="开始释义匹配练习。", source="heuristic")
        if "听写" in text or "dictation" in lowered:
            return LLMRoute(command="/game dictation", reply="我们开始听写训练。", source="heuristic")
        if ("博物馆" in text or "museum" in lowered) and ("卡片" in text or "card" in lowered):
            return LLMRoute(
                command="/learn",
                reply="我先用今日学习词生成 Museum 卡，并带上配套练习。",
                source="heuristic",
            )

        word_match = re.search(r"\b([A-Za-z][A-Za-z'-]{1,24})\b", text)
        if ("解释" in text or "卡片" in text or "museum" in lowered or "card" in lowered) and word_match:
            word = word_match.group(1).lower()
            return LLMRoute(command=f"/card {word}", reply=f"我先为 {word} 生成学习卡片。", source="heuristic")

        reply = (
            "我可以直接执行学习动作。你可以说："
            "‘帮我开始学习词库单词’、‘今日学习这些词：appraise,bolster’、"
            "‘帮我看今天任务’、‘开始拼写练习’或‘把 antena 改成 antenna’。"
        )
        if strict_mode:
            reply = "请告诉我你要做哪项训练：今日任务、复习、卡片、练习或周报。"
        return LLMRoute(command=None, reply=reply, source="heuristic")


def sanitize_command(raw_command: str) -> str | None:
    if not raw_command:
        return None
    cmd = " ".join(raw_command.strip().split())
    if not cmd.startswith("/"):
        return None

    parts = cmd.split()
    name = parts[0].lower()

    if name in {"/today", "/review", "/mistakes"} and len(parts) == 1:
        return name
    if name == "/learn":
        learn_words = _extract_words_from_learn_command(cmd)
        regenerate = any(part.lower() in {"--new", "--regenerate"} for part in parts[1:])
        if learn_words:
            base = f"/learn --words {','.join(learn_words)}"
            return f"{base} --new" if regenerate else base
        if len(parts) == 1:
            return name
        if regenerate:
            return "/learn --new"
        return None
    if name == "/words" and len(parts) == 1:
        return name
    if name == "/new" and len(parts) == 2 and parts[1].isdigit():
        return f"/new {parts[1]}"
    if name == "/card" and len(parts) >= 2 and _word_ok(parts[1]):
        return f"/card {parts[1].lower()}"
    if name == "/game" and len(parts) >= 2 and parts[1].lower() in {
        "spelling",
        "spell",
        "match",
        "daily",
        "today",
        "combo",
        "dictation",
        "cloze",
    }:
        return f"/game {parts[1].lower()}"
    if name == "/report" and len(parts) >= 2 and parts[1].lower() == "week":
        return "/report week"
    if name == "/fix" and len(parts) >= 3 and _word_ok(parts[1]) and _word_ok(parts[2]):
        return f"/fix {parts[1].lower()} {parts[2].lower()}"
    return None


def _extract_content(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(str(item.get("text", "")))
        return "\n".join(texts).strip()
    return str(content).strip()


def _word_ok(token: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z][A-Za-z'-]{0,32}", token))


def _sanitize_import_words(values: object, *, limit: int = 200) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip().lower()
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        if not re.fullmatch(r"[a-z][a-z' -]{0,40}", text):
            continue
        if text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def extract_custom_learning_words(message: str) -> list[str]:
    text = str(message or "").strip()
    if not text:
        return []
    lowered = text.lower()
    intent_markers = (
        "今日要学习",
        "今天要学习",
        "学习如下单词",
        "学习这些单词",
        "学习这个单词表",
        "加入到词库",
        "加入词库",
        "单词表",
        "word list",
        "learn these",
        "study these",
        "指定",
    )
    if not any(marker in lowered for marker in intent_markers):
        return []

    segments = [text]
    if "：" in text:
        segments.append(text.split("：")[-1])
    if ":" in text:
        segments.append(text.split(":")[-1])

    for segment in reversed(segments):
        words = _extract_word_tokens(segment)
        if len(words) >= 2:
            return words

    words = _extract_word_tokens(text)
    if len(words) >= 3:
        return words
    return []


def _extract_words_from_learn_command(command: str) -> list[str]:
    compact = " ".join(str(command or "").split())
    parts = compact.split()
    lowered_parts = [part.lower() for part in parts]
    if "--words" in lowered_parts:
        idx = lowered_parts.index("--words")
        collected: list[str] = []
        for part in parts[idx + 1 :]:
            if part.startswith("--"):
                break
            collected.append(part)
        if collected:
            return _extract_word_tokens(" ".join(collected))
        return []
    if len(parts) > 1 and not any(part.startswith("--") for part in parts[1:]):
        return _extract_word_tokens(" ".join(parts[1:]))
    return []


def _extract_word_tokens(text: str) -> list[str]:
    blacklist = {
        "learn",
        "today",
        "words",
        "word",
        "list",
        "study",
        "these",
        "add",
        "into",
        "vocabulary",
    }
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]{1,32}", str(text or ""))
    cleaned: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        lemma = token.lower().strip("-'")
        if not lemma or lemma in blacklist:
            continue
        if not _word_ok(lemma):
            continue
        if lemma in seen:
            continue
        seen.add(lemma)
        cleaned.append(lemma)
    return cleaned


def _is_high_signal_museum_payload(payload: dict, *, word: str) -> bool:
    required = (
        "origin_scene_zh",
        "origin_scene_en",
        "core_formula_zh",
        "core_formula_en",
        "explanation_zh",
        "explanation_en",
        "etymology_zh",
        "etymology_en",
        "nuance_points_zh",
        "nuance_points_en",
        "example_sentence",
        "mermaid_code",
        "epiphany",
    )
    for key in required:
        value = payload.get(key)
        if isinstance(value, list):
            if not value:
                return False
            continue
        if not str(value or "").strip():
            return False

    mermaid = str(payload.get("mermaid_code") or "")
    if "graph TD" not in mermaid:
        return False
    labels = [str(x).strip().lower() for x in re.findall(r"\[(.*?)\]", mermaid) if str(x).strip()]
    if len(labels) < 4:
        return False
    generic = {"词源", "核心动作", "抽象含义", "现代用法", "etymology", "core action", "modern usage"}
    if sum(1 for label in labels if label in generic) >= 3:
        return False
    word_seed = re.sub(r"[^a-z]", "", word.lower())[:5]
    if not any(word_seed and word_seed in re.sub(r"[^a-z]", "", label) for label in labels):
        # allow etymology-driven nodes if not directly containing the word
        if not any(re.search(r"[a-z]{5,}|[\u4e00-\u9fff]{2,}", label) for label in labels):
            return False
    return True
