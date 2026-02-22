from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    user_id: int = Field(default=2)
    message: str


class ReviewRequest(BaseModel):
    user_id: int = Field(default=2)
    word_id: int
    passed: bool
    mode: str = Field(default="SPELLING")
    error_type: str = Field(default="SPELLING")
    user_answer: str | None = None
    correct_answer: str | None = None
    latency_ms: int | None = None


class TextImportRequest(BaseModel):
    user_id: int = Field(default=2)
    text: str
    source_name: str = Field(default="manual_input")
    importer_role: str = Field(default="CHILD")
    tags: list[str] = Field(default_factory=list)
    note: str | None = None


class ImportCommitRequest(BaseModel):
    import_id: int
    accepted_item_ids: list[int] = Field(default_factory=list)


class CardRequest(BaseModel):
    user_id: int = Field(default=2)
    card_type: str = Field(default="MUSEUM")
    regenerate: bool = False


class ExerciseRequest(BaseModel):
    user_id: int = Field(default=2)
    mode: str = Field(default="spelling")
    limit: int = Field(default=10, ge=1, le=30)


class WordCorrectionRequest(BaseModel):
    user_id: int = Field(default=2)
    new_lemma: str
    new_surface: str | None = None
    reason: str | None = None
    corrected_by_role: str = Field(default="CHILD")


class WordStatusUpdateRequest(BaseModel):
    user_id: int = Field(default=2)
    status: str


class DictionaryAddRequest(BaseModel):
    user_id: int = Field(default=2)
    word: str
    tags: list[str] = Field(default_factory=lambda: ["dictionary"])


class ParentSettingsUpdateRequest(BaseModel):
    child_user_id: int = Field(default=2)
    daily_new_limit: int | None = Field(default=None, ge=1, le=40)
    daily_review_limit: int | None = Field(default=None, ge=1, le=200)
    orchestration_mode: str | None = None
    ocr_strength: str | None = None
    correction_auto_accept_threshold: float | None = Field(default=None, ge=0.5, le=0.99)
    strict_mode: bool | None = None
    llm_enabled: bool | None = None
    voice_accent: str | None = None
    tts_voice: str | None = None
    auto_tts: bool | None = None
    llm_provider: str | None = None
    llm_model: str | None = None
    card_llm_quality_model: str | None = None
    card_llm_fast_model: str | None = None
    card_llm_strategy: str | None = None


class TTSRequest(BaseModel):
    text: str
    accent: str = Field(default="en-GB")
    voice: str | None = None
