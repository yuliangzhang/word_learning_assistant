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
    a.textContent = `打开: ${link}`;
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
    addMessage(`语音播报失败: ${err.message}`, "bot");
  }
}

async function sendChat(message) {
  addMessage(message, "user");
  try {
    const data = await requestJSON("/api/chat", {
      method: "POST",
      body: JSON.stringify({ user_id: USER_ID, message }),
    });
    addMessage(data.reply || "已处理");
    renderLinks(data.links || []);
    if (data.route_source === "openclaw") {
      const status = document.getElementById("openclaw-status");
      if (status) {
        status.textContent = `聊天编排：OpenClaw（命令：${data.route_command || "自然语言"}）`;
      }
    } else if (data.route_source === "openclaw_unavailable") {
      const status = document.getElementById("openclaw-status");
      if (status) {
        status.textContent = "聊天编排：OpenClaw 当前不可用，已按设置处理。";
      }
    }
    if (data.reply) {
      speakText(data.reply);
    }
  } catch (err) {
    addMessage(`请求失败: ${err.message}`);
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
      <span>${item.needs_confirmation ? "需确认" : "自动"}</span>
    `;
    list.appendChild(row);
  });
  wrap.classList.remove("hidden");
}

async function importTextPreview() {
  const text = document.getElementById("import-text").value.trim();
  if (!text) {
    addMessage("请先粘贴文本再预览。");
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
    addMessage(`已生成导入预览，共 ${data.preview_items.length} 条（自动阈值 ${threshold}）。`);
  } catch (err) {
    addMessage(`文本预览失败: ${err.message}`);
  }
}

async function importFilePreview() {
  const input = document.getElementById("file-input");
  if (!input.files || !input.files.length) {
    addMessage("请先选择文件。", "bot");
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
    const selectionMode = data.selection_mode === "smart" ? "智能筛选" : "标准筛选";
    addMessage(`文件预览完成 (${data.source_type}, OCR=${mode}, ${selectionMode})，共 ${data.preview_items.length} 条。`);
  } catch (err) {
    addMessage(`文件预览失败: ${err.message}`);
  }
}

async function commitImport() {
  if (!currentImportId) {
    addMessage("还没有可提交的导入批次。", "bot");
    return;
  }

  const checked = [...document.querySelectorAll("#preview-list input[type='checkbox']:checked")]
    .map((node) => Number(node.dataset.id));

  try {
    const data = await requestJSON("/api/import/commit", {
      method: "POST",
      body: JSON.stringify({ import_id: currentImportId, accepted_item_ids: checked }),
    });
    addMessage(`导入完成，入库 ${data.imported_words} 个单词。`);
    currentImportId = null;
    document.getElementById("preview-wrap").classList.add("hidden");
    refreshWords();
    refreshCorrections();
  } catch (err) {
    addMessage(`提交失败: ${err.message}`);
  }
}

async function correctWord(wordId, lemma) {
  const input = prompt(`将 ${lemma} 修正为：`, lemma);
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
    addMessage(`修正成功：${lemma} -> ${data.word.lemma}`);
    refreshWords();
    refreshCorrections();
  } catch (err) {
    addMessage(`修正失败: ${err.message}`);
  }
}

async function deleteWord(wordId, lemma) {
  const ok = confirm(`确认删除单词 "${lemma}" 吗？此操作会删除相关学习记录。`);
  if (!ok) return;

  try {
    await requestJSON(`/api/words/${wordId}?user_id=${USER_ID}&deleted_by_role=CHILD`, {
      method: "DELETE",
    });
    addMessage(`已删除：${lemma}`);
    refreshWords();
    refreshCorrections();
  } catch (err) {
    addMessage(`删除失败: ${err.message}`);
  }
}

function statusText(status) {
  const key = String(status || "").toUpperCase();
  if (key === "MASTERED") return "已掌握";
  if (key === "LEARNING" || key === "REVIEWING") return "学习中";
  if (key === "SUSPENDED") return "暂停";
  return "未学习";
}

function statusFilterText(filter) {
  const key = String(filter || "ALL").toUpperCase();
  if (key === "MASTERED") return "已掌握";
  if (key === "IN_PROGRESS" || key === "LEARNING") return "学习中";
  if (key === "NEW") return "未学习";
  return "全部";
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
    info.textContent = `第 ${wordListState.page} / ${wordListState.totalPages} 页`;
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
      summary.textContent = `当前词库：${wordListState.total} 个（筛选：${statusFilterText(wordListState.status)}）`;
    }
    data.items.forEach((word) => {
      const li = document.createElement("li");
      li.className = "word-row";
      const next = word.next_review_at ? new Date(word.next_review_at).toLocaleString() : "-";
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.textContent = `${word.lemma} | 状态: ${statusText(word.status)} | 下次复习: ${next}`;

      const actionWrap = document.createElement("div");
      actionWrap.className = "word-actions";
      const select = document.createElement("select");
      select.className = "action-select";
      select.innerHTML = `
        <option value="">操作</option>
        <option value="correct">纠正</option>
        <option value="delete">删除</option>
        <option value="status:NEW">设为未学习</option>
        <option value="status:LEARNING">设为学习中</option>
        <option value="status:MASTERED">设为已掌握</option>
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
            addMessage(`状态已更新：${word.lemma} -> ${statusText(updated.status)}`);
            refreshWords();
            return;
          }
        } catch (err) {
          addMessage(`操作失败: ${err.message}`);
        }
      });
      actionWrap.appendChild(select);

      li.appendChild(meta);
      li.appendChild(actionWrap);
      list.appendChild(li);
    });
    renderWordPager();
  } catch (err) {
    addMessage(`刷新词库失败: ${err.message}`);
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
    addMessage(`读取修正记录失败: ${err.message}`);
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
    htmlLink.textContent = "打开周报 HTML";
    box.appendChild(htmlLink);

    const csvLink = document.createElement("a");
    csvLink.className = "link";
    csvLink.href = data.csv_url;
    csvLink.target = "_blank";
    csvLink.textContent = "下载周报 CSV";
    box.appendChild(csvLink);

    addMessage(`周报生成成功，正确率 ${(data.report.accuracy * 100).toFixed(0)}%。`);
  } catch (err) {
    addMessage(`周报生成失败: ${err.message}`);
  }
}

async function loadVoices() {
  try {
    const data = await requestJSON("/api/speech/voices");
    window.voiceOptions = data.voices || {};
    updateVoiceOptions();
  } catch (err) {
    addMessage(`读取语音配置失败: ${err.message}`);
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
    addMessage("当前浏览器不支持录音。", "bot");
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
    document.getElementById("voice-btn").textContent = "停止录音";
    addMessage("录音中...再次点击可结束。", "bot");
  } catch (err) {
    addMessage(`开启录音失败: ${err.message}`, "bot");
  }
}

function stopRecording() {
  if (!mediaRecorder) return;
  mediaRecorder.stop();
  mediaRecorder = null;
  document.getElementById("voice-btn").textContent = "开始录音";
}

async function submitStt(blob) {
  const form = new FormData();
  form.append("file", blob, "record.webm");
  try {
    const data = await requestJSON("/api/speech/stt", { method: "POST", body: form });
    addMessage(`语音识别: ${data.text}`, "user");
    if (document.getElementById("auto-send-stt").checked) {
      sendChat(data.text);
    } else {
      document.getElementById("chat-input").value = data.text;
    }
  } catch (err) {
    addMessage(`语音识别失败: ${err.message}`, "bot");
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
    addMessage(`读取家长设置失败: ${err.message}`);
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
    addMessage("家长设置已保存。", "bot");
  } catch (err) {
    addMessage(`保存家长设置失败: ${err.message}`, "bot");
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
    link.textContent = `下载词库 ${fmt.toUpperCase()} (${data.count} 条)`;
    box.prepend(link);
  } catch (err) {
    addMessage(`导出失败: ${err.message}`, "bot");
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
    link.textContent = "下载备份包";
    box.prepend(link);
    addMessage("备份已创建。", "bot");
  } catch (err) {
    addMessage(`创建备份失败: ${err.message}`, "bot");
  }
}

async function loadOpenClawStatus() {
  const box = document.getElementById("openclaw-status");
  if (!box) return;

  try {
    const data = await requestJSON("/api/openclaw/status");
    const modeText = {
      OPENCLAW_PREFERRED: "OpenClaw优先",
      LOCAL_ONLY: "仅本地",
      OPENCLAW_ONLY: "仅OpenClaw",
    }[data.mode] || data.mode || "未设置";
    if (data.available && data.gateway === "up") {
      box.textContent = `OpenClaw: 在线（mode=${modeText}, profile=${data.profile || "word-assistant"}）`;
    } else {
      const reason = data.reason || "不可用";
      box.textContent = `OpenClaw: 不可用（mode=${modeText}，原因: ${reason}）`;
    }
  } catch (err) {
    box.textContent = `OpenClaw 状态读取失败: ${err.message}`;
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

  document.getElementById("btn-today").addEventListener("click", () => sendChat("帮我看今天任务"));
  document.getElementById("btn-upload").addEventListener("click", () => {
    document.querySelector(".import-panel").scrollIntoView({ behavior: "smooth" });
  });
  document.getElementById("btn-game").addEventListener("click", () => sendChat("开始拼写练习"));
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
loadVoices();
loadParentSettings();
refreshWords();
refreshCorrections();
loadOpenClawStatus();
addMessage("欢迎使用单词管家。你可以直接说需求，我会理解并执行。", "bot");
