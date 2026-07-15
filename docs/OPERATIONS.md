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

检查对应目录中的五个产物：

1. `articles.json`：文章数量、日期窗口和原始链接正确。
2. `ranking.json`：条目数等于源文章数，ID 唯一，分数和理由与 CEO 重要性一致。
3. `brief.json`：`generation.mode=llm`，重点信号不重复，标签和业务影响能由原文支持。
4. `wechat_article.md`：标题、日期和封面 URL 正确。
5. `wechat_article_img.html`：在浏览器或公众号编辑器预览中确认层级、文字换行和链接。

`run` 已在输出前执行 HTML 合规校验，发布时会再次执行。校验失败时不要手工删除 `<span leaf="">`，应修正渲染代码或输入文本。

## 创建草稿

以下命令会向配置的微信公众号账号创建一条草稿，但不会群发：

```powershell
earlydata-weekly publish `
  --file data\reports\20260525_20260531\wechat_article_img.html `
  --title "AI CEO 生物医药舆情周报 2026.05.25-05.31" `
  --cover "https://www.earlydata.com/assets/early-data-logo.png" `
  --confirm
```

执行前须已明确获得发布确认。命令成功后仅记录返回的 `media_id`；在公众号后台继续编辑、预览和群发。

## 常见故障

| 现象 | 处理 |
| --- | --- |
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
