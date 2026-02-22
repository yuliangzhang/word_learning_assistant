from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

from word_assistance.config import EXERCISES_DIR

UTC = timezone.utc
MATCH_PAGE_SIZE = 20
DAILY_COMBO_SCHEMA_VERSION = "v5"


def build_exercise(
    *,
    session_type: str,
    words: list[dict],
) -> tuple[Path, dict]:
    if not words:
        raise ValueError("no words for exercise")

    timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    folder = EXERCISES_DIR / session_type.lower()
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{timestamp}.html"

    question_payload = _question_payload(session_type, words)
    html = _render_exercise_page(session_type, question_payload)
    html_path.write_text(html, encoding="utf-8")

    return html_path, {"questions": len(question_payload), "type": session_type}


def build_daily_combo_exercise(
    *,
    user_id: int,
    words: list[dict],
    regenerate: bool = False,
) -> tuple[Path, dict]:
    if not words:
        raise ValueError("no words for exercise")

    today = datetime.now(UTC).strftime("%Y%m%d")
    serial = [
        {
            "id": int(word.get("id", 0)),
            "lemma": str(word.get("lemma", "")).lower(),
            "status": str(word.get("status", "")),
            "updated_at": str(word.get("updated_at", "")),
            "meaning_en": tuple(str(v).strip() for v in (word.get("meaning_en") or [])[:2]),
            "meaning_zh": tuple(str(v).strip() for v in (word.get("meaning_zh") or [])[:2]),
        }
        for word in words
    ]
    fingerprint_payload = {
        "schema": DAILY_COMBO_SCHEMA_VERSION,
        "items": serial,
    }
    fingerprint = hashlib.sha1(json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:14]
    folder = EXERCISES_DIR / "daily"
    folder.mkdir(parents=True, exist_ok=True)
    html_path = folder / f"{today}_u{user_id}_{fingerprint}.html"

    cached = html_path.exists()
    if cached and not regenerate:
        return html_path, {"type": "DAILY_COMBO", "questions": len(words), "cached": True, "fingerprint": fingerprint}

    spell_questions = _question_payload("SPELL", words)
    match_questions = _question_payload("MATCH", words)
    html = _render_daily_combo_page(
        user_id=user_id,
        words=words,
        spell_questions=spell_questions,
        match_questions=match_questions,
    )
    html_path.write_text(html, encoding="utf-8")
    return html_path, {
        "type": "DAILY_COMBO",
        "questions": len(words),
        "cached": False,
        "fingerprint": fingerprint,
    }


def _question_payload(session_type: str, words: list[dict]) -> list[dict]:
    payload: list[dict] = []
    normalized_type = session_type.upper()
    if normalized_type == "MATCH":
        for idx, word in enumerate(words):
            answer = str(word["lemma"]).lower()
            definition_text = _compose_definition(word, lemma=answer, default="Common meaning is pending lexicon enrichment.")
            payload.append(
                {
                    "uid": str(idx + 1),
                    "word_id": int(word.get("id") or 0),
                    "word": answer,
                    "definition_text": definition_text,
                    "answer": answer,
                    "type": "match",
                }
            )
    elif normalized_type == "SPELL":
        for word in words:
            answer = str(word["lemma"]).lower()
            clue = _compose_definition(word, lemma=answer, default="Tap 🔊 for pronunciation, then spell the word.")
            payload.append(
                {
                    "uid": str(word.get("id") or answer),
                    "word_id": int(word.get("id") or 0),
                    "clue": clue,
                    "answer": answer,
                    "type": "spell",
                }
            )
    elif normalized_type == "DICTATION":
        for word in words:
            payload.append(
                {
                    "prompt": f"Dictation: type the word you hear -> {word['lemma']}",
                    "answer": word["lemma"],
                    "type": "dictation",
                }
            )
    elif normalized_type == "CLOZE":
        for word in words:
            payload.append(
                {
                    "prompt": f"Fill in the blank: I used ____ in my sentence ({word['lemma']}).",
                    "answer": word["lemma"],
                    "type": "cloze",
                }
            )
    else:
        raise ValueError(f"unsupported exercise type: {session_type}")
    return payload


def _render_exercise_page(session_type: str, questions: list[dict]) -> str:
    dataset = json.dumps(questions, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{session_type} Exercise</title>
  <style>
    :root {{ --bg:#f6faf7; --ink:#162024; --accent:#1e7f5e; --card:#fff; --line:#d3e8dd; }}
    body {{ margin:0; font-family:'Avenir Next', Arial, sans-serif; background:linear-gradient(135deg,#f6faf7,#ecf5ff); color:var(--ink); }}
    .wrap {{ max-width:900px; margin:20px auto; padding:16px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:12px; }}
    input {{ width:100%; padding:10px; font-size:16px; border:1px solid #bcd7ca; border-radius:8px; }}
    button {{ background:var(--accent); color:#fff; border:0; border-radius:8px; padding:10px 16px; font-size:16px; cursor:pointer; }}
    .result {{ margin-top:14px; font-weight:700; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>{session_type} Practice</h1>
    <p>Submit when finished. The system will compute score and mistakes.</p>
    <div id=\"list\"></div>
    <button id=\"submit\">Submit</button>
    <div id=\"result\" class=\"result\"></div>
  </div>
  <script>
    const questions = {dataset};
    const list = document.getElementById('list');

    questions.forEach((q, idx) => {{
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `<div><b>#${{idx + 1}}</b> ${{q.prompt}}</div><input data-idx="${{idx}}" placeholder="Type your answer" />`;
      list.appendChild(card);
    }});

    document.getElementById('submit').addEventListener('click', () => {{
      let correct = 0;
      const mistakes = [];
      document.querySelectorAll('input[data-idx]').forEach((input) => {{
        const idx = Number(input.dataset.idx);
        const user = (input.value || '').trim().toLowerCase();
        const expected = questions[idx].answer.toLowerCase();
        if (user === expected) {{
          correct += 1;
        }} else {{
          mistakes.push({{ prompt: questions[idx].prompt, expected: questions[idx].answer, user }});
        }}
      }});
      const score = Math.round((correct / questions.length) * 100);
      const summary = `Score: ${{score}} (${{correct}}/${{questions.length}})`;
      const resultEl = document.getElementById('result');
      resultEl.textContent = mistakes.length ? summary + `, mistakes: ${{mistakes.length}}` : summary + ', perfect!';
    }});
  </script>
</body>
</html>
"""


def _render_daily_combo_page(*, user_id: int, words: list[dict], spell_questions: list[dict], match_questions: list[dict]) -> str:
    match_pages = _build_match_pages(match_questions, page_size=MATCH_PAGE_SIZE)
    payload = json.dumps(
        {
            "words": [str(word.get("lemma", "")).lower() for word in words if word.get("lemma")],
            "spell": spell_questions,
            "match_pages": match_pages,
            "match_page_size": MATCH_PAGE_SIZE,
        },
        ensure_ascii=False,
    )
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Daily Practice Combo</title>
  <style>
    :root {{ --bg:#f6faf7; --ink:#162024; --accent:#1e7f5e; --card:#fff; --line:#d3e8dd; --muted:#5e7480; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:'Avenir Next', Arial, sans-serif; background:linear-gradient(135deg,#f6faf7,#ecf5ff); color:var(--ink); }}
    .wrap {{ max-width:1000px; margin:0 auto; padding:18px; }}
    .header {{ display:flex; justify-content:space-between; align-items:end; gap:12px; flex-wrap:wrap; }}
    .tabs {{ display:flex; gap:8px; flex-wrap:wrap; margin:14px 0 10px; }}
    .tab-btn {{ border:1px solid var(--line); background:#fff; padding:8px 14px; border-radius:999px; cursor:pointer; font-weight:700; }}
    .tab-btn.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
    .top-controls {{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }}
    .top-controls select {{ padding:8px 10px; border:1px solid #bcd7ca; border-radius:8px; background:#fff; }}
    .hint {{ color:var(--muted); font-size:14px; }}
    .hint.small {{ font-size:12px; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:10px; }}
    input {{ width:100%; padding:10px; font-size:16px; border:1px solid #bcd7ca; border-radius:8px; margin-top:8px; }}
    button.primary {{ background:var(--accent); color:#fff; border:0; border-radius:8px; padding:10px 16px; font-size:16px; cursor:pointer; }}
    button.secondary {{ background:#fff; color:var(--ink); border:1px solid var(--line); border-radius:8px; padding:8px 12px; font-size:14px; cursor:pointer; }}
    .actions {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:10px; }}
    .result {{ margin-top:14px; font-weight:700; white-space:pre-line; }}
    .result.good {{ color:#0f766e; }}
    .result.bad {{ color:#9f1239; }}
    .spell-head {{ display:flex; justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap; }}
    .audio-btn {{ border:1px solid #9bc8b8; background:#ecfff8; color:#0d5c46; border-radius:999px; padding:7px 11px; cursor:pointer; font-weight:700; }}
    .audio-btn:disabled {{ opacity:.6; cursor:not-allowed; }}
    .clue {{ color:#4b606b; font-size:14px; margin-top:8px; }}
    .spell-progress {{ font-size:13px; color:var(--muted); margin-bottom:8px; }}
    .spell-actions {{ display:flex; gap:8px; flex-wrap:wrap; margin-top:10px; }}
    .big-submit {{
      width: 100%;
      margin-top: 10px;
      padding: 12px 16px;
      border-radius: 10px;
      border: 0;
      background: #0f766e;
      color: #fff;
      font-size: 17px;
      font-weight: 700;
      cursor: pointer;
    }}
    .feedback {{ margin-top: 10px; font-weight: 700; min-height: 24px; }}
    .feedback.good {{ color:#0f766e; }}
    .feedback.bad {{ color:#9f1239; }}
    .summary-card {{
      background: #fff;
      border: 1px solid #cde4d9;
      border-radius: 12px;
      padding: 14px;
    }}
    .summary-card h3 {{ margin: 0 0 10px; }}
    .match-shell {{
      position: relative;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 14px;
      min-height: 380px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 12px;
    }}
    .match-col {{
      border: 1px solid #e4ece8;
      border-radius: 10px;
      padding: 10px;
      background: #fcfefd;
      min-height: 320px;
    }}
    .col-title {{
      font-size: 14px;
      font-weight: 800;
      color: #3f5560;
      margin-bottom: 8px;
    }}
    .match-list {{
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .match-item {{
      border: 1px solid #c8d7d0;
      border-radius: 8px;
      background: #fff;
      padding: 8px 10px;
      font-size: 15px;
      text-align: left;
      cursor: pointer;
      position: relative;
      z-index: 2;
      min-height: 44px;
      display: flex;
      align-items: center;
    }}
    .match-item.left.active {{
      border-color: #0f766e;
      background: #e2faf2;
      box-shadow: inset 0 0 0 1px #0f766e;
    }}
    .match-item.left.mapped {{
      border-color: #0f766e66;
      background: #f4fffb;
    }}
    .match-item.right.used {{
      border-color: #2c7a7b;
      background: #f0fcff;
    }}
    .line-layer {{
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 1;
    }}
    .pager {{
      display:flex;
      align-items:center;
      gap:10px;
      flex-wrap:wrap;
      margin-top:12px;
    }}
    .hidden {{ display:none !important; }}
    @media (max-width: 860px) {{
      .match-shell {{ grid-template-columns: 1fr; min-height: auto; }}
      .match-col {{ min-height: auto; }}
    }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"header\">
      <div>
        <h1 style=\"margin:0;\">Today's Practice (Spelling + Definition Match)</h1>
        <div class=\"hint\">Generated from today's task and cached for reuse.</div>
      </div>
      <div class=\"hint\">Word count: {len(words)}</div>
    </div>
    <div class=\"tabs\">
      <button class=\"tab-btn\" data-mode=\"spell\">Spelling</button>
      <button class=\"tab-btn\" data-mode=\"match\">Definition Match</button>
    </div>
    <div class=\"top-controls\">
      <label class=\"hint\">Pronunciation accent:</label>
      <select id=\"accent\">
        <option value=\"en-GB\">UK (en-GB)</option>
        <option value=\"en-AU\">AU (en-AU)</option>
        <option value=\"en-US\">US (en-US)</option>
      </select>
      <span class=\"hint\">For spelling: tap 🔊 first, then type your spelling (tablet handwriting keyboard works too).</span>
    </div>
    <div id=\"list\"></div>
    <div id=\"pager\" class=\"pager hidden\">
      <button id=\"prev-page\" class=\"secondary\">Prev Page</button>
      <span id=\"page-info\" class=\"hint\"></span>
      <button id=\"next-page\" class=\"secondary\">Next Page</button>
    </div>
    <div class=\"actions\">
      <button id=\"submit\" class=\"primary\">Submit Current Matching</button>
      <span class=\"hint\">Hash shortcuts: #spell / #match</span>
    </div>
    <div id=\"result\" class=\"result\"></div>
  </div>
  <script>
    const USER_ID = {user_id};
    const data = {payload};
    let mode = (location.hash || '#spell').replace('#', '');
    if (!['spell', 'match'].includes(mode)) mode = 'spell';

    const list = document.getElementById('list');
    const result = document.getElementById('result');
    const buttons = [...document.querySelectorAll('.tab-btn')];
    const pager = document.getElementById('pager');
    const pageInfo = document.getElementById('page-info');
    const accentSelect = document.getElementById('accent');
    const audioCache = new Map();
    const submitBtn = document.getElementById('submit');
    const encouragements = [
      'Well done!',
      'Excellent!',
      'Great job!',
      'You nailed it!',
      'Brilliant!',
      'Fantastic!'
    ];

    const state = {{
      matchPage: 0,
      activeLeft: null,
      matchSelections: {{}},
      spellIndex: 0,
      spellAttemptByUid: {{}},
      spellSummary: {{
        totalWords: (data.spell || []).length,
        totalAttempts: 0,
        completed: 0,
        mistakes: {{}},
      }},
    }};

    function currentQuestions() {{
      if (mode === 'match') {{
        const page = data.match_pages[state.matchPage] || {{ pairs: [] }};
        return page.pairs || [];
      }}
      return data.spell || [];
    }}

    function currentMatchPage() {{
      return data.match_pages[state.matchPage] || {{ pairs: [], definitions: [] }};
    }}

    function normalizeSpelling(value) {{
      return String(value || '').trim().toLowerCase();
    }}

    async function persistAttempts(attempts) {{
      if (!Array.isArray(attempts) || !attempts.length) {{
        return {{ saved: 0, failed: 0 }};
      }}
      const requests = attempts
        .filter(item => Number(item.word_id) > 0)
        .map((item) => {{
          return fetch('/api/review', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{
              user_id: USER_ID,
              word_id: Number(item.word_id),
              passed: Boolean(item.passed),
              mode: item.mode,
              error_type: item.error_type,
              user_answer: item.user_answer || '',
              correct_answer: item.correct_answer || '',
            }}),
          }});
        }});
      if (!requests.length) {{
        return {{ saved: 0, failed: 0 }};
      }}
      const settled = await Promise.allSettled(requests);
      let saved = 0;
      let failed = 0;
      for (const item of settled) {{
        if (item.status === 'fulfilled' && item.value && item.value.ok) {{
          saved += 1;
        }} else {{
          failed += 1;
        }}
      }}
      return {{ saved, failed }};
    }}

    async function persistSingleAttempt(attempt) {{
      return persistAttempts([attempt]);
    }}

    function playAudio(word, btn) {{
      if (!word) return;
      const accent = accentSelect.value || 'en-GB';
      const key = `${{accent}}:${{word}}`;
      const loadAndPlay = async () => {{
        if (!audioCache.has(key)) {{
          const res = await fetch('/api/speech/tts', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ text: word, accent }}),
          }});
          if (!res.ok) {{
            throw new Error(await res.text());
          }}
          const payload = await res.json();
          audioCache.set(key, payload.audio_url);
        }}
        const audio = new Audio(audioCache.get(key));
        await audio.play();
      }};

      btn.disabled = true;
      loadAndPlay()
        .catch((err) => {{
          alert('Audio playback failed: ' + err.message);
        }})
        .finally(() => {{
          btn.disabled = false;
        }});
    }}

    function ensurePageSelection() {{
      if (!state.matchSelections[state.matchPage]) {{
        state.matchSelections[state.matchPage] = {{}};
      }}
      return state.matchSelections[state.matchPage];
    }}

    function drawLines() {{
      const svg = document.getElementById('line-layer');
      const shell = document.querySelector('.match-shell');
      if (!svg || !shell) return;

      const shellRect = shell.getBoundingClientRect();
      svg.setAttribute('viewBox', `0 0 ${{Math.round(shellRect.width)}} ${{Math.round(shellRect.height)}}`);
      svg.innerHTML = '';

      const colors = ['#0f766e', '#2563eb', '#be123c', '#7c3aed', '#ca8a04', '#0369a1'];
      const pairs = currentMatchPage().pairs || [];
      const selections = ensurePageSelection();

      pairs.forEach((pair, idx) => {{
        const rightId = selections[pair.uid];
        if (!rightId) return;
        const leftEl = document.querySelector(`.match-item.left[data-uid="${{pair.uid}}"]`);
        const rightEl = document.querySelector(`.match-item.right[data-defid="${{rightId}}"]`);
        if (!leftEl || !rightEl) return;

        const l = leftEl.getBoundingClientRect();
        const r = rightEl.getBoundingClientRect();
        const x1 = l.right - shellRect.left - 4;
        const y1 = l.top - shellRect.top + l.height / 2;
        const x2 = r.left - shellRect.left + 4;
        const y2 = r.top - shellRect.top + r.height / 2;
        const c1 = x1 + 56;
        const c2 = x2 - 56;
        const color = colors[idx % colors.length];

        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', `M ${{x1}} ${{y1}} C ${{c1}} ${{y1}}, ${{c2}} ${{y2}}, ${{x2}} ${{y2}}`);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke', color);
        path.setAttribute('stroke-width', '2.5');
        path.setAttribute('stroke-linecap', 'round');
        svg.appendChild(path);
      }});
    }}

    function renderMatchBoard() {{
      const page = currentMatchPage();
      const pairs = page.pairs || [];
      const defs = page.definitions || [];
      const selections = ensurePageSelection();
      const usedDefs = new Set(Object.values(selections));

      list.innerHTML = `
        <div class="match-shell">
          <svg id="line-layer" class="line-layer"></svg>
          <section class="match-col">
            <div class="col-title">Words (tap here first)</div>
            <div class="match-list" id="left-list"></div>
          </section>
          <section class="match-col">
            <div class="col-title">Definitions (tap here second)</div>
            <div class="match-list" id="right-list"></div>
          </section>
        </div>
      `;

      const leftWrap = document.getElementById('left-list');
      const rightWrap = document.getElementById('right-list');

      pairs.forEach((pair, idx) => {{
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'match-item left';
        btn.dataset.uid = pair.uid;
        const mapped = selections[pair.uid];
        if (state.activeLeft === pair.uid) btn.classList.add('active');
        if (mapped) btn.classList.add('mapped');
        btn.textContent = `${{idx + 1}}. ${{pair.word}}`;
        btn.addEventListener('click', () => {{
          state.activeLeft = pair.uid;
          render();
        }});
        leftWrap.appendChild(btn);
      }});

      defs.forEach((def, idx) => {{
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'match-item right';
        btn.dataset.defid = def.id;
        if (usedDefs.has(def.id)) {{
          btn.classList.add('used');
        }}
        btn.innerHTML = `<span>${{String.fromCharCode(65 + (idx % 26))}}. ${{def.text}}</span>`;
        btn.addEventListener('click', () => {{
          if (!state.activeLeft) return;
          const pageSelection = ensurePageSelection();
          pageSelection[state.activeLeft] = def.id;
          state.activeLeft = null;
          render();
        }});
        rightWrap.appendChild(btn);
      }});

      drawLines();
    }}

    function renderSpellSummary() {{
      const totalWords = state.spellSummary.totalWords || 1;
      const completed = state.spellSummary.completed;
      const attempts = state.spellSummary.totalAttempts;
      const accuracy = Math.round((completed / totalWords) * 100);
      const mistakeWords = Object.keys(state.spellSummary.mistakes);
      const mistakesHtml = mistakeWords.length
        ? `<ul>${{mistakeWords.map((word) => `<li>${{word}}</li>`).join('')}}</ul>`
        : '<p>No wrong words in this round.</p>';
      list.innerHTML = `
        <div class="summary-card">
          <h3>Spelling Session Complete</h3>
          <p><b>Words:</b> ${{totalWords}}</p>
          <p><b>Completed:</b> ${{completed}} / ${{totalWords}}</p>
          <p><b>Total attempts:</b> ${{attempts}}</p>
          <p><b>Completion accuracy:</b> ${{accuracy}}%</p>
          <h4>Words to revisit</h4>
          ${{mistakesHtml}}
          <div class="spell-actions">
            <button id="restart-spell" class="secondary" type="button">Practice Again</button>
            <a href="#match" class="secondary" style="text-decoration:none;display:inline-flex;align-items:center;">Go to Definition Match</a>
          </div>
        </div>
      `;
      const restart = document.getElementById('restart-spell');
      if (restart) {{
        restart.addEventListener('click', () => {{
          state.spellIndex = 0;
          state.spellAttemptByUid = {{}};
          state.spellSummary = {{
            totalWords: (data.spell || []).length,
            totalAttempts: 0,
            completed: 0,
            mistakes: {{}},
          }};
          result.textContent = '';
          render();
        }});
      }}
    }}

    function renderSpellStep() {{
      const questions = data.spell || [];
      if (!questions.length) {{
        list.innerHTML = '<div class="card">No spelling words for today.</div>';
        return;
      }}
      if (state.spellIndex >= questions.length) {{
        renderSpellSummary();
        return;
      }}

      const q = questions[state.spellIndex];
      const uid = String(q.uid || state.spellIndex);
      const attempts = Number(state.spellAttemptByUid[uid] || 0);
      const revealAnswer = attempts >= 3;

      list.innerHTML = `
        <div class="card">
          <div class="spell-progress">Word ${{state.spellIndex + 1}} / ${{questions.length}}</div>
          <div class="spell-head">
            <div><b>Listen and spell</b></div>
            <button type="button" id="spell-audio" class="audio-btn" data-word="${{q.answer}}">🔊 Play Audio</button>
          </div>
          <div class="clue">${{q.clue || 'Tap 🔊 then spell the word.'}}</div>
          <input id="spell-input" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="Type the spelling here" />

          <button type="button" id="spell-submit" class="big-submit">Submit</button>
          <div id="spell-feedback" class="feedback"></div>
          <div id="spell-post-actions" class="spell-actions ${{revealAnswer ? '' : 'hidden'}}">
            <button type="button" id="retry-word" class="secondary">Try Again</button>
            <button type="button" id="next-word" class="secondary">Next Word</button>
          </div>
        </div>
      `;

      const input = document.getElementById('spell-input');
      const audioBtn = document.getElementById('spell-audio');
      const feedback = document.getElementById('spell-feedback');
      const postActions = document.getElementById('spell-post-actions');

      audioBtn.addEventListener('click', () => playAudio(audioBtn.dataset.word || '', audioBtn));

      const goNext = () => {{
        state.spellIndex += 1;
        result.textContent = '';
        render();
      }};

      if (revealAnswer) {{
        feedback.className = 'feedback bad';
        feedback.textContent = `Correct answer: ${{q.answer}}`;
      }}

      document.getElementById('retry-word').addEventListener('click', () => {{
        state.spellAttemptByUid[uid] = 0;
        input.value = '';
        feedback.className = 'feedback';
        feedback.textContent = '';
        postActions.classList.add('hidden');
      }});
      document.getElementById('next-word').addEventListener('click', goNext);

      document.getElementById('spell-submit').addEventListener('click', async () => {{
        const user = normalizeSpelling(input.value);
        const expected = normalizeSpelling(q.answer);
        if (!user) {{
          feedback.className = 'feedback bad';
          feedback.textContent = 'Type a spelling first.';
          return;
        }}

        state.spellSummary.totalAttempts += 1;
        state.spellAttemptByUid[uid] = Number(state.spellAttemptByUid[uid] || 0) + 1;
        const attemptCount = state.spellAttemptByUid[uid];
        const passed = user === expected;
        await persistSingleAttempt({{
          word_id: Number(q.word_id || 0),
          passed,
          mode: 'SPELLING',
          error_type: 'SPELLING',
          user_answer: user || '',
          correct_answer: expected,
        }});

        if (passed) {{
          state.spellSummary.completed += 1;
          const msg = encouragements[Math.floor(Math.random() * encouragements.length)];
          feedback.className = 'feedback good';
          feedback.textContent = `${{msg}} ✔`;
          setTimeout(goNext, 700);
          return;
        }}

        state.spellSummary.mistakes[expected] = true;
        if (attemptCount >= 3) {{
          feedback.className = 'feedback bad';
          feedback.textContent = `Not quite. Correct answer: ${{q.answer}}`;
          postActions.classList.remove('hidden');
        }} else {{
          feedback.className = 'feedback bad';
          feedback.textContent = `Try again (${{
            attemptCount
          }}/3).`;
        }}
      }});

      input.addEventListener('keydown', (event) => {{
        if (event.key === 'Enter') {{
          event.preventDefault();
          document.getElementById('spell-submit').click();
        }}
      }});
    }}

    function updatePager() {{
      if (mode !== 'match' || !Array.isArray(data.match_pages) || data.match_pages.length <= 1) {{
        pager.classList.add('hidden');
        return;
      }}
      pager.classList.remove('hidden');
      pageInfo.textContent = `Page ${{state.matchPage + 1}} / ${{data.match_pages.length}} (up to ${{data.match_page_size}} words/page)`;
      document.getElementById('prev-page').disabled = state.matchPage <= 0;
      document.getElementById('next-page').disabled = state.matchPage >= data.match_pages.length - 1;
    }}

    function render() {{
      buttons.forEach(btn => btn.classList.toggle('active', btn.dataset.mode === mode));
      if (mode === 'match') {{
        renderMatchBoard();
        submitBtn.classList.remove('hidden');
      }} else {{
        renderSpellStep();
        submitBtn.classList.add('hidden');
      }}
      updatePager();
      if (mode !== 'match') {{
        result.textContent = '';
      }}
    }}

    buttons.forEach(btn => btn.addEventListener('click', () => {{
      mode = btn.dataset.mode;
      location.hash = mode;
      state.activeLeft = null;
      render();
    }}));

    window.addEventListener('hashchange', () => {{
      const next = (location.hash || '#spell').replace('#', '');
      if (['spell', 'match'].includes(next) && next !== mode) {{
        mode = next;
        state.activeLeft = null;
        render();
      }}
    }});

    document.getElementById('prev-page').addEventListener('click', () => {{
      if (state.matchPage <= 0) return;
      state.matchPage -= 1;
      state.activeLeft = null;
      render();
    }});

    document.getElementById('next-page').addEventListener('click', () => {{
      if (state.matchPage >= data.match_pages.length - 1) return;
      state.matchPage += 1;
      state.activeLeft = null;
      render();
    }});

    window.addEventListener('resize', () => {{
      if (mode === 'match') drawLines();
    }});

    document.getElementById('submit').addEventListener('click', async () => {{
      let correct = 0;
      let total = 0;
      const mistakes = [];
      const attempts = [];
      if (mode === 'match') {{
        const pages = data.match_pages || [];
        pages.forEach((page, pageIdx) => {{
          const selection = state.matchSelections[pageIdx] || {{}};
          (page.pairs || []).forEach((pair) => {{
            total += 1;
            const chosen = String(selection[pair.uid] || '');
            const expected = String(pair.answer || '');
            const passed = chosen === expected;
            attempts.push({{
              word_id: Number(pair.word_id || 0),
              passed,
              mode: 'MATCH',
              error_type: 'MEANING',
              user_answer: chosen || '',
              correct_answer: expected,
            }});
            if (chosen === expected) {{
              correct += 1;
            }} else {{
              mistakes.push(`- ${{pair.word}} => your choice: ${{chosen || '(blank)'}}, expected: ${{expected}}`);
            }}
          }});
        }});
      }} else {{
        const questions = data.spell || [];
        questions.forEach((q, idx) => {{
          total += 1;
          const node = document.querySelector(`input[data-idx="${{idx}}"]`);
          const user = (node && node.value || '').trim().toLowerCase();
          const expected = String(q.answer || '').toLowerCase();
          const passed = user === expected;
          attempts.push({{
            word_id: Number(q.word_id || 0),
            passed,
            mode: 'SPELLING',
            error_type: 'SPELLING',
            user_answer: user || '',
            correct_answer: expected,
          }});
          if (user === expected) {{
            correct += 1;
          }} else {{
            mistakes.push(`- #${{idx + 1}} your spelling: ${{user || '(blank)'}}, expected: ${{expected}}`);
          }}
        }});
      }}

      total = total || 1;
      const score = Math.round((correct / total) * 100);
      const recordSummary = await persistAttempts(attempts);
      const head = `Mode: ${{mode === 'match' ? 'Definition Match' : 'Spelling'}}\\nScore: ${{score}} (${{correct}}/${{total}})`;
      const records = `\\nSaved attempts: ${{recordSummary.saved}}${{recordSummary.failed ? `, failed writes ${{recordSummary.failed}}` : ''}}`;
      result.textContent = mistakes.length
        ? head + records + "\\nMistakes:\\n" + mistakes.join("\\n")
        : head + records + "\\nPerfect!";
      result.className = mistakes.length ? 'result bad' : 'result good';
    }});

    render();
  </script>
</body>
</html>
"""


def _build_match_pages(questions: list[dict], *, page_size: int) -> list[dict]:
    pages: list[dict] = []
    for start in range(0, len(questions), page_size):
        chunk = questions[start : start + page_size]
        pairs = [
            {
                "uid": item["uid"],
                "word_id": int(item.get("word_id") or 0),
                "word": item["word"],
                "answer": item["answer"],
                "definition_text": item["definition_text"],
            }
            for item in chunk
        ]
        defs = [{"id": item["answer"], "text": item["definition_text"]} for item in chunk]
        random.Random(f"match-page-{start}-{len(chunk)}").shuffle(defs)
        pages.append(
            {
                "page": start // page_size + 1,
                "pairs": pairs,
                "definitions": defs,
            }
        )
    return pages


def _compose_definition(word: dict, *, lemma: str, default: str) -> str:
    zh_list = [str(item).strip() for item in (word.get("meaning_zh") or []) if str(item).strip()]
    en_list = [str(item).strip() for item in (word.get("meaning_en") or []) if str(item).strip()]
    zh = zh_list[0] if zh_list else ""
    en = en_list[0] if en_list else ""
    parts = [part for part in (en, zh) if part]
    combined = " / ".join(parts).strip()
    if not combined:
        return default
    return _redact_word(combined, lemma=lemma)


def _redact_word(text: str, *, lemma: str) -> str:
    token = lemma.strip().lower()
    if not token:
        return text
    escaped = re.escape(token)
    return re.sub(rf"\\b{escaped}\\b", "____", text, flags=re.IGNORECASE)
