# EarlyData Weekly Publisher

把一周的生物医药新闻，变成一篇可审核、可追溯、可安全发布到微信公众号草稿箱的 EarlyData 周报。

输入是 RedFox API 或 P&B Excel 导出的原始文章，输出是经过 LLM 语义排名与综合分析的 Markdown 存档、公众号兼容 HTML、人工审核稿，以及一条微信草稿回执。

它不是一个“一键生成”的工具，而是一条**可恢复、可审核、可追溯**的内容流水线。

```mermaid
flowchart LR
    A[自然语言或 CLI] --> B[检查已有状态]
    B --> C[RedFox API / P&B Excel]
    C --> D[articles.json]
    D --> E[LLM 增量排名]
    E --> F[LLM 周报综合分析]
    F --> G[公众号合规 HTML]
    G --> H[本地人工审核]
    H --> I[审批哈希校验]
    I --> J[微信公众号草稿箱]
```

## 核心特性

- **LLM 语义生成**：先对候选新闻批量语义排名，再生成关键信号、背景、CEO 业务影响、公司/技术标签与管理层启示。LLM 失败时不会静默退回规则模式。
- **增量排名缓存**：按文章内容、模型名和排名提示词版本缓存结果。重复运行时只对新增或修改过的文章调用 LLM，命中情况写入 `generation.cache_hits` / `cache_misses`。
- **候选池换稿**：综合阶段同时产出最多 6 条备选信号，审核台可直接换入，无需重新调用 LLM。
- **跨周信号库**：批准时把本期信号、分类和重点实体写入本地 SQLite，支持连续出现、相对上期新增以及跨周数量趋势，并作为下一期选题与综合分析的参考上下文。
- **双数据源**：RedFox API 在线采集，或导入本地 P&B 格式 Excel；两条路径都会按报告日期窗口过滤。
- **断点续跑**：自动识别原始数据、生成稿、审核稿、批准状态和发布回执，优先复用有效产物。
- **人工审核工作台**：在浏览器中编辑内容、锁定字段、查看排名证据、处理质量问题、换入候选、查看趋势，并确认最终发布稿。
- **发布安全门禁**：审核批准与发布授权是两个独立步骤；发布前校验审核稿与 HTML 哈希，发布后保存回执，默认阻止重复创建相同草稿。
- **Agent 引导交付**：仓库自带项目级 Skill，可用自然语言完成日期确认、来源选择、复用判断、审核与发布。

## 快速开始

### 1. 环境与安装

要求 Python 3.10 或更高版本。

```powershell
git clone https://github.com/GuJiaWen777/SentimentTracker.git
cd SentimentTracker
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

按所选数据源、LLM 后端和发布账号填写 `.env`。`.env` 与 `data/` 均已被 Git 忽略，不要提交真实密钥。

### 2. 方式 A：让 Agent 引导

在支持项目级 Skills 的 Agent 中打开仓库，[交付 Skill](.agents/skills/deliver-earlydata-weekly/SKILL.md) 会响应周报生成、继续审核和发布请求：

```text
生成 2026.05.25 到 05.31 的 EarlyData 周报
继续上次的报告，已有数据就不要重新获取
打开本期周报审核页面
确认发布到微信公众号草稿箱
```

Agent 会先检查状态，再只询问当前阶段必需的决定：没有数据时让你选来源，已有 `articles.json` 时建议复用，已有生成稿时直接进入审核，已发布时返回现有回执而不是重复创建草稿。

### 3. 方式 B：CLI 手动执行

所有命令都从仓库根目录运行，安装后命令名为 `earlydata-weekly`。

```powershell
# 1. 先看状态，决定复用还是重新获取
earlydata-weekly status --start 2026-05-25 --end 2026-05-31

# 2. 获取数据（二选一）
earlydata-weekly fetch --start 2026-05-25 --end 2026-05-31 `
  --account "医药魔方" `
  --output "data/reports/20260525_20260531/articles.json"

earlydata-weekly ingest-xlsx --start 2026-05-25 --end 2026-05-31 `
  --xlsx "data/input/weekly.xlsx" `
  --output "data/reports/20260525_20260531/articles.json"

# 3. LLM 排名与生成（或直接用 run 合并第 2、3 步）
earlydata-weekly build --start 2026-05-25 --end 2026-05-31 `
  --input "data/reports/20260525_20260531/articles.json" `
  --output-dir "data/reports/20260525_20260531"

# 4. 本地审核并确认发布稿
earlydata-weekly review --report-dir "data/reports/20260525_20260531"

# 5. 在用户明确确认后写入公众号草稿箱
earlydata-weekly publish --report-dir "data/reports/20260525_20260531" --confirm
```

也可以一步完成采集与生成（`run` 不会发布）：

```powershell
earlydata-weekly run --source xlsx --start 2026-05-25 --end 2026-05-31 `
  --xlsx "data/input/weekly.xlsx" `
  --output-dir "data/reports/20260525_20260531"
```

默认使用 `.env` 中的 `LLM_BACKEND`；也可用 `--llm-backend api|claude|codex` 临时切换。`--generator rules` 仅用于明确选择的离线兜底或测试，不会被自动启用。

默认启用排名缓存（`data/cache/ranking.json`）和跨周历史上下文（`data/history/signals.sqlite3`）。需要完全重新排名或隔离环境时：

```powershell
earlydata-weekly build ... --no-ranking-cache --no-history
```

## 命令参考

| 命令 | 作用 | 调用 LLM |
| --- | --- | --- |
| `status` | 检查产物、状态、可复用项与待处理问题 | 否 |
| `fetch` | 从 RedFox API 采集文章 | 否 |
| `ingest-xlsx` | 导入 P&B Excel 文章 | 否 |
| `run` | 采集 + 生成（组合 `fetch`/`ingest-xlsx` 与 `build`） | 默认是 |
| `build` | 排名、生成 brief、Markdown 与 HTML | 默认是 |
| `render` | 从已编辑的 `brief.json` 重新渲染，不调用模型 | 否 |
| `review` | 启动本地审核工作台 | 否 |
| `history record` | 把一份报告补录进跨周信号库 | 否 |
| `history report` | 查看最近数期的信号数量与实体趋势 | 否 |
| `publish` | 将已批准的 HTML 写入微信草稿箱 | 否 |

`status` 支持 `--report-dir`，或 `--start/--end` 自动寻找同日窗口下进度最完整的目录。

## 工作流状态

| 状态 | 含义 | 下一步 |
| --- | --- | --- |
| `empty` | 没有可复用数据 | 选择 RedFox 或 Excel 来源 |
| `articles_ready` | 已有有效 `articles.json` | 复用数据并运行 LLM 生成 |
| `ready_for_review` | 生成稿与 HTML 已完成 | 打开审核工作台 |
| `review_in_progress` | 已保存人工修改但未批准 | 继续审核并确认发布稿 |
| `approved` | 审核稿与 HTML 哈希有效 | 单独确认是否发布草稿 |
| `published` | 当前批准版本已有发布回执 | 返回回执，避免重复发布 |

`status` 输出中的 `reuse` 表示可复用的产物，`gates` 表示审核与发布门禁，`issues` 会列出窗口不匹配、窗口外文章、缺少原始数据等问题。

## 主要产物

每期报告默认保存在 `data/reports/YYYYMMDD_YYYYMMDD/`：

| 文件 | 用途 |
| --- | --- |
| `articles.json` | 标准化后的原始文章与来源证据（含稳定 ID） |
| `ranking.json` | LLM 排名结果、分数与选择依据 |
| `brief.json` | 生成的结构化初稿，含 `items` 与 `alternates` 候选池 |
| `wechat_article.md` | 便于阅读和归档的 Markdown |
| `wechat_article_img.html` | EarlyData 主题的公众号兼容 HTML |
| `brief.reviewed.json` | 人工保存后的结构化审核稿 |
| `reviewed/wechat_article_img.html` | 审核稿对应的最终 HTML |
| `review_state.json` | 字段锁定、批准状态、内容哈希与历史写入结果 |
| `publication_receipt.json` | 微信草稿 `media_id` 与发布版本哈希 |

跨报告复用的辅助文件：

| 文件 | 用途 |
| --- | --- |
| `data/cache/ranking.json` | 按文章内容、模型和提示词版本索引的排名缓存 |
| `data/history/signals.sqlite3` | 跨周信号、分类和重点实体历史库 |

`build` 会保留完整的 `articles.json` 快照，仅在生成阶段过滤窗口外文章，避免误选窗口时丢失原始数据。

## 审核与发布安全

- 审核工作台默认监听 `127.0.0.1:8765`，页面内嵌一次性 token；所有 `/api/*` 请求同时校验 token 与 `Host`，拒绝跨站请求和 DNS 重绑定。
- 保存审核稿后点击“确认发布稿”，系统记录 `brief.reviewed.json` 与最终 HTML 的哈希。任何后续修改都会使批准失效。
- 候选换稿只替换最终选择，不改写原始文章；保存时会重新计算本期来源列表。
- 跨周历史只在批准时自动写入；趋势写入失败不会阻止批准，错误会记录在 `review_state.json.history_error`。
- 发布前重新校验 HTML 合规性；未批准的报告不能通过 `--report-dir` 发布。
- `publish` 必须显式传入 `--confirm`，且只创建草稿，不群发。
- HTML 中引用的本地图片必须位于报告目录内；显式 `--cover` 传入的本地路径不受此限制。
- 同一批准版本已有有效回执时，发布命令直接返回原 `media_id`；只有明确需要新草稿时才使用 `--force-new-draft`。
- 旧流程迁移可使用 `publish --file ... --allow-unreviewed`，但该路径仍要求 `--title` 与 `--confirm`。

## 配置

### LLM 后端

| `LLM_BACKEND` | 运行方式 | 关键配置 |
| --- | --- | --- |
| `api` | OpenAI 兼容 Chat Completions API | `LLM_API_KEY`、`LLM_API_MODEL`、`LLM_API_BASE_URL`、`LLM_API_TIMEOUT` |
| `claude` | 本机 Claude CLI | CLI 已登录并在 `PATH`，可选 `LLM_CLAUDE_MODEL`、`LLM_CLAUDE_TIMEOUT` |
| `codex` | 本机 Codex CLI | CLI 已登录并在 `PATH`，可选 `LLM_CODEX_MODEL`、`LLM_CODEX_TIMEOUT` |

`LLM_RANK_BATCH_SIZE` 控制每批排名的新闻数，`LLM_SYNTHESIS_CANDIDATES` 控制进入综合阶段的候选数。完整配置见 [.env.example](.env.example)。

### 数据、历史与发布

| 变量 | 用途 |
| --- | --- |
| `REDFOX_API_KEY` | 使用 RedFox API 时必填 |
| `EARLYDATA_RANKING_CACHE` | 排名缓存路径，默认 `data/cache/ranking.json` |
| `EARLYDATA_HISTORY_DB` | 跨周历史库路径，默认 `data/history/signals.sqlite3` |
| `WECHAT_APP_ID` / `WECHAT_APP_SECRET` | 写入公众号草稿箱时必填 |
| `WECHAT_AUTHOR` | 公众号文章作者，默认 `EARLY DATA` |

## 常见问题

| 现象 | 处理 |
| --- | --- |
| `REDFOX_API_KEY is missing` | 在项目根目录 `.env` 配置密钥后重试 |
| `LLM_API_KEY/LLM_API_MODEL is required` | 配置 OpenAI 兼容 API，或显式改用 `--llm-backend claude/codex` |
| Claude `402 Insufficient Balance` | 为当前网关充值，或改用其他已配置后端 |
| LLM 排名 ID 不匹配 | 缩小 `LLM_RANK_BATCH_SIZE` 或更换模型，不要用规则模式伪装成功 |
| Excel 输出为 0 篇 | 核对日期列与 `--start` / `--end`；日期范围是闭区间 |
| HTML 校验失败 | 检查是否引入 `style`、`script`、`div`、`class`，或漏掉 `span leaf` |
| 微信 token / IP 白名单错误 | 在公众号后台把执行机器的公网 IP 加入白名单 |
| 审核页无法加载或 API 报 403 | 确认通过启动时打印的地址访问，且没有从其他站点跳转 |

## 开发与文档

```powershell
pytest -q
```

测试覆盖状态机、窗口过滤、排名缓存、跨周历史、审核服务器鉴权、HTML 合规与发布门禁。

进一步说明：

- [架构说明](docs/ARCHITECTURE.md)
- [内容生成规则](docs/CONTENT_RULES.md)
- [运行与发布手册](docs/OPERATIONS.md)
- [Agent 状态机](.agents/skills/deliver-earlydata-weekly/references/state-machine.md)

## 项目结构

```text
src/earlydata_weekly_publisher/
  pipeline.py            数据采集、窗口过滤、brief 渲染与微信草稿发布
  semantic_generation.py LLM 排名与综合分析
  llm_client.py          API / Claude CLI / Codex CLI 传输层
  ranking_cache.py       增量排名缓存
  signal_history.py      跨周信号库与趋势
  review_app.py          本地审核工作台与 API
  approval.py            审核哈希与批准状态
  quality.py             内容质量检查
  workflow_status.py     可恢复状态机
  cli.py                 命令行入口
tests/                   pytest 测试
docs/                    架构、内容规则、运行手册与 ADR
```

项目保持“小核心”边界：采集、LLM 语义生成、合规 HTML、人工审核与微信草稿交付。通用舆情平台、前端门户和群发运营不在此仓库范围内。
