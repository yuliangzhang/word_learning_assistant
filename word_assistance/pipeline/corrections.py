from __future__ import annotations

import re

COMMON_WORDS = {
    "accommodate",
    "antenna",
    "because",
    "definitely",
    "between",
    "business",
    "children",
    "classroom",
    "dictionary",
    "different",
    "environment",
    "example",
    "exercise",
    "family",
    "future",
    "grammar",
    "history",
    "holiday",
    "important",
    "journal",
    "science",
    "school",
    "knowledge",
    "language",
    "listen",
    "museum",
    "necessary",
    "practice",
    "private",
    "question",
    "reading",
    "remember",
    "review",
    "government",
    "sentence",
    "spelling",
    "student",
    "teacher",
    "through",
    "tomorrow",
    "vocabulary",
    "weather",
    "friend",
    "beautiful",
    "library",
    "word",
    "learning",
}

CONFUSION_MAP = str.maketrans(
    {
        "0": "o",
        "1": "l",
        "2": "z",
        "3": "e",
        "4": "a",
        "5": "s",
        "6": "g",
        "7": "t",
        "8": "b",
        "9": "g",
        "$": "s",
        "@": "a",
        "!": "i",
    }
)


def suggest_correction(word: str) -> dict:
    """Return correction result with confidence and manual confirmation flag."""
    original = word.strip().lower()
    candidate = original
    confidence = 0.96
    needs_confirmation = False
    changed = False

    if not candidate:
        return {
            "word_candidate": original,
            "suggested_correction": original,
            "confidence": 0.5,
            "needs_confirmation": True,
        }

    if re.search(r"[0-9$@!]", candidate):
        normalized = candidate.translate(CONFUSION_MAP)
        if normalized != candidate:
            candidate = normalized
            confidence = min(confidence, 0.7)
            needs_confirmation = True
            changed = True

    for wrong, right, penalty in (
        ("rn", "m", 0.14),
        ("vv", "w", 0.16),
        ("cl", "d", 0.18),
    ):
        if wrong in candidate:
            merged = candidate.replace(wrong, right)
            if merged != candidate:
                candidate = merged
                confidence = min(confidence, 1 - penalty)
                needs_confirmation = True
                changed = True

    if candidate not in COMMON_WORDS:
        nearest, distance = _closest_common_word(candidate)
        if nearest and nearest != candidate and distance <= 2:
            candidate = nearest
            confidence = min(confidence, 0.84 if distance == 1 else 0.76)
            needs_confirmation = True
            changed = True

    if len(candidate) <= 2:
        confidence = min(confidence, 0.55)
        needs_confirmation = True

    if candidate in COMMON_WORDS and candidate != original:
        confidence = min(max(confidence, 0.72), 0.84)
        needs_confirmation = True

    if candidate == original and candidate in COMMON_WORDS:
        confidence = 0.99
        needs_confirmation = False

    if changed and candidate != original and confidence < 0.9:
        needs_confirmation = True

    return {
        "word_candidate": original,
        "suggested_correction": candidate,
        "confidence": round(confidence, 2),
        "needs_confirmation": needs_confirmation,
    }


def _closest_common_word(token: str) -> tuple[str | None, int]:
    best_word: str | None = None
    best_distance = 3
    for known in COMMON_WORDS:
        if abs(len(known) - len(token)) > 2:
            continue
        distance = _levenshtein_with_cutoff(token, known, cutoff=2)
        if distance < best_distance:
            best_distance = distance
            best_word = known
            if distance == 1:
                break
    return best_word, best_distance


def _levenshtein_with_cutoff(a: str, b: str, cutoff: int) -> int:
    if a == b:
        return 0
    if abs(len(a) - len(b)) > cutoff:
        return cutoff + 1

    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i]
        row_min = i
        for j, char_b in enumerate(b, start=1):
            insertions = current[j - 1] + 1
            deletions = previous[j] + 1
            substitutions = previous[j - 1] + (char_a != char_b)
            cost = min(insertions, deletions, substitutions)
            current.append(cost)
            row_min = min(row_min, cost)
        if row_min > cutoff:
            return cutoff + 1
        previous = current
    return previous[-1]
