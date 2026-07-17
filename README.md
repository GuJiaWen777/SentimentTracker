# EarlyData Weekly Publisher

独立、可复跑的公众号周报交付工具，只保留完整核心闭环：

```text
RedFox API 或 P&B Excel -> LLM 全量语义排名 -> LLM 板块分析 -> EarlyData 合规 HTML -> 用户确认 -> 微信草稿箱
```

项目说明：

- [架构与数据契约](docs/ARCHITECTURE.md)
- [运行与发布手册](docs/OPERATIONS.md)
- [内容质量规则](docs/CONTENT_RULES.md)

## 安装

```powershell
cd C:\Users\EDDC\workspace\earlydata-weekly-publisher
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

在 `.env` 中配置数据源、LLM 和微信公众号凭据。不要提交该文件。默认 LLM 后端是 OpenAI-compatible API，需要 `LLM_API_KEY` 和 `LLM_API_MODEL`；也可使用已登录的 Claude 或 Codex CLI。

## 完整流程

从 RedFox 获取并生成本地草稿：

```powershell
earlydata-weekly run --source redfox --start 2026-05-25 --end 2026-05-31 `
  --account "氨基观察" --account "医药魔方"
```

从 P&B Excel 获取并生成本地草稿：

```powershell
earlydata-weekly run --source xlsx --start 2026-05-25 --end 2026-05-31 `
  --xlsx "C:\data\P&B微信公众号5月数据.xlsx"
```

产物写入 `data/reports/YYYYMMDD_YYYYMMDD/`：

- `articles.json`：窗口内原始文章
- `ranking.json`：全部新闻的 LLM 分数、分类和排名理由
- `brief.json`：可审计的内容生成结果
- `wechat_article.md`：源稿与发布元数据
- `wechat_article_img.html`：EarlyData 信号简报主题的合规正文

`build` 会强制校验内联样式、禁用标签和 `<span leaf="">` 包裹，失败不会写出 HTML。

预览和检查 HTML 后，再显式上传：

```powershell
earlydata-weekly publish `
  --report-dir data\reports\20260525_20260531 `
  --cover "https://www.earlydata.com/assets/early-data-logo.png" `
  --confirm
```

先在审核工作台保存并点击“确认发布稿”。`publish --report-dir` 会校验人工稿和 HTML 哈希，成功后记录 `publication_receipt.json`；同一版本再次运行不会重复创建草稿。`--confirm` 仍是草稿箱写入门禁，它只创建草稿，不会群发。

## 命令拆分

```text
fetch         RedFox API -> articles.json
ingest-xlsx   P&B Excel -> articles.json
build         articles.json -> LLM 排名 / brief.json / Markdown / 合规 HTML
run           fetch 或 ingest-xlsx 后自动 build（不发布）
publish       已确认后上传 HTML 到草稿箱
render        人工修改 brief.json 后重新生成 Markdown / HTML（不调用 LLM）
status        检查已有产物并给出下一步，供人工或 agent 续跑
```

检查某个窗口是否已有可复用数据：

```powershell
earlydata-weekly status --start 2026-05-25 --end 2026-05-31
```

输出中的 `stage`、`next_action`、`reuse` 和 `gates` 用于判断是否跳过采集、生成或审核步骤。

人工修改 `brief.json` 后可以单独重新渲染，不会重新采集或消耗模型调用：

```powershell
earlydata-weekly render `
  --input data\reports\20260525_20260531\brief.json
```

使用本地审核工作台编辑、锁定并预览人工稿：

```powershell
earlydata-weekly review `
  --report-dir data\reports\20260525_20260531
```

模型原稿保留为 `brief.json`；人工稿保存为 `brief.reviewed.json`，字段锁定状态保存在 `review_state.json`，预览产物写入 `reviewed/`。

审核工作台会合并 `ranking.json` 与 `articles.json`，显示每条新闻的排名分数、入选理由、原文摘录和来源链接，并标记缺失来源、重复新闻、异常长度及原文中无法直接找到的数字。`build` 会把输入文章快照复制到报告目录，供后续审核复核。

`build` 和 `run` 默认使用 LLM。第一阶段对窗口内全部新闻逐条给出 0-100 分、分类和排名理由；第二阶段从去重后的高分候选中生成最终 6 条、关键信号、仪表盘、标签、摘要、业务影响、管理层洞察和后续追踪。任何模型配置或结构化输出错误都会让命令失败，不会暗中退回规则结果。

仅在离线调试时显式使用规则备用模式：

```powershell
earlydata-weekly build --start 2026-05-25 --end 2026-05-31 `
  --input data\reports\20260525_20260531\articles.json `
  --generator rules
```

使用已登录的本地模型客户端：

```powershell
earlydata-weekly build --start 2026-05-25 --end 2026-05-31 `
  --input data\reports\20260525_20260531\articles.json `
  --llm-backend claude

earlydata-weekly build --start 2026-05-25 --end 2026-05-31 `
  --input data\reports\20260525_20260531\articles.json `
  --llm-backend codex
```

发布前仍应人工核对 `ranking.json`、`brief.json` 与 `wechat_article_img.html` 的事实、公司标签和行动建议。

## 验证

```powershell
pytest -q
earlydata-weekly run --source xlsx --start 2026-05-25 --end 2026-05-31 `
  --xlsx "C:\data\P&B微信公众号5月数据.xlsx" `
  --output-dir data\reports\20260525_20260531
```

`run` 和 `build` 会在写出 HTML 前执行内联样式、禁用标签与 `span leaf` 校验；`publish` 会再次校验，避免未经验证的文件进入草稿箱。
