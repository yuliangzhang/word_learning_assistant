Semantic topology generation rules:

1. Output Mermaid code only, starting with `graph TD`.
2. Topology must represent concept flow:
   - `词源/本义` -> `核心动作` -> `抽象含义/现代用法`
3. Node labels must be short phrases (<= 12 words).
4. Keep graph simple:
   - 4-8 nodes
   - basic `A[xx] --> B[yy]` edges only
5. Do not output:
   - `classDef`, `style`, `click`, `subgraph`, HTML tags
