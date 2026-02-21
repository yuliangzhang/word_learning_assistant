from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from word_assistance.config import LEARNING_DIR

UTC = timezone.utc
LEARNING_HUB_SCHEMA_VERSION = "v6"


def build_learning_hub(
    *,
    user_id: int,
    words: list[dict],
    practice_url: str,
    regenerate: bool = False,
) -> tuple[Path, dict]:
    if not words:
        raise ValueError("no words for learning hub")

    date_key = datetime.now(UTC).strftime("%Y%m%d")
    summary = [
        {"id": int(item.get("id", 0)), "lemma": str(item.get("lemma", "")).lower(), "status": str(item.get("status", ""))}
        for item in words
    ]
    fingerprint_payload = {
        "schema": LEARNING_HUB_SCHEMA_VERSION,
        "items": summary,
    }
    fingerprint = hashlib.sha1(json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:14]
    LEARNING_DIR.mkdir(parents=True, exist_ok=True)
    html_path = LEARNING_DIR / f"{date_key}_u{user_id}_{fingerprint}.html"

    cached = html_path.exists()
    if cached and not regenerate:
        return html_path, {"cached": True, "fingerprint": fingerprint, "words": len(words)}

    html_path.write_text(
        _render_learning_hub(
            user_id=user_id,
            words=summary,
            practice_url=practice_url,
        ),
        encoding="utf-8",
    )
    return html_path, {"cached": False, "fingerprint": fingerprint, "words": len(words)}


def _render_learning_hub(*, user_id: int, words: list[dict], practice_url: str) -> str:
    dataset = json.dumps(words, ensure_ascii=False)
    practice = practice_url
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Today's Learning Workspace</title>
  <style>
    :root {{
      --bg: #f4f6f8;
      --panel: #ffffff;
      --line: #d9e2ec;
      --ink: #1f2937;
      --muted: #5d6b77;
      --accent: #0f766e;
      --accent-soft: #d7efec;
      --warn: #92400e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: 'Avenir Next', 'Helvetica Neue', Helvetica, Arial, sans-serif;
      height: 100vh;
      overflow: hidden;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 300px 1fr;
      gap: 12px;
      padding: 10px;
      height: 100vh;
    }}
    .sidebar {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }}
    .word-list {{
      flex: 1;
      min-height: 0;
      overflow-y: auto;
      overflow-x: hidden;
      scrollbar-gutter: stable;
      padding-right: 4px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .word-row {{
      border: 1px solid var(--line);
      border-radius: 10px;
      background: #fff;
      padding: 8px;
      display: grid;
      grid-template-columns: 1fr;
      gap: 6px;
    }}
    .word-btn {{
      border: 0;
      background: transparent;
      border-radius: 8px;
      padding: 2px 2px 0;
      text-align: left;
      cursor: pointer;
      color: var(--ink);
      transition: all 0.15s ease;
    }}
    .word-row.active {{
      border-color: var(--accent);
      background: var(--accent-soft);
    }}
    .status {{
      font-size: 12px;
      color: var(--muted);
      margin-top: 2px;
    }}
    .word-actions {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}
    .word-actions select {{
      flex: 1;
      border: 1px solid #c5d4cc;
      border-radius: 8px;
      padding: 6px 8px;
      font-size: 13px;
      background: #fff;
    }}
    .status-tip {{
      font-size: 12px;
      color: var(--warn);
    }}
    .main {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 12px;
      display: grid;
      grid-template-rows: auto 1fr;
      min-height: 0;
    }}
    .toolbar {{
      padding: 10px;
      border-bottom: 1px solid var(--line);
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      align-items: center;
    }}
    .toolbar a, .toolbar button {{
      text-decoration: none;
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 999px;
      padding: 8px 12px;
      font-size: 14px;
      cursor: pointer;
    }}
    .toolbar select {{
      border: 1px solid var(--line);
      border-radius: 999px;
      background: #fff;
      color: var(--ink);
      padding: 8px 12px;
      font-size: 14px;
    }}
    .toolbar .primary {{
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
    }}
    .hint {{ font-size: 13px; color: var(--muted); }}
    .frame-wrap {{
      min-height: 0;
      height: 100%;
      overflow: hidden;
      position: relative;
      background: #f7faf8;
    }}
    iframe {{
      width: 100%;
      height: 100%;
      border: 0;
      border-bottom-left-radius: 12px;
      border-bottom-right-radius: 12px;
      background: #fff;
    }}
    @media (max-width: 760px) {{
      .layout {{
        grid-template-columns: 1fr;
        grid-template-rows: auto 1fr;
        height: auto;
        min-height: 100vh;
      }}
      body {{
        overflow: auto;
        height: auto;
      }}
      .sidebar {{ min-height: auto; }}
      .word-list {{
        flex-direction: row;
        overflow-x: auto;
        overflow-y: hidden;
        padding-bottom: 6px;
      }}
      .word-row {{ min-width: 210px; }}
      iframe {{ min-height: 500px; }}
    }}
  </style>
</head>
<body>
  <main class=\"layout\">
    <aside class=\"sidebar\">
      <h3 style=\"margin:4px 4px 10px;\">Today's Focus Words</h3>
      <div class=\"status-tip\">You can update each word status directly from the left panel.</div>
      <div id=\"word-list\" class=\"word-list\"></div>
    </aside>
    <section class=\"main\">
      <div class=\"toolbar\">
        <a class=\"primary\" id=\"btn-spell\" href=\"{practice}#spell\" target=\"_blank\">Spelling Practice</a>
        <a id=\"btn-match\" href=\"{practice}#match\" target=\"_blank\">Definition Match</a>
        <button id=\"play-pron\">🔊 Pronounce Word</button>
        <select id=\"pron-accent\">
          <option value=\"en-GB\">UK (en-GB)</option>
          <option value=\"en-AU\">AU (en-AU)</option>
          <option value=\"en-US\">US (en-US)</option>
        </select>
        <button id=\"regen-card\">Regenerate Current Card</button>
        <span class=\"hint\">Cards are generated on demand and cached; practice pages are cached by today's task.</span>
      </div>
      <div class=\"frame-wrap\">
        <iframe id=\"card-frame\" title=\"word-card\"></iframe>
      </div>
    </section>
  </main>
  <script>
    const USER_ID = {user_id};
    const WORDS = {dataset};
    const audioCache = new Map();
    let activeWord = WORDS[0] ? WORDS[0].lemma : '';
    let activeWordId = WORDS[0] ? Number(WORDS[0].id) : 0;

    async function fetchCardUrl(word, regenerate = false) {{
      const qs = new URLSearchParams({{
        user_id: String(USER_ID),
        word,
        regenerate: regenerate ? '1' : '0',
      }});
      const res = await fetch(`/api/learn/card-url?${{qs.toString()}}`);
      if (!res.ok) {{
        throw new Error(await res.text());
      }}
      return res.json();
    }}

    function statusLabel(status) {{
      const key = String(status || '').toUpperCase();
      if (key === 'MASTERED') return 'Mastered';
      if (key === 'LEARNING' || key === 'REVIEWING') return 'In Progress';
      if (key === 'SUSPENDED') return 'Paused';
      return 'Not Started';
    }}

    function statusSelectValue(status) {{
      const key = String(status || '').toUpperCase();
      if (key === 'MASTERED') return 'MASTERED';
      if (key === 'LEARNING' || key === 'REVIEWING') return 'LEARNING';
      return 'NEW';
    }}

    async function updateWordStatus(wordId, status) {{
      const res = await fetch(`/api/words/${{wordId}}/status`, {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ user_id: USER_ID, status }}),
      }});
      if (!res.ok) {{
        throw new Error(await res.text());
      }}
      const data = await res.json();
      return data.word;
    }}

    async function openWord(word, regenerate = false) {{
      if (!word) return;
      activeWord = word;
      document.querySelectorAll('.word-row').forEach((row) => {{
        row.classList.toggle('active', row.dataset.word === word);
      }});
      const picked = WORDS.find((item) => item.lemma === word);
      activeWordId = picked ? Number(picked.id || 0) : 0;
      try {{
        const data = await fetchCardUrl(word, regenerate);
        const frame = document.getElementById('card-frame');
        frame.src = data.url;
      }} catch (err) {{
        alert('Failed to open card: ' + err.message);
      }}
    }}

    function renderWordList() {{
      const wrap = document.getElementById('word-list');
      wrap.innerHTML = '';
      WORDS.forEach((item, idx) => {{
        const row = document.createElement('div');
        row.className = 'word-row';
        row.dataset.word = item.lemma;

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'word-btn';
        btn.dataset.word = item.lemma;
        btn.innerHTML = `<div>${{idx + 1}}. ${{item.lemma}}</div><div class="status">${{statusLabel(item.status)}}</div>`;
        btn.addEventListener('click', () => openWord(item.lemma));
        row.appendChild(btn);

        const actions = document.createElement('div');
        actions.className = 'word-actions';
        const statusSelect = document.createElement('select');
        statusSelect.innerHTML = `
          <option value="NEW">Not Started</option>
          <option value="LEARNING">In Progress</option>
          <option value="MASTERED">Mastered</option>
        `;
        statusSelect.value = statusSelectValue(item.status);
        statusSelect.addEventListener('change', async () => {{
          try {{
            const updated = await updateWordStatus(item.id, statusSelect.value);
            item.status = updated.status;
            btn.querySelector('.status').textContent = statusLabel(updated.status);
          }} catch (err) {{
            alert('Failed to update status: ' + err.message);
            statusSelect.value = statusSelectValue(item.status);
          }}
        }});
        actions.appendChild(statusSelect);
        row.appendChild(actions);
        wrap.appendChild(row);
      }});
    }}

    async function playActiveWord() {{
      if (!activeWord) return;
      const accent = document.getElementById('pron-accent').value || 'en-GB';
      const key = `${{accent}}:${{activeWord}}`;
      try {{
        if (!audioCache.has(key)) {{
          const res = await fetch('/api/speech/tts', {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ text: activeWord, accent }}),
          }});
          if (!res.ok) {{
            throw new Error(await res.text());
          }}
          const payload = await res.json();
          audioCache.set(key, payload.audio_url);
        }}
        const audio = new Audio(audioCache.get(key));
        await audio.play();
      }} catch (err) {{
        alert('Audio playback failed: ' + err.message);
      }}
    }}

    function fitCardFrame() {{
      const frame = document.getElementById('card-frame');
      if (!frame) return;
      const frameTop = frame.getBoundingClientRect().top;
      const viewportHeight = window.innerHeight;
      const available = Math.max(420, viewportHeight - frameTop - 12);
      frame.style.height = `${{available}}px`;
      const doc = frame.contentDocument;
      if (!doc || !doc.body || !doc.documentElement) {{
        return;
      }}
      const html = doc.documentElement;
      doc.body.style.transform = 'none';
      doc.body.style.transformOrigin = 'top left';
      doc.body.style.width = '100%';
      doc.body.style.margin = '0';
      doc.body.style.overflowY = 'auto';
      doc.body.style.overflowX = 'hidden';
      html.style.overflowY = 'auto';
      html.style.overflowX = 'hidden';
      html.style.width = '100%';
    }}

    document.getElementById('regen-card').addEventListener('click', () => {{
      if (!activeWord) return;
      openWord(activeWord, true);
    }});
    document.getElementById('play-pron').addEventListener('click', playActiveWord);
    document.getElementById('card-frame').addEventListener('load', () => {{
      fitCardFrame();
      setTimeout(fitCardFrame, 120);
      setTimeout(fitCardFrame, 520);
    }});
    window.addEventListener('resize', fitCardFrame);

    renderWordList();
    if (activeWord) openWord(activeWord);
  </script>
</body>
</html>
"""
