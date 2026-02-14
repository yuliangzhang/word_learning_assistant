---
name: word-lexicon-enricher
description: Query bilingual word meanings (EN/ZH), phonetic, and examples, then persist them into local word records for practice generation and card rendering.
---

## Trigger

Use this skill when a word lacks reliable `meaning_en/meaning_zh/examples/phonetic`, or when imported words look like OCR misspellings.

## Workflow

1. Normalize lemma (lowercase, trim symbols) and load existing word fields.
2. If data is already complete, do nothing.
3. Query lexical profile with structured JSON output.
4. If likely misspelling, include correction hint in Chinese and keep trace.
5. Persist results to storage fields:
   - `words.phonetic`
   - `words.meaning_en` (array)
   - `words.meaning_zh` (array)
   - `words.examples` (array)
6. Reuse persisted data for exercises/cards to reduce repeated token cost.

## Output Contract

The lexical profile must include:
- `canonical_lemma`
- `is_valid`
- `phonetic`
- `meaning_en` (2-4 items)
- `meaning_zh` (2-4 items)
- `examples` (1-3 items)

## Safety

- Do not execute arbitrary web commands.
- Never expose API keys.
- If lookup is uncertain, return conservative meanings and a correction hint instead of fabricating details.
