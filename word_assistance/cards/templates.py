from __future__ import annotations

from html import escape

REQUIRED_MUSEUM_FIELDS = {
    "word",
    "phonetic",
    "definition_deep",
    "etymology",
    "nuance_text",
    "example_sentence",
    "mermaid_code",
    "epiphany",
    "confidence_note",
}

MUSEUM_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang=\"zh-CN\">
<head>
<meta charset=\"UTF-8\" />
<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
<title>Word Mastery: {{WORD}}</title>
<style>
  :root {
    --bg-color: #f3f4f6;
    --card-bg: #ffffff;
    --text-main: #1f2937;
    --text-muted: #6b7280;
    --border-color: #e5e7eb;
    --font-serif: 'Georgia', 'Times New Roman', serif;
    --font-sans: 'Avenir Next', 'Helvetica Neue', Helvetica, Arial, sans-serif;
  }

  * { box-sizing: border-box; }

  body {
    background-color: var(--bg-color);
    color: var(--text-main);
    font-family: var(--font-sans);
    display: flex;
    justify-content: center;
    padding: 12px;
    margin: 0;
    line-height: 1.45;
    min-height: 100vh;
  }

  .container {
    max-width: 1180px;
    width: 100%;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .header {
    border-bottom: 2px solid var(--text-main);
    padding-bottom: 10px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
  }

  .word-title {
    font-family: var(--font-serif);
    font-size: clamp(46px, 7vw, 92px);
    font-weight: 700;
    margin: 0;
    letter-spacing: -0.02em;
    line-height: 1;
  }

  .phonetic {
    font-family: 'Courier New', monospace;
    font-size: 1.55em;
    color: var(--text-muted);
    white-space: nowrap;
  }

  .phonetic-wrap {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .phonetic-wrap select {
    border: 1px solid var(--border-color);
    border-radius: 999px;
    padding: 6px 10px;
    background: #fff;
    color: var(--text-main);
  }

  .pron-btn {
    border: 1px solid #b8d8c7;
    border-radius: 999px;
    background: #ecfff6;
    color: #115142;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: 700;
    cursor: pointer;
  }

  .bento-grid {
    display: grid;
    grid-template-columns: 1.8fr 1.2fr;
    gap: 12px;
    align-items: start;
  }

  .column {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .card {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    padding: 14px;
    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.04);
    border-radius: 8px;
    min-height: 0;
  }

  .card-label {
    font-size: 0.75em;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--text-muted);
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 8px;
    margin-bottom: 10px;
    font-weight: 700;
  }

  .definition-text {
    font-family: var(--font-serif);
    font-size: 1.1em;
  }

  .etymology-content {
    font-size: 0.95em;
  }

  .bi-zh {
    color: var(--text-main);
    margin-bottom: 6px;
  }

  .bi-en {
    color: #334155;
    font-size: 0.95em;
    margin-bottom: 8px;
  }

  .nuance-list {
    margin: 0;
    padding-left: 20px;
  }

  .nuance-item { margin-bottom: 8px; }

  .quote-box {
    margin-top: 10px;
    padding-left: 10px;
    border-left: 3px solid #be123c;
    font-style: italic;
    color: var(--text-muted);
    font-family: var(--font-serif);
  }

  .mermaid {
    display: flex;
    justify-content: center;
    background: #fafafa;
    padding: 10px;
    border-radius: 6px;
  }

  .epiphany-box {
    background-color: #111111;
    color: #ffffff;
    padding: 16px;
    text-align: center;
    border-radius: 8px;
    position: relative;
    overflow: hidden;
  }

  .epiphany-label {
    font-size: 0.72em;
    opacity: 0.55;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin-bottom: 8px;
    display: block;
  }

  .epiphany-text {
    font-family: 'Courier New', monospace;
    font-size: 1.25em;
    font-weight: 700;
    line-height: 1.4;
  }

  .epiphany-box::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 4px;
    background: linear-gradient(90deg, #be123c, #1d4ed8);
  }

  .confidence {
    font-size: 13px;
    color: #6f5a3f;
    background: #fff7e5;
    border: 1px dashed #d7b77d;
    border-radius: 8px;
    padding: 8px 10px;
  }

  @media (max-width: 960px) {
    .bento-grid { grid-template-columns: 1fr; }
    .word-title { font-size: clamp(38px, 12vw, 64px); }
    .phonetic { font-size: 1.1em; }
  }

  @media (max-width: 640px) {
    body { padding: 8px; }
    .container { gap: 8px; }
    .header { padding-bottom: 8px; }
    .card { padding: 10px; }
    .definition-text { font-size: 1em; }
  }
</style>
</head>
<body>
<div class=\"container\" data-word=\"{{WORD_RAW}}\">
  <div class=\"header\">
    <h1 class=\"word-title\">{{WORD}}</h1>
    <div class=\"phonetic-wrap\">
      <span class=\"phonetic\">/{{PHONETIC}}/</span>
      <button id=\"card-pron-btn\" class=\"pron-btn\" type=\"button\">🔊 读音</button>
      <select id=\"card-accent\">
        <option value=\"en-GB\">英式</option>
        <option value=\"en-AU\">澳式</option>
        <option value=\"en-US\">美式</option>
      </select>
    </div>
  </div>

  <div class=\"bento-grid\">
    <div class=\"column\">
      <div class=\"card\">
        <div class=\"card-label\">CORE MEANING (核心语义)</div>
        <div class=\"definition-text\">
          {{DEFINITION_DEEP}}
        </div>
      </div>

      <div class=\"card\">
        <div class=\"card-label\">NUANCE & CONTEXT (语感与语境)</div>
        <div class=\"etymology-content\">
          {{NUANCE_TEXT}}
          <div class=\"quote-box\">
            \"{{EXAMPLE_SENTENCE}}\"
          </div>
        </div>
      </div>
    </div>

    <div class=\"column\">
      <div class=\"card\">
        <div class=\"card-label\">SEMANTIC TOPOLOGY (语义拓扑)</div>
        <div class=\"mermaid\">
{{MERMAID_CODE}}
        </div>
      </div>

      <div class=\"card\">
        <div class=\"card-label\">ETYMOLOGY (词源)</div>
        <div class=\"etymology-content\">
          {{ETYMOLOGY}}
        </div>
      </div>
    </div>
  </div>

  <div class=\"epiphany-box\">
    <span class=\"epiphany-label\">EPIPHANY (一语道破)</span>
    <div class=\"epiphany-text\">
      \"{{EPIPHANY}}\"
    </div>
  </div>
  <div class=\"confidence\">{{CONFIDENCE_NOTE}}</div>
</div>

<script src=\"/static/assets/mermaid.min.js\"></script>
<script>
  if (window.mermaid) {
    mermaid.initialize({
      startOnLoad: true,
      theme: 'base',
      securityLevel: 'loose',
      themeVariables: {
        primaryColor: '#ffffff',
        primaryTextColor: '#1a1a1a',
        primaryBorderColor: '#333',
        lineColor: '#333',
        fontFamily: 'Avenir Next, Helvetica, Arial, sans-serif',
        fontSize: '13px'
      }
    });
    mermaid.run();
  }

  (function setupCardPronunciation() {
    const btn = document.getElementById('card-pron-btn');
    const accent = document.getElementById('card-accent');
    const container = document.querySelector('.container');
    if (!btn || !accent || !container) return;
    const word = (container.getAttribute('data-word') || '').trim();
    if (!word) return;

    btn.addEventListener('click', async () => {
      btn.disabled = true;
      try {
        const selectedAccent = accent.value || 'en-GB';
        const res = await fetch('/api/speech/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text: word, accent: selectedAccent }),
        });
        if (!res.ok) {
          throw new Error(await res.text());
        }
        const payload = await res.json();
        const audio = new Audio(payload.audio_url);
        await audio.play();
      } catch (err) {
        alert('播放读音失败: ' + err.message);
      } finally {
        btn.disabled = false;
      }
    });
  })();
</script>
</body>
</html>
"""

KIDS_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Kids Card - {{WORD}}</title>
  <style>
    body { font-family: 'Avenir Next', Arial, sans-serif; margin: 0; background: linear-gradient(120deg,#e2f8ff,#fff6dd); }
    .wrap { max-width: 900px; margin: 22px auto; padding: 18px; background: #fff; border-radius: 14px; box-shadow: 0 10px 28px rgba(0,0,0,.08); }
    h1 { margin: 0; font-size: clamp(34px, 7vw, 56px); }
    .phonetic { color: #466176; margin-bottom: 14px; }
    .part { border-top: 1px dashed #c8deef; padding-top: 12px; margin-top: 12px; }
    ul { margin-top: 6px; }
    .next { margin-top: 16px; display: flex; gap: 8px; flex-wrap: wrap; }
    .next span { background: #0f6a73; color: #fff; padding: 8px 12px; border-radius: 999px; }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>{{WORD}}</h1>
    <div class=\"phonetic\">/{{PHONETIC}}/</div>
    <div class=\"part\"><b>适龄解释</b><br/>{{CORE_SEMANTICS}}</div>
    <div class=\"part\"><b>例句</b><ul>{{EXAMPLE_LIST}}</ul></div>
    <div class=\"part\"><b>记忆法</b><br/>{{ACTION_TODAY}}</div>
    <div class=\"next\">
      <span>加入词库</span><span>开始练习</span><span>听写</span>
    </div>
  </div>
</body>
</html>
"""


def ensure_museum_payload(payload: dict) -> None:
    missing = sorted(REQUIRED_MUSEUM_FIELDS - payload.keys())
    if missing:
        raise ValueError(f"museum payload missing fields: {', '.join(missing)}")


def render_card(template: str, mapping: dict[str, str]) -> str:
    rendered = template
    for key, value in mapping.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def html_list(items: list[str]) -> str:
    return "".join(f"<li>{escape(item)}</li>" for item in items)
