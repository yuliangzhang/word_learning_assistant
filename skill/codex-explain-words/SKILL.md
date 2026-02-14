---
name: codex-explain-words
description: Generate museum-quality English word cards with etymology, bilingual nuance, and model-generated semantic topology (Mermaid graph TD) for Codex-based workflows.
---

## Trigger

Use this skill when the user asks for deep word deconstruction, museum card generation, or semantic topology refinement.

## Workflow

1. Normalize input word (`lowercase`, display as `Capitalized`).
2. Produce bilingual card payload:
   - core meaning: origin scene + core formula + explanation
   - etymology: roots + cognates
   - nuance/context: contrast points + sentence
3. Generate `mermaid_code` with this structure:
   - `[词源/本义] -> [核心动作] -> [抽象含义/现代用法]`
   - keep node labels concise
   - `graph TD` only, basic nodes and arrows only
4. Validate topology:
   - must parse as `graph TD`
   - reject style/class/click/subgraph
   - fallback to safe topology if invalid
5. Render HTML card and persist cache.

## Output Contract

Return JSON fields:
- `phonetic`
- `origin_scene_zh`, `origin_scene_en`
- `core_formula_zh`, `core_formula_en`
- `explanation_zh`, `explanation_en`
- `etymology_zh`, `etymology_en`
- `cognates`
- `nuance_points_zh`, `nuance_points_en`
- `example_sentence`
- `mermaid_code`
- `epiphany`
