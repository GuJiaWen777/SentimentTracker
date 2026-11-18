# 运行与发布手册

## 一次完整本地生成

在项目根目录创建 `.env`。`REDFOX_API_KEY` 用于采集；`WECHAT_APP_ID`、`WECHAT_APP_SECRET` 和可选的 `WECHAT_AUTHOR` 用于发布。默认 LLM 后端为 `api`，必须配置 `LLM_API_KEY`、`LLM_API_MODEL`，可选 `LLM_API_BASE_URL` 和 `LLM_API_TIMEOUT`。`.env` 已被 Git 忽略。

也可以使用已登录的本地客户端：`--llm-backend claude` 或 `--llm-backend codex`。模型分别由 `LLM_CLAUDE_MODEL`、`LLM_CODEX_MODEL` 指定。`LLM_RANK_BATCH_SIZE` 控制每批新闻数，`LLM_SYNTHESIS_CANDIDATES` 控制第二阶段候选数。

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

首次运行或排障时先执行自检：

```powershell
earlydata-weekly doctor --format text
earlydata-weekly doctor --format json   # 供 Agent/脚本读取
```

自检只显示“已配置/未配置”，不会输出密钥。存在 `error` 时命令返回 1；`warn` 不影响本地生成。

使用 P&B Excel 生成：

```powershell
earlydata-weekly run --source xlsx --start 2026-05-25 --end 2026-05-31 `
  --xlsx "C:\data\P&B微信公众号5月数据.xlsx" `
  --output-dir data\reports\20260525_20260531
```

使用 RedFox 生成：

```powershell
earlydata-weekly run --source redfox --start 2026-05-25 --end 2026-05-31 `
  --account "氨基观察" --account "医药魔方"
```

## 发布前检查

检查对应目录中的产物：

1. `articles.json`：文章数量、日期窗口和原始链接正确。
2. `ranking.json`：条目数等于源文章数，ID 唯一，分数和理由与 CEO 重要性一致。
3. `brief.json`：`generation.mode=llm`，重点信号不重复，标签和业务影响能由原文支持。
4. `wechat_article.md`：标题、日期和封面 URL 正确。
5. `wechat_article_img.html`：在浏览器或公众号编辑器预览中确认层级、文字换行和链接。
6. `run.json`：确认后端、模型、提示词版本、token 用量、缓存命中与产物哈希符合本次预期；失败运行也会写入错误类型和信息。

`run` 已在输出前执行 HTML 合规校验，发布时会再次执行。校验失败时不要手工删除 `<span leaf="">`，应修正渲染代码或输入文本。

人工修改 `brief.json` 后，只重新生成 Markdown 和 HTML：

```powershell
earlydata-weekly render --input data\reports\20260525_20260531\brief.json
```

该命令不会调用数据源或 LLM。

## 本地审核工作台

```powershell
earlydata-weekly review --report-dir data\reports\20260525_20260531
```

工作台默认监听 `127.0.0.1:8765`。页面内嵌一次性 token，所有 `/api/*` 请求都会校验 token 和 `Host`；因此浏览器扩展、跨站页面和 DNS 重绑定无法读写审核数据。不要把 `--host` 设为 `0.0.0.0`，除非确实需要在可信局域网内访问。编辑内容和字段锁定状态不会覆盖模型原稿；保存后生成 `brief.reviewed.json`、`review_state.json` 和 `reviewed/wechat_article_img.html`。

生成和采集都会按窗口过滤：`status` 的 `in_window_count` 显示窗口内条数，`issues` 会列出被忽略的窗口外条数。`build` 只把窗口内文章交给 LLM，但会保留完整的 `articles.json` 快照（含稳定 ID），避免误选窗口后丢失原始数据；`run` 在采集阶段就已过滤。

审核台还提供两个辅助区块：

- **候选池**：`brief.json` 的 `alternates` 最多 6 条。选择目标位置后点击“换入”即可替换最终信号，保存后重新渲染，无需重新调用 LLM。
- **跨周趋势**：显示最近数期的信号数量、连续出现的公司和连续出现的技术标签，以及本期相对上期的新增标签。

## 增量排名与跨周历史

默认启用两个本地辅助文件，均已位于被 Git 忽略的 `data/` 下：

```text
data/cache/ranking.json          排名缓存
data/cache/wechat_media.json     微信图片素材去重缓存（发布时生成）
data/history/signals.sqlite3     跨周信号库
```

`build`/`run` 默认复用排名缓存，只对新增或内容变化的文章调用 LLM。缓存键包含模型名和 `RANKING_PROMPT_VERSION`；修改排名提示词后应同步升级该版本号。

```powershell
earlydata-weekly build ... --no-ranking-cache   # 忽略缓存并重新排名
earlydata-weekly build ... --no-history         # 不读取历史上下文
earlydata-weekly build ... --ranking-cache "D:\cache\ranking.json"
earlydata-weekly build ... --history-db "D:\history\signals.sqlite3"
```

审核批准时会自动把本期写入历史库；`review --no-history` 可以关闭趋势面板和自动记录。手动补录与查询：

```powershell
earlydata-weekly history record --report-dir data\reports\20260525_20260531
earlydata-weekly history report --weeks 8 --format text
earlydata-weekly history report --weeks 8 --format json --end 2026-05-31
```

历史库按日期窗口幂等覆盖：同一窗口重复批准或重复 `history record` 不会产生重复记录。历史写入失败不会阻止审核批准，错误记录在 `review_state.json` 的 `history_error`。

## 创建草稿

以下命令会向配置的微信公众号账号创建一条草稿，但不会群发：

```powershell
earlydata-weekly publish `
  --report-dir data\reports\20260525_20260531 `
  --cover "https://www.earlydata.com/assets/early-data-logo.png" `
  --confirm
```

执行前须在审核工作台保存人工稿并点击“确认发布稿”。确认状态记录产物哈希，任何后续修改都会阻止发布，必须重新审核确认。命令成功后将 `media_id` 和产物哈希写入 `publication_receipt.json`；同一版本再次运行默认直接返回已有回执，不重复创建草稿。

修正错别字或小范围调整后，重新审核批准并更新原草稿（而不是新建）：

```powershell
earlydata-weekly publish --report-dir data\reports\20260525_20260531 --update-draft --confirm
```

该命令要求回执中已有 `media_id`；仅在内容哈希变化时执行。微信 access token 会缓存并按 `expires_in` 刷新，网络错误、限流和 token 失效会指数退避重试；封面和文章图片按内容哈希去重上传。

只有迁移旧流程时才使用 `publish --file ... --allow-unreviewed`；该路径仍要求 `--title` 和 `--confirm`，但不会生成审核回执。为防止本地文件被带出，HTML 中 `<img src="...">` 的本地路径必须位于该 HTML 所在目录内；`--cover` 显式传入的本地图片路径不受此限制。

## 常见故障

| 现象 | 处理 |
| --- | --- |
| 环境或凭据不确定 | 运行 `earlydata-weekly doctor --format text`，按 `error` 项处理。 |
| `another build is already running` | 同一报告目录已有进程在运行；等待其结束。若确认已崩溃，删除该目录下的 `.earlydata.lock` 后重试。 |
| `schema_version` 过新 | 该文件由更新版本写出；升级本工具后再读取，不要手工改版本号。 |
| `REDFOX_API_KEY is missing` | 在项目根目录 `.env` 配置密钥，重新运行。 |
| `LLM_API_KEY/LLM_API_MODEL is required` | 配置 OpenAI-compatible API，或显式改用 `--llm-backend claude/codex`。 |
| Claude `402 Insufficient Balance` | 为当前 Claude 网关充值或改用其他已配置 LLM 后端。 |
| Codex 模型要求新版 CLI | 用 `LLM_CODEX_MODEL` 指定当前 CLI 支持的模型，或升级客户端后再运行。 |
| LLM 排名 ID 不匹配 | 模型没有遵守结构化输出；缩小 `LLM_RANK_BATCH_SIZE` 或更换模型，不要切换规则模式伪装成功。 |
| Excel 输出为 0 篇 | 核对日期列和 `--start` / `--end`；日期范围是闭区间。 |
| HTML 校验失败 | 检查是否引入 `style`、`script`、`div`、`class` 或漏掉 `span leaf`。 |
| 微信 token / IP 白名单错误 | 在公众号后台将执行机器的公网 IP 加入白名单。 |
| 封面上传失败 | 确认 URL 可公开访问，或传入可读取的本地图片路径。 |

草稿写入后若需要撤回或删除，应在公众号后台操作；该项目不提供自动删除草稿的命令。
