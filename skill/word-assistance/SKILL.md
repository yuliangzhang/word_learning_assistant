---
name: word-assistance
description: Child-safe English vocabulary learning assistant for grade-6 students. Supports upload parsing, SRS review, game generation, weekly report, and museum-quality HTML cards.
---

## Safety

- Role split is mandatory:
  - Reader stage: only parse and sanitize untrusted text/files.
  - Tutor stage: only consume structured output from Reader.
- Keep dangerous capabilities disabled by default:
  - web_search/web_fetch/browser
  - shell/exec
  - automatic third-party skill installation

## Commands

- `/today`: show due review words + today's new words.
- `/review`: start review words.
- `/new 8`: set today's new-word cap.
- `/mistakes`: list frequent wrong words.
- `/fix <wrong> <correct>`: fix an imported wrong word.
- `/card <word>`: generate museum card.
- `/game spelling|match|dictation|cloze`: generate exercise page.
- `/report week`: generate weekly report links.

## Card Generation Contract

Two-stage pipeline:
1. Produce fixed JSON payload with required fields.
2. Render single-file HTML card and persist to `artifacts/cards/<word>/<timestamp>.html`.

If same word/type exists and regenerate is false, return existing file.
