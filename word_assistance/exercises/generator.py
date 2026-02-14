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
DAILY_COMBO_SCHEMA_VERSION = "v4"


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
            definition_text = _compose_definition(word, lemma=answer, default="该词的常用释义（词典待补全）")
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
            clue = _compose_definition(word, lemma=answer, default="点击🔊播放读音后，在输入框拼写。")
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
<html lang=\"zh-CN\">
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
    <h1>{session_type} 练习</h1>
    <p>完成后点击提交，系统会统计得分和错题。</p>
    <div id=\"list\"></div>
    <button id=\"submit\">提交练习</button>
    <div id=\"result\" class=\"result\"></div>
  </div>
  <script>
    const questions = {dataset};
    const list = document.getElementById('list');

    questions.forEach((q, idx) => {{
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `<div><b>#${{idx + 1}}</b> ${{q.prompt}}</div><input data-idx="${{idx}}" placeholder="请输入答案" />`;
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
      const summary = `得分: ${{score}} 分 (${{correct}}/${{questions.length}})`;
      const resultEl = document.getElementById('result');
      resultEl.textContent = mistakes.length ? summary + `，错题: ${{mistakes.length}}` : summary + '，全对!';
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
<html lang=\"zh-CN\">
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
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px; margin-bottom:10px; }}
    input {{ width:100%; padding:10px; font-size:16px; border:1px solid #bcd7ca; border-radius:8px; margin-top:8px; }}
    button.primary {{ background:var(--accent); color:#fff; border:0; border-radius:8px; padding:10px 16px; font-size:16px; cursor:pointer; }}
    button.secondary {{ background:#fff; color:var(--ink); border:1px solid var(--line); border-radius:8px; padding:8px 12px; font-size:14px; cursor:pointer; }}
    .actions {{ display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-top:10px; }}
    .result {{ margin-top:14px; font-weight:700; white-space:pre-line; }}
    .spell-head {{ display:flex; justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap; }}
    .audio-btn {{ border:1px solid #9bc8b8; background:#ecfff8; color:#0d5c46; border-radius:999px; padding:7px 11px; cursor:pointer; font-weight:700; }}
    .audio-btn:disabled {{ opacity:.6; cursor:not-allowed; }}
    .clue {{ color:#4b606b; font-size:14px; margin-top:8px; }}
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
    .hidden {{ display:none; }}
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
        <h1 style=\"margin:0;\">今日练习（拼写 + 释义匹配）</h1>
        <div class=\"hint\">系统按今日任务生成并缓存，默认优先使用缓存结果。</div>
      </div>
      <div class=\"hint\">单词数：{len(words)}</div>
    </div>
    <div class=\"tabs\">
      <button class=\"tab-btn\" data-mode=\"spell\">拼写练习</button>
      <button class=\"tab-btn\" data-mode=\"match\">释义匹配</button>
    </div>
    <div class=\"top-controls\">
      <label class=\"hint\">发音口音：</label>
      <select id=\"accent\">
        <option value=\"en-GB\">英式 (en-GB)</option>
        <option value=\"en-AU\">澳式 (en-AU)</option>
        <option value=\"en-US\">美式 (en-US)</option>
      </select>
      <span class=\"hint\">拼写题请先点 🔊 播放读音，再输入拼写。</span>
    </div>
    <div id=\"list\"></div>
    <div id=\"pager\" class=\"pager hidden\">
      <button id=\"prev-page\" class=\"secondary\">上一页</button>
      <span id=\"page-info\" class=\"hint\"></span>
      <button id=\"next-page\" class=\"secondary\">下一页</button>
    </div>
    <div class=\"actions\">
      <button id=\"submit\" class=\"primary\">提交当前练习</button>
      <span class=\"hint\">可通过 URL hash 切换：#spell / #match</span>
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

    const state = {{
      matchPage: 0,
      activeLeft: null,
      matchSelections: {{}},
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
          alert('读音播放失败: ' + err.message);
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
            <div class="col-title">左侧单词（先点这里）</div>
            <div class="match-list" id="left-list"></div>
          </section>
          <section class="match-col">
            <div class="col-title">右侧释义（再点这里）</div>
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

    function renderSpellCards() {{
      list.innerHTML = '';
      const questions = data.spell || [];
      questions.forEach((q, idx) => {{
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
          <div class="spell-head">
            <div><b>#${{idx + 1}}</b> 点击发音并拼写</div>
            <button type="button" class="audio-btn" data-word="${{q.answer}}">🔊 播放读音</button>
          </div>
          <div class="clue">${{q.clue || '点击🔊播放读音后拼写。'}}</div>
          <input data-idx="${{idx}}" data-kind="spell" placeholder="请输入拼写" />
        `;
        list.appendChild(card);
      }});
      list.querySelectorAll('.audio-btn').forEach((btn) => {{
        btn.addEventListener('click', () => playAudio(btn.dataset.word || '', btn));
      }});
    }}

    function updatePager() {{
      if (mode !== 'match' || !Array.isArray(data.match_pages) || data.match_pages.length <= 1) {{
        pager.classList.add('hidden');
        return;
      }}
      pager.classList.remove('hidden');
      pageInfo.textContent = `第 ${{state.matchPage + 1}} / ${{data.match_pages.length}} 页（每页最多 ${{data.match_page_size}} 词）`;
      document.getElementById('prev-page').disabled = state.matchPage <= 0;
      document.getElementById('next-page').disabled = state.matchPage >= data.match_pages.length - 1;
    }}

    function render() {{
      buttons.forEach(btn => btn.classList.toggle('active', btn.dataset.mode === mode));
      if (mode === 'match') {{
        renderMatchBoard();
      }} else {{
        renderSpellCards();
      }}
      updatePager();
      result.textContent = '';
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
              mistakes.push(`- ${{pair.word}} => 你的匹配: ${{chosen || '(空)'}}，正确词: ${{expected}}`);
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
            mistakes.push(`- #${{idx + 1}} 你的拼写: ${{user || '(空)'}}，正确: ${{expected}}`);
          }}
        }});
      }}

      total = total || 1;
      const score = Math.round((correct / total) * 100);
      const recordSummary = await persistAttempts(attempts);
      const head = `模式: ${{mode === 'match' ? '释义匹配' : '拼写练习'}}\\n得分: ${{score}} 分 (${{correct}}/${{total}})`;
      const records = `\\n记录: 已写入 ${{recordSummary.saved}} 条${{recordSummary.failed ? `，失败 ${{recordSummary.failed}} 条` : ''}}`;
      result.textContent = mistakes.length
        ? head + records + "\\n错题:\\n" + mistakes.join("\\n")
        : head + records + "\\n全对！";
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
    combined = f"{zh} / {en}".strip(" /")
    if not combined:
        return default
    return _redact_word(combined, lemma=lemma)


def _redact_word(text: str, *, lemma: str) -> str:
    token = lemma.strip().lower()
    if not token:
        return text
    escaped = re.escape(token)
    return re.sub(rf"\\b{escaped}\\b", "____", text, flags=re.IGNORECASE)
