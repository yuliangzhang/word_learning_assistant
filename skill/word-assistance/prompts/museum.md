你要输出 Museum 卡结构化 JSON，必须包含：
- word
- phonetic
- origin_scene_zh, origin_scene_en
- core_formula_zh, core_formula_en
- explanation_zh, explanation_en
- etymology_zh, etymology_en
- cognates (2-4)
- nuance_points_zh (2-4), nuance_points_en (2-4)
- example_sentence
- mermaid_code
- epiphany
- confidence_note

Semantic Topology 要求（关键）：
- `mermaid_code` 必须以 `graph TD` 开头。
- 结构遵循：`[词源/本义] -> [核心动作] -> [抽象含义/现代用法]`。
- 节点文字简练，避免长段落。
- 只使用基础节点与箭头，不使用 `classDef/style/click/subgraph/HTML`。
