from __future__ import annotations

import re
from pathlib import Path

from word_assistance.cards.generator import (
    _build_semantic_topology,
    _is_low_signal_mermaid_topology,
    _normalize_mermaid_graph_td,
    generate_card,
)
from word_assistance.cards.templates import ensure_museum_payload
from word_assistance.pipeline.importer import build_import_preview_from_text


def _seed_word(db):
    preview = build_import_preview_from_text("antenna")
    import_id = db.create_import(
        user_id=2,
        source_type="TEXT",
        source_name="seed",
        source_path=None,
        importer_role="CHILD",
        tags=["seed"],
        note=None,
    )
    db.add_import_items(import_id, preview)
    db.commit_import(import_id)


def test_museum_payload_requires_fields():
    try:
        ensure_museum_payload({"word": "Antenna"})
    except ValueError as exc:
        assert "missing fields" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_generate_card_with_cache_and_regenerate(temp_db):
    _seed_word(temp_db)

    first = generate_card(db=temp_db, user_id=2, word="antenna", card_type="MUSEUM", regenerate=False)
    second = generate_card(db=temp_db, user_id=2, word="antenna", card_type="MUSEUM", regenerate=False)
    third = generate_card(db=temp_db, user_id=2, word="antenna", card_type="MUSEUM", regenerate=True)

    assert first["cached"] is False
    assert second["cached"] is True
    assert third["cached"] is False
    assert first["html_path"] != third["html_path"]


def test_museum_card_has_word_specific_content(temp_db):
    preview = build_import_preview_from_text("accommodate")
    import_id = temp_db.create_import(
        user_id=2,
        source_type="TEXT",
        source_name="seed",
        source_path=None,
        importer_role="CHILD",
        tags=["seed"],
        note=None,
    )
    temp_db.add_import_items(import_id, preview)
    temp_db.commit_import(import_id)

    card = generate_card(db=temp_db, user_id=2, word="accommodate", card_type="MUSEUM", regenerate=True)
    html = Path(card["html_path"]).read_text(encoding="utf-8")
    assert "accommodate" in html.lower()
    assert "CORE MEANING (核心语义)" in html
    assert "NUANCE & CONTEXT (语感与语境)" in html
    assert "识别 + 场景 + 复述 = 稳定记忆" not in html


def test_museum_card_for_necessary_uses_non_template_meaning(temp_db):
    preview = build_import_preview_from_text("necessary")
    import_id = temp_db.create_import(
        user_id=2,
        source_type="TEXT",
        source_name="seed",
        source_path=None,
        importer_role="CHILD",
        tags=["seed"],
        note=None,
    )
    temp_db.add_import_items(import_id, preview)
    temp_db.commit_import(import_id)

    card = generate_card(db=temp_db, user_id=2, word="necessary", card_type="MUSEUM", regenerate=True)
    html = Path(card["html_path"]).read_text(encoding="utf-8")
    assert "necessary" in html.lower()
    assert "core formula" in html.lower()
    assert "graph TD" in html
    assert "Syntax error in text" not in html
    assert "class=\"bi-zh\"" in html
    assert "class=\"bi-en\"" in html
    assert "graph TD" in html
    assert "topology-source:" in html
    assert "definition unavailable" not in html.lower()


def test_mermaid_topology_normalizer_keeps_graph_shape():
    raw = """```mermaid
graph TD
A[root origin] -->|trigger| B(core action)
B --> C[modern meaning]
C --> D[usage branch]
style A fill:#fff
```"""
    normalized = _normalize_mermaid_graph_td(raw)
    assert normalized is not None
    assert normalized.startswith("graph TD")
    assert "A[root origin]" in normalized
    assert "B[core action]" in normalized
    assert "C[modern meaning]" in normalized
    assert "style" not in normalized


def test_semantic_topology_fallback_shape():
    topo = _build_semantic_topology(
        word="accommodate",
        etymology="来自拉丁语 accommodare，表示使之合适。",
        core_action="调整条件以容纳差异",
        modern_usage="在现代语境中指给人或需求留出空间并适配",
        meaning_hint="提供空间并满足需要",
        regenerate=True,
    )
    assert topo.startswith("graph TD")
    assert "accommod" in topo.lower()
    assert topo.count("-->") >= 5


def test_low_signal_mermaid_topology_detection():
    generic = """graph TD
  A[词源]
  B[核心动作]
  C[抽象含义]
  D[现代用法]
  A --> B
  B --> C
  B --> D
"""
    assert _is_low_signal_mermaid_topology(generic, word="penitentiary") is True

    informative = """graph TD
  A[paenitentia 忏悔]
  B[惩戒并改造]
  C[长期监禁机构]
  D[rehabilitation over revenge]
  A --> B
  B --> C
  B --> D
    """
    assert _is_low_signal_mermaid_topology(informative, word="penitentiary") is False


def test_cache_invalidates_low_signal_mermaid(temp_db):
    _seed_word(temp_db)
    first = generate_card(db=temp_db, user_id=2, word="antenna", card_type="MUSEUM", regenerate=False)
    path = Path(first["html_path"])
    html = path.read_text(encoding="utf-8")
    html = re.sub(
        r'(<div class="mermaid">\s*)(.*?)(\s*</div>)',
        (
            "\\1"
            "graph TD\n  A[词源]\n  B[核心动作]\n  C[抽象含义]\n  D[现代用法]\n"
            "  A --> B\n  B --> C\n  B --> D"
            "\\3"
        ),
        html,
        flags=re.DOTALL,
    )
    path.write_text(html, encoding="utf-8")

    next_card = generate_card(db=temp_db, user_id=2, word="antenna", card_type="MUSEUM", regenerate=False)
    assert next_card["cached"] is False
    assert next_card["html_path"] != first["html_path"]
