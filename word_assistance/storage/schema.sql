PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  role TEXT NOT NULL CHECK (role IN ('PARENT', 'CHILD')),
  display_name TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS words (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  lemma TEXT NOT NULL,
  surface TEXT NOT NULL,
  phonetic TEXT,
  pos TEXT,
  meaning_zh TEXT NOT NULL DEFAULT '[]',
  meaning_en TEXT NOT NULL DEFAULT '[]',
  examples TEXT NOT NULL DEFAULT '[]',
  tags TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL CHECK (status IN ('NEW','LEARNING','REVIEWING','MASTERED','SUSPENDED')) DEFAULT 'NEW',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(user_id, lemma),
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS imports (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  source_type TEXT NOT NULL,
  source_name TEXT NOT NULL,
  source_path TEXT,
  importer_role TEXT NOT NULL,
  tags TEXT NOT NULL DEFAULT '[]',
  note TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS import_items (
  id INTEGER PRIMARY KEY,
  import_id INTEGER NOT NULL,
  word_candidate TEXT NOT NULL,
  suggested_correction TEXT NOT NULL,
  confidence REAL NOT NULL,
  needs_confirmation INTEGER NOT NULL DEFAULT 0,
  accepted INTEGER,
  final_lemma TEXT,
  FOREIGN KEY(import_id) REFERENCES imports(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY,
  word_id INTEGER NOT NULL,
  review_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  result TEXT NOT NULL CHECK (result IN ('PASS', 'FAIL')),
  mode TEXT NOT NULL CHECK (mode IN ('MEANING','SPELLING','DICTATION','CLOZE','MATCH')),
  error_type TEXT NOT NULL CHECK (error_type IN ('SPELLING','CONFUSION','MEANING','PRONUNCIATION','OTHER')),
  user_answer TEXT,
  correct_answer TEXT,
  latency_ms INTEGER,
  FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS srs_state (
  word_id INTEGER PRIMARY KEY,
  last_review_at TEXT,
  next_review_at TEXT,
  ease REAL NOT NULL DEFAULT 2.5,
  interval_days INTEGER NOT NULL DEFAULT 1,
  streak INTEGER NOT NULL DEFAULT 0,
  lapses INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS cards (
  id INTEGER PRIMARY KEY,
  word_id INTEGER NOT NULL,
  type TEXT NOT NULL CHECK (type IN ('KIDS','MUSEUM')),
  html_path TEXT NOT NULL,
  version TEXT NOT NULL,
  content_hash TEXT NOT NULL,
  model_used TEXT NOT NULL DEFAULT 'rule_based_mvp',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(word_id, type, version),
  FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS exercise_sessions (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  type TEXT NOT NULL,
  html_path TEXT NOT NULL,
  word_ids TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS chat_messages (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  message TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS word_corrections (
  id INTEGER PRIMARY KEY,
  word_id INTEGER NOT NULL,
  user_id INTEGER NOT NULL,
  old_lemma TEXT NOT NULL,
  new_lemma TEXT NOT NULL,
  old_surface TEXT,
  new_surface TEXT,
  reason TEXT,
  corrected_by_role TEXT NOT NULL CHECK (corrected_by_role IN ('PARENT', 'CHILD')),
  corrected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS parent_settings (
  id INTEGER PRIMARY KEY,
  parent_user_id INTEGER NOT NULL,
  child_user_id INTEGER NOT NULL UNIQUE,
  daily_new_limit INTEGER NOT NULL DEFAULT 8,
  daily_review_limit INTEGER NOT NULL DEFAULT 20,
  orchestration_mode TEXT NOT NULL DEFAULT 'OPENCLAW_PREFERRED'
    CHECK (orchestration_mode IN ('OPENCLAW_PREFERRED','LOCAL_ONLY','OPENCLAW_ONLY')),
  strict_mode INTEGER NOT NULL DEFAULT 0,
  llm_enabled INTEGER NOT NULL DEFAULT 1,
  voice_accent TEXT NOT NULL DEFAULT 'en-GB',
  tts_voice TEXT NOT NULL DEFAULT 'en-GB-SoniaNeural',
  auto_tts INTEGER NOT NULL DEFAULT 0,
  ocr_strength TEXT NOT NULL DEFAULT 'BALANCED'
    CHECK (ocr_strength IN ('FAST','BALANCED','ACCURATE')),
  correction_auto_accept_threshold REAL NOT NULL DEFAULT 0.85
    CHECK (correction_auto_accept_threshold >= 0.5 AND correction_auto_accept_threshold <= 0.99),
  llm_provider TEXT NOT NULL DEFAULT 'openai-compatible',
  llm_model TEXT NOT NULL DEFAULT 'gpt-4o-mini',
  card_llm_quality_model TEXT NOT NULL DEFAULT 'gpt-4.1-mini',
  card_llm_fast_model TEXT NOT NULL DEFAULT 'gpt-4o-mini',
  card_llm_strategy TEXT NOT NULL DEFAULT 'QUALITY_FIRST'
    CHECK (card_llm_strategy IN ('QUALITY_FIRST','BALANCED','FAST_FIRST')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(parent_user_id) REFERENCES users(id) ON DELETE CASCADE,
  FOREIGN KEY(child_user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_words_user_status ON words(user_id, status);
CREATE INDEX IF NOT EXISTS idx_reviews_word_time ON reviews(word_id, review_at);
CREATE INDEX IF NOT EXISTS idx_imports_user_time ON imports(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_chat_messages_user_time ON chat_messages(user_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_word_corrections_word_time ON word_corrections(word_id, corrected_at);
