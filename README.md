# Word Assistance MVP

基于 `app_dev.md` 的可运行实现，目标是让孩子通过 WebChat + 语音 + LLM 交互完成单词导入、纠错、复习、练习和周报。

当前版本采用「`Word Assistance` 业务服务 + `OpenClaw` 编排层」双层架构：
- `word_assistance`（FastAPI）：承载词库、导入、纠错、SRS、练习、语音、报告等核心能力
- `openclaw_workspace`（OpenClaw Agent）：承载自然语言编排、技能路由、安全边界、跨渠道接入

## 已实现功能（MVP）

- WebChat 入口（儿童友好：大按钮 + 自然语言 + 聊天命令）
- 统一聊天入口：`/api/chat` 先尝试 OpenClaw Agent 编排，失败自动回退本地执行
- 聊天动作保障：识别到可执行学习意图时，保证落地到本地命令执行（避免“只聊天不执行”）
- 记忆与自适应：基于 SRS 状态（streak/lapses）+ 错题统计动态排序今日学习优先级
- LLM 路由：自然语言需求自动转成可执行指令（如修正单词、生成周报）
- 导入预览：文本/文件（PDF/Excel/CSV/TXT）
- 图片 OCR 强化：图像预处理 + OCR + 视觉模型兜底
- 纠错输出：原词、候选、置信度、是否需人工确认
- 已入库单词修正入口（UI + API + 修正历史记录）
- 词库与状态：`NEW/LEARNING/REVIEWING/MASTERED/SUSPENDED`
- SRS 调度：PASS/FAIL 更新 `next_review_at/ease/interval/streak/lapses`
- 练习页生成：`MATCH/SPELL/DICTATION/CLOZE`
- 真实语音：STT（语音转文字）+ TTS（支持英式口音可选）
- 周报生成：HTML + CSV（含 Top 错题与下周建议）
- 家长配置面板：学习强度、严格模式、导出 CSV/XLSX、一键备份/恢复
- 家长可调 OCR 强度（FAST/BALANCED/ACCURATE）与导入自动通过阈值
- Museum/Kids 单词卡：对齐 `ljg-explain-words` 结构（Definition Deep / Etymology / Nuance / Topology / Epiphany），两段式（JSON -> HTML），支持缓存与重生成
- 学习工作台：左侧今日单词列表，右侧卡片（按需生成）；可一键切换任意待学词
- 今日练习页缓存：`spell + match` 合一页面，按“用户+日期+今日任务”缓存，可按需重生成
- 安全基线：Reader/Tutor 分层、注入内容清洗、默认拒绝高风险请求

## 目录

- `/word_assistance`：后端代码
- `/templates`：首页
- `/static`：前端 JS/CSS 与本地 mermaid 资源
- `/artifacts`：卡片/练习/周报输出
- `/skill/word-assistance`：技能说明与 prompt
- `/openclaw_workspace`：OpenClaw Agent 工作区（含词汇助手 skill）
- `/scripts`：一键启动/停止/状态检查脚本
- `/tests`：单测与集成测试

## 快速运行（推荐）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./scripts/dev_up.sh
```

启动后：
- Word Assistance Web：`http://127.0.0.1:8000`
- OpenClaw Control UI：`http://127.0.0.1:18789/openclaw`

停止服务：

```bash
./scripts/dev_down.sh
```

状态检查：

```bash
./scripts/dev_status.sh
```

## Ubuntu 一键部署（systemd）

推荐系统：`Ubuntu 22.04/24.04`。  
脚本会自动完成：安装依赖、拉取代码、创建 `.venv`、安装 Python 依赖、生成 systemd 服务并启动。

### 1. 首次部署（One Command）

```bash
git clone https://github.com/yuliangzhang/word_learning_assistant.git
cd word_learning_assistant
chmod +x scripts/deploy_linux.sh scripts/deploy_ubuntu.sh scripts/update_linux.sh
sudo APP_DIR=/opt/word_learning_assistant BRANCH=main ./scripts/deploy_ubuntu.sh
```

首次部署会自动创建：
- 应用目录：`/opt/word_learning_assistant`
- 环境文件：`/opt/word_learning_assistant/.env`
- 服务名：`word-learning-assistant`

### 2. 配置 API Key（只做一次）

```bash
sudo vim /opt/word_learning_assistant/.env
```

建议至少配置：
- `OPENAI_API_KEY=...`
- `WORD_ASSISTANCE_CARD_LLM_QUALITY_MODEL=...`
- `WORD_ASSISTANCE_CARD_LLM_FAST_MODEL=...`

保存后重启服务：

```bash
sudo systemctl restart word-learning-assistant
```

### 3. 服务管理与排错

```bash
sudo systemctl status word-learning-assistant
sudo journalctl -u word-learning-assistant -f
curl -fsS http://127.0.0.1:8000/health
```

### 4. 一键更新（后续升级）

```bash
cd /opt/word_learning_assistant
sudo ./scripts/update_linux.sh
```

### 5. 可选自定义参数

部署时可覆盖默认值：

```bash
sudo APP_DIR=/opt/word_learning_assistant \
  APP_PORT=8000 \
  SERVICE_NAME=word-learning-assistant \
  APP_USER=$USER \
  BRANCH=main \
  ./scripts/deploy_ubuntu.sh
```

如果服务器有多版本 Python，可显式指定：

```bash
sudo PYTHON_BIN=python3 PYTHON_PACKAGE=python3 ./scripts/deploy_ubuntu.sh
```

## 仅启动业务服务（不启 OpenClaw）

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m word_assistance
```

浏览器打开：`http://127.0.0.1:8000`

### 可选环境变量（建议配置）

```bash
# LLM 路由（OpenAI）
export OPENAI_API_KEY=...
export WORD_ASSISTANCE_LLM_MODEL=gpt-4o-mini
# 可选：显式关闭卡片 LLM（默认有 key 时自动启用）
# export WORD_ASSISTANCE_CARD_LLM_ENABLED=0

# 或者 DeepSeek（OpenAI 兼容）
export WORD_ASSISTANCE_LLM_PROVIDER=deepseek
export DEEPSEEK_API_KEY=...
export WORD_ASSISTANCE_LLM_MODEL=deepseek-chat
```

说明：
- 未配置 API Key 时，系统会使用内置规则路由（仍可用）。
- Museum 卡片在检测到可用 API Key 时会自动调用模型做深度词义解构；若失败则回落到本地知识库。
- 可通过 `WORD_ASSISTANCE_CARD_LLM_ENABLED=0` 强制关闭卡片模型生成。
- STT 默认依赖 `OPENAI_API_KEY`；TTS 优先 `edge-tts`（可选英式声音）。
- OpenClaw Agent 对话若要调用云模型，需要先配置对应 provider 的 key（例如 `OPENAI_API_KEY`）。

## 测试

```bash
pytest -q
```

Playwright E2E：

```bash
./scripts/e2e_playwright.sh
```

学习工作台与卡片接口：

- 工作台由聊天 `/learn` 返回链接（`/artifacts/learning/...`）
- 单词卡按需生成接口：`GET /api/learn/card-url?user_id=<id>&word=<word>&regenerate=0|1`

## OpenClaw 编排模式

可在「家长配置面板」切换 `orchestration_mode`：

- `OPENCLAW_PREFERRED`（默认）：优先 OpenClaw，失败回退本地执行
- `LOCAL_ONLY`：仅使用本地执行（不调用 OpenClaw）
- `OPENCLAW_ONLY`：仅使用 OpenClaw；若不可用则返回不可用提示

接口：
- 读取：`GET /api/parent/settings?child_user_id=<id>`
- 更新：`POST /api/parent/settings`
- 状态：`GET /api/openclaw/status?child_user_id=<id>`

## OpenClaw 词汇助手 Skill

- skill 路径：`/Users/yuliangzhang/Documents/New project/openclaw_workspace/skills/word-assistant`
- 入口脚本：`word_assistance_cli.py`（通过固定子命令调用业务 API，避免任意命令执行）
- 支持能力：
  - 学习链路（`/learn`）、今日任务（`/today`）、词库清单（`/words`）、聊天执行、导入文本并提交
  - 已导入单词纠错（`fix-lemma`）
  - 生成卡片/周报
  - 家长设置读取与更新
- 状态接口：`GET /api/openclaw/status`

## 已安装并使用的 Skills（构建过程）

以下 skills 已安装到 `/Users/yuliangzhang/.codex/skills`，并在本项目构建中使用：

- `doc`：快速检索框架/工具文档，减少配置和接口误配
- `playwright`：用于规划和执行 Web 端到端验证
- `speech`：语音能力落地参考（STT/TTS 流程与质量检查）
- `security-best-practices`：用于安全基线核对（高风险能力默认关闭、输入不可信处理）
- `ljg-explain-words`：参考博物馆级单词卡视觉结构与内容编排
- `word-lexicon-enricher`（本项目内置 skill）：用于查中英释义并持久化，供释义匹配题与词卡复用

## 说明

Museum 卡样式结构参考了 `https://github.com/lijigang/ljg-skill-explain-words/tree/master/skills/ljg-explain-words` 技能思路，并改为本项目的两步生成与本地存档路径约束。
