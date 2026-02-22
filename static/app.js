const USER_ID = 2;
let currentImportId = null;
let currentPreviewItems = [];
let mediaRecorder = null;
let mediaChunks = [];
const wordListState = {
  page: 1,
  pageSize: 15,
  status: "ALL",
  total: 0,
  totalPages: 1,
};

function addMessage(text, type = "bot") {
  const log = document.getElementById("chat-log");
  const node = document.createElement("div");
  node.className = `msg ${type}`;
  node.textContent = text;
  log.appendChild(node);
  log.scrollTop = log.scrollHeight;
}

function _messageTypeFromRole(role) {
  return String(role || "").toLowerCase() === "user" ? "user" : "bot";
}

async function requestJSON(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(url, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

function renderLinks(links = []) {
  if (!Array.isArray(links) || !links.length) return;
  const log = document.getElementById("chat-log");
  links.forEach((link) => {
    const a = document.createElement("a");
    a.href = link;
    a.target = "_blank";
    a.className = "link";
    a.textContent = `Open: ${link}`;
    log.appendChild(a);
  });
  log.scrollTop = log.scrollHeight;
}

async function speakText(text) {
  if (!document.getElementById("auto-tts").checked) return;

  const accent = document.getElementById("voice-accent").value;
  const voice = document.getElementById("voice-preset").value || null;

  try {
    const data = await requestJSON("/api/speech/tts", {
      method: "POST",
      body: JSON.stringify({ text, accent, voice }),
    });
    const audio = new Audio(data.audio_url);
    await audio.play();
  } catch (err) {
    addMessage(`TTS failed: ${err.message}`, "bot");
  }
}

async function sendChat(message) {
  addMessage(message, "user");
  try {
    const data = await requestJSON("/api/chat", {
      method: "POST",
      body: JSON.stringify({ user_id: USER_ID, message }),
    });
    addMessage(data.reply || "Done.");
    renderLinks(data.links || []);
    if (data.route_source === "openclaw") {
      const status = document.getElementById("openclaw-status");
      if (status) {
        status.textContent = `Chat routing: OpenClaw (command: ${data.route_command || "natural language"})`;
      }
    } else if (data.route_source === "openclaw_unavailable") {
      const status = document.getElementById("openclaw-status");
      if (status) {
        status.textContent = "Chat routing: OpenClaw unavailable, handled by configured fallback.";
      }
    }
    if (data.reply) {
      speakText(data.reply);
    }
  } catch (err) {
    addMessage(`Request failed: ${err.message}`);
  }
}

async function loadChatHistory() {
  const log = document.getElementById("chat-log");
  if (!log) return;
  log.innerHTML = "";

  try {
    const data = await requestJSON(`/api/chat/history?user_id=${USER_ID}&limit=150`);
    const items = Array.isArray(data.items) ? data.items : [];
    if (!items.length) {
      addMessage("Welcome to Word Learning Assistant. Tell me what to do and I will execute it.", "bot");
      return;
    }
    items.forEach((item) => {
      addMessage(item.message || "", _messageTypeFromRole(item.role));
    });
  } catch (err) {
    addMessage(`Failed to load chat memory: ${err.message}`);
  }
}

async function clearChatHistory() {
  const ok = confirm("Clear all saved chat history?");
  if (!ok) return;
  try {
    await requestJSON(`/api/chat/history?user_id=${USER_ID}`, { method: "DELETE" });
    const log = document.getElementById("chat-log");
    if (log) log.innerHTML = "";
    addMessage("Chat memory cleared.", "bot");
  } catch (err) {
    addMessage(`Failed to clear chat memory: ${err.message}`, "bot");
  }
}

function renderPreview(items) {
  currentPreviewItems = items || [];
  const wrap = document.getElementById("preview-wrap");
  const list = document.getElementById("preview-list");
  list.innerHTML = "";

  currentPreviewItems.forEach((item) => {
    const row = document.createElement("label");
    row.className = `preview-item ${item.needs_confirmation ? "low" : ""}`;
    row.innerHTML = `
      <input type="checkbox" data-id="${item.id}" ${item.accepted === 0 ? "" : "checked"} />
      <span>${item.word_candidate}</span>
      <span>${item.suggested_correction}</span>
      <span>${item.confidence}</span>
      <span>${item.needs_confirmation ? "Needs review" : "Auto"}</span>
    `;
    list.appendChild(row);
  });
  wrap.classList.remove("hidden");
}

async function importTextPreview() {
  const text = document.getElementById("import-text").value.trim();
  if (!text) {
    addMessage("Paste text first, then preview.");
    return;
  }

  const tags = document.getElementById("import-tags").value
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);

  try {
    const data = await requestJSON("/api/import/text", {
      method: "POST",
      body: JSON.stringify({ user_id: USER_ID, text, source_name: "chat_text", tags }),
    });
    currentImportId = data.import_id;
    renderPreview(data.preview_items);
    const threshold = data.import_profile ? data.import_profile.auto_accept_threshold : 0.85;
    addMessage(`Text preview ready: ${data.preview_items.length} items (auto threshold ${threshold}).`);
  } catch (err) {
    addMessage(`Text preview failed: ${err.message}`);
  }
}

async function importFilePreview() {
  const input = document.getElementById("file-input");
  if (!input.files || !input.files.length) {
    addMessage("Please choose a file first.", "bot");
    return;
  }

  const form = new FormData();
  form.append("user_id", USER_ID);
  form.append("importer_role", "CHILD");
  form.append("tags", document.getElementById("import-tags").value || "");
  form.append("file", input.files[0]);

  try {
    const data = await requestJSON("/api/import/file", { method: "POST", body: form });
    currentImportId = data.import_id;
    renderPreview(data.preview_items);
    const mode = (data.import_profile && data.import_profile.ocr_strength) || "BALANCED";
    const selectionMode = data.selection_mode === "smart" ? "Smart selection" : "Standard selection";
    addMessage(`File preview ready (${data.source_type}, OCR=${mode}, ${selectionMode}), ${data.preview_items.length} items.`);
  } catch (err) {
    addMessage(`File preview failed: ${err.message}`);
  }
}

async function commitImport() {
  if (!currentImportId) {
    addMessage("No import batch to commit yet.", "bot");
    return;
  }

  const checked = [...document.querySelectorAll("#preview-list input[type='checkbox']:checked")]
    .map((node) => Number(node.dataset.id));

  try {
    const data = await requestJSON("/api/import/commit", {
      method: "POST",
      body: JSON.stringify({ import_id: currentImportId, accepted_item_ids: checked }),
    });
    addMessage(`Import done. Added ${data.imported_words} words.`);
    currentImportId = null;
    document.getElementById("preview-wrap").classList.add("hidden");
    refreshWords();
    refreshCorrections();
  } catch (err) {
    addMessage(`Commit failed: ${err.message}`);
  }
}

async function correctWord(wordId, lemma) {
  const input = prompt(`Fix "${lemma}" to:`, lemma);
  if (!input || input.trim().toLowerCase() === lemma.toLowerCase()) {
    return;
  }

  try {
    const data = await requestJSON(`/api/words/${wordId}/correct`, {
      method: "POST",
      body: JSON.stringify({
        user_id: USER_ID,
        new_lemma: input.trim(),
        new_surface: input.trim(),
        reason: "ui_manual_correction",
        corrected_by_role: "CHILD",
      }),
    });
    addMessage(`Updated: ${lemma} -> ${data.word.lemma}`);
    refreshWords();
    refreshCorrections();
  } catch (err) {
    addMessage(`Correction failed: ${err.message}`);
  }
}

async function deleteWord(wordId, lemma) {
  const ok = confirm(`Delete "${lemma}"? This also removes related practice records.`);
  if (!ok) return;

  try {
    await requestJSON(`/api/words/${wordId}?user_id=${USER_ID}&deleted_by_role=CHILD`, {
      method: "DELETE",
    });
    addMessage(`Deleted: ${lemma}`);
    refreshWords();
    refreshCorrections();
  } catch (err) {
    addMessage(`Delete failed: ${err.message}`);
  }
}

function statusText(status) {
  const key = String(status || "").toUpperCase();
  if (key === "MASTERED") return "Mastered";
  if (key === "LEARNING" || key === "REVIEWING") return "In Progress";
  if (key === "SUSPENDED") return "Paused";
  return "Not Started";
}

function statusFilterText(filter) {
  const key = String(filter || "ALL").toUpperCase();
  if (key === "MASTERED") return "Mastered";
  if (key === "IN_PROGRESS" || key === "LEARNING") return "In Progress";
  if (key === "NEW") return "Not Started";
  return "All";
}

async function updateWordStatus(wordId, status) {
  const data = await requestJSON(`/api/words/${wordId}/status`, {
    method: "POST",
    body: JSON.stringify({
      user_id: USER_ID,
      status,
    }),
  });
  return data.word;
}

function renderWordPager() {
  const info = document.getElementById("word-page-info");
  const prev = document.getElementById("word-prev");
  const next = document.getElementById("word-next");
  if (info) {
    info.textContent = `Page ${wordListState.page} / ${wordListState.totalPages}`;
  }
  if (prev) prev.disabled = wordListState.page <= 1;
  if (next) next.disabled = wordListState.page >= wordListState.totalPages;
}

async function refreshWords() {
  const list = document.getElementById("word-list");
  const summary = document.getElementById("word-summary");
  list.innerHTML = "";
  if (summary) summary.textContent = "";
  try {
    const params = new URLSearchParams({
      user_id: String(USER_ID),
      page: String(wordListState.page),
      page_size: String(wordListState.pageSize),
      status: wordListState.status,
    });
    const data = await requestJSON(`/api/words?${params.toString()}`);
    wordListState.total = Number(data.total || 0);
    wordListState.totalPages = Number(data.total_pages || 1);
    wordListState.page = Number(data.page || 1);
    if (summary) {
      summary.textContent = `Vocabulary: ${wordListState.total} words (filter: ${statusFilterText(wordListState.status)})`;
    }
    data.items.forEach((word) => {
      const li = document.createElement("li");
      li.className = "word-row";
      const next = word.next_review_at ? new Date(word.next_review_at).toLocaleString() : "-";
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = `${word.lemma} | Status: ${statusText(word.status)} | Next review: ${next}`;

      const actionWrap = document.createElement("div");
      actionWrap.className = "word-actions";
      const select = document.createElement("select");
      select.className = "action-select";
      select.innerHTML = `
        <option value="">Action</option>
        <option value="correct">Correct</option>
        <option value="delete">Delete</option>
        <option value="status:NEW">Set Not Started</option>
        <option value="status:LEARNING">Set In Progress</option>
        <option value="status:MASTERED">Set Mastered</option>
      `;
      select.addEventListener("change", async () => {
        const action = select.value;
        select.value = "";
        if (!action) return;
        try {
          if (action === "correct") {
            await correctWord(word.id, word.lemma);
            return;
          }
          if (action === "delete") {
            await deleteWord(word.id, word.lemma);
            return;
          }
          if (action.startsWith("status:")) {
            const nextStatus = action.split(":")[1] || "NEW";
            const updated = await updateWordStatus(word.id, nextStatus);
            addMessage(`Status updated: ${word.lemma} -> ${statusText(updated.status)}`);
            refreshWords();
            return;
          }
        } catch (err) {
          addMessage(`Action failed: ${err.message}`);
        }
      });
      actionWrap.appendChild(select);

      li.appendChild(meta);
      li.appendChild(actionWrap);
      list.appendChild(li);
    });
    renderWordPager();
  } catch (err) {
    addMessage(`Failed to refresh vocabulary: ${err.message}`);
  }
}

async function refreshCorrections() {
  const list = document.getElementById("correction-list");
  list.innerHTML = "";
  try {
    const data = await requestJSON(`/api/words/corrections?user_id=${USER_ID}&limit=20`);
    data.items.forEach((item) => {
      const li = document.createElement("li");
      li.textContent = `${item.old_lemma} -> ${item.new_lemma} (${item.corrected_by_role})`;
      list.appendChild(li);
    });
  } catch (err) {
    addMessage(`Failed to load correction history: ${err.message}`);
  }
}

async function generateWeekReport() {
  const box = document.getElementById("report-links");
  box.innerHTML = "";
  try {
    const data = await requestJSON(`/api/report/week?user_id=${USER_ID}`);
    const htmlLink = document.createElement("a");
    htmlLink.className = "link";
    htmlLink.href = data.html_url;
    htmlLink.target = "_blank";
    htmlLink.textContent = "Open Weekly Report (HTML)";
    box.appendChild(htmlLink);

    const csvLink = document.createElement("a");
    csvLink.className = "link";
    csvLink.href = data.csv_url;
    csvLink.target = "_blank";
    csvLink.textContent = "Download Weekly Report (CSV)";
    box.appendChild(csvLink);

    addMessage(`Weekly report generated. Accuracy ${(data.report.accuracy * 100).toFixed(0)}%.`);
  } catch (err) {
    addMessage(`Weekly report failed: ${err.message}`);
  }
}

async function loadVoices() {
  try {
    const data = await requestJSON("/api/speech/voices");
    window.voiceOptions = data.voices || {};
    updateVoiceOptions();
  } catch (err) {
    addMessage(`Failed to load voice options: ${err.message}`);
  }
}

function updateVoiceOptions() {
  const accent = document.getElementById("voice-accent").value;
  const select = document.getElementById("voice-preset");
  const options = (window.voiceOptions && window.voiceOptions[accent]) || [];
  select.innerHTML = "";
  options.forEach((item) => {
    const opt = document.createElement("option");
    opt.value = item.id;
    opt.textContent = item.label;
    select.appendChild(opt);
  });
}

async function startRecording() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    addMessage("This browser does not support audio recording.", "bot");
    return;
  }

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    mediaChunks = [];
    mediaRecorder = new MediaRecorder(stream);
    mediaRecorder.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) {
        mediaChunks.push(event.data);
      }
    };
    mediaRecorder.onstop = async () => {
      const blob = new Blob(mediaChunks, { type: "audio/webm" });
      stream.getTracks().forEach((track) => track.stop());
      await submitStt(blob);
    };
    mediaRecorder.start();
    document.getElementById("voice-btn").textContent = "Stop Recording";
    addMessage("Recording... tap again to stop.", "bot");
  } catch (err) {
    addMessage(`Failed to start recording: ${err.message}`, "bot");
  }
}

function stopRecording() {
  if (!mediaRecorder) return;
  mediaRecorder.stop();
  mediaRecorder = null;
  document.getElementById("voice-btn").textContent = "Start Recording";
}

async function submitStt(blob) {
  const form = new FormData();
  form.append("file", blob, "record.webm");
  try {
    const data = await requestJSON("/api/speech/stt", { method: "POST", body: form });
    addMessage(`STT: ${data.text}`, "user");
    if (document.getElementById("auto-send-stt").checked) {
      sendChat(data.text);
    } else {
      document.getElementById("chat-input").value = data.text;
    }
  } catch (err) {
    addMessage(`STT failed: ${err.message}`, "bot");
  }
}

async function loadParentSettings() {
  try {
    const data = await requestJSON(`/api/parent/settings?child_user_id=${USER_ID}`);
    const s = data.settings;
    document.getElementById("setting-new").value = s.daily_new_limit;
    document.getElementById("setting-review").value = s.daily_review_limit;
    document.getElementById("setting-strict").checked = !!s.strict_mode;
    document.getElementById("setting-llm").checked = !!s.llm_enabled;
    document.getElementById("setting-auto-tts").checked = !!s.auto_tts;
    document.getElementById("setting-orchestration").value = s.orchestration_mode || "OPENCLAW_PREFERRED";
    document.getElementById("setting-ocr-strength").value = s.ocr_strength || "BALANCED";
    document.getElementById("setting-auto-accept-threshold").value =
      Number(s.correction_auto_accept_threshold ?? 0.85).toFixed(2);
    document.getElementById("setting-card-quality-model").value = s.card_llm_quality_model || "gpt-4.1-mini";
    document.getElementById("setting-card-fast-model").value = s.card_llm_fast_model || "gpt-4o-mini";
    document.getElementById("setting-card-strategy").value = s.card_llm_strategy || "QUALITY_FIRST";
    document.getElementById("auto-tts").checked = !!s.auto_tts;

    document.getElementById("voice-accent").value = s.voice_accent || "en-GB";
    updateVoiceOptions();
    if (s.tts_voice) {
      document.getElementById("voice-preset").value = s.tts_voice;
    }
  } catch (err) {
    addMessage(`Failed to load parent settings: ${err.message}`);
  }
}

async function saveParentSettings() {
  const thresholdInput = Number(document.getElementById("setting-auto-accept-threshold").value || 0.85);
  const threshold = Math.max(0.5, Math.min(0.99, thresholdInput));
  const payload = {
    child_user_id: USER_ID,
    daily_new_limit: Number(document.getElementById("setting-new").value || 8),
    daily_review_limit: Number(document.getElementById("setting-review").value || 20),
    strict_mode: document.getElementById("setting-strict").checked,
    llm_enabled: document.getElementById("setting-llm").checked,
    auto_tts: document.getElementById("setting-auto-tts").checked,
    orchestration_mode: document.getElementById("setting-orchestration").value,
    ocr_strength: document.getElementById("setting-ocr-strength").value,
    correction_auto_accept_threshold: Number(threshold.toFixed(2)),
    card_llm_quality_model: (document.getElementById("setting-card-quality-model").value || "").trim() || "gpt-4.1-mini",
    card_llm_fast_model: (document.getElementById("setting-card-fast-model").value || "").trim() || "gpt-4o-mini",
    card_llm_strategy: (document.getElementById("setting-card-strategy").value || "QUALITY_FIRST").toUpperCase(),
    voice_accent: document.getElementById("voice-accent").value,
    tts_voice: document.getElementById("voice-preset").value,
  };

  try {
    await requestJSON("/api/parent/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    document.getElementById("setting-auto-accept-threshold").value = payload.correction_auto_accept_threshold.toFixed(2);
    document.getElementById("auto-tts").checked = payload.auto_tts;
    addMessage("Parent settings saved.", "bot");
  } catch (err) {
    addMessage(`Failed to save parent settings: ${err.message}`, "bot");
  }
}

async function exportWords(fmt) {
  const box = document.getElementById("parent-links");
  try {
    const data = await requestJSON(`/api/parent/export/words?user_id=${USER_ID}&fmt=${fmt}`);
    const link = document.createElement("a");
    link.href = data.url;
    link.target = "_blank";
    link.className = "link";
    link.textContent = `Download ${fmt.toUpperCase()} (${data.count} words)`;
    box.prepend(link);
  } catch (err) {
    addMessage(`Export failed: ${err.message}`, "bot");
  }
}

async function createBackup() {
  const box = document.getElementById("parent-links");
  try {
    const data = await requestJSON("/api/parent/backup", { method: "POST" });
    const link = document.createElement("a");
    link.href = data.backup_url;
    link.target = "_blank";
    link.className = "link";
    link.textContent = "Download Backup";
    box.prepend(link);
    addMessage("Backup created.", "bot");
  } catch (err) {
    addMessage(`Backup failed: ${err.message}`, "bot");
  }
}

async function loadOpenClawStatus() {
  const box = document.getElementById("openclaw-status");
  if (!box) return;

  try {
    const data = await requestJSON("/api/openclaw/status");
    const modeText = {
      OPENCLAW_PREFERRED: "OpenClaw preferred",
      LOCAL_ONLY: "Local only",
      OPENCLAW_ONLY: "OpenClaw only",
    }[data.mode] || data.mode || "unset";
    if (data.available && data.gateway === "up") {
      box.textContent = `OpenClaw: online (mode=${modeText}, profile=${data.profile || "word-assistant"})`;
    } else {
      const reason = data.reason || "unavailable";
      box.textContent = `OpenClaw: unavailable (mode=${modeText}, reason=${reason})`;
    }
  } catch (err) {
    box.textContent = `OpenClaw status failed: ${err.message}`;
  }
}

function bindEvents() {
  document.getElementById("chat-send").addEventListener("click", () => {
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    sendChat(message);
  });

  document.getElementById("chat-input").addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      document.getElementById("chat-send").click();
    }
  });

  const clearChatBtn = document.getElementById("chat-clear");
  if (clearChatBtn) {
    clearChatBtn.addEventListener("click", clearChatHistory);
  }

  document.getElementById("btn-today").addEventListener("click", () => sendChat("Show me today's plan"));
  document.getElementById("btn-upload").addEventListener("click", () => {
    document.querySelector(".import-panel").scrollIntoView({ behavior: "smooth" });
  });
  document.getElementById("btn-game").addEventListener("click", () => sendChat("Start spelling practice"));
  const dictionaryBtn = document.getElementById("btn-dictionary");
  if (dictionaryBtn) {
    dictionaryBtn.addEventListener("click", () => {
      window.open("/dictionary", "_blank");
    });
  }

  document.getElementById("voice-btn").addEventListener("click", () => {
    if (mediaRecorder) {
      stopRecording();
    } else {
      startRecording();
    }
  });

  document.getElementById("voice-accent").addEventListener("change", updateVoiceOptions);

  document.getElementById("import-text-btn").addEventListener("click", importTextPreview);
  document.getElementById("import-file-btn").addEventListener("click", importFilePreview);
  document.getElementById("commit-btn").addEventListener("click", commitImport);
  document.getElementById("refresh-words").addEventListener("click", refreshWords);
  const pageSize = document.getElementById("word-page-size");
  if (pageSize) {
    pageSize.addEventListener("change", () => {
      wordListState.pageSize = Math.max(1, Number(pageSize.value || 15));
      wordListState.page = 1;
      refreshWords();
    });
  }
  const filterButtons = [...document.querySelectorAll(".filter-btn[data-status]")];
  filterButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      filterButtons.forEach((el) => el.classList.remove("active"));
      btn.classList.add("active");
      wordListState.status = btn.dataset.status || "ALL";
      wordListState.page = 1;
      refreshWords();
    });
  });
  const prevBtn = document.getElementById("word-prev");
  const nextBtn = document.getElementById("word-next");
  if (prevBtn) {
    prevBtn.addEventListener("click", () => {
      if (wordListState.page <= 1) return;
      wordListState.page -= 1;
      refreshWords();
    });
  }
  if (nextBtn) {
    nextBtn.addEventListener("click", () => {
      if (wordListState.page >= wordListState.totalPages) return;
      wordListState.page += 1;
      refreshWords();
    });
  }
  document.getElementById("week-report").addEventListener("click", generateWeekReport);

  document.getElementById("save-settings").addEventListener("click", saveParentSettings);
  document.getElementById("export-csv").addEventListener("click", () => exportWords("csv"));
  document.getElementById("export-xlsx").addEventListener("click", () => exportWords("xlsx"));
  document.getElementById("create-backup").addEventListener("click", createBackup);
  document.getElementById("refresh-openclaw-status").addEventListener("click", loadOpenClawStatus);
}

bindEvents();
loadChatHistory();
loadVoices();
loadParentSettings();
refreshWords();
refreshCorrections();
loadOpenClawStatus();
