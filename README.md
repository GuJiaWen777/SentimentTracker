# EarlyData Weekly Publisher

独立、可复跑的公众号周报交付工具，只保留完整核心闭环：

```text
RedFox API 或 P&B Excel -> 重点信号内容生成 -> EarlyData 合规 HTML -> 用户确认 -> 微信草稿箱
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

在 `.env` 中配置 `REDFOX_API_KEY`、`WECHAT_APP_ID` 和 `WECHAT_APP_SECRET`。不要提交该文件。

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
- `brief.json`：可审计的内容生成结果
- `wechat_article.md`：源稿与发布元数据
- `wechat_article_img.html`：EarlyData 信号简报主题的合规正文

`build` 会强制校验内联样式、禁用标签和 `<span leaf="">` 包裹，失败不会写出 HTML。

预览和检查 HTML 后，再显式上传：

```powershell
earlydata-weekly publish `
  --file data\reports\20260525_20260531\wechat_article_img.html `
  --title "AI CEO 生物医药舆情周报 2026.05.25-05.31" `
  --cover "https://www.earlydata.com/assets/early-data-logo.png" `
  --confirm
```

`--confirm` 是草稿箱写入门禁。它只创建草稿，不会群发。若接口返回 IP 白名单错误，请在公众号后台加入运行本工具机器的公网 IP。

## 命令拆分

```text
fetch         RedFox API -> articles.json
ingest-xlsx   P&B Excel -> articles.json
build         articles.json -> brief.json / Markdown / 合规 HTML
run           fetch 或 ingest-xlsx 后自动 build（不发布）
publish       已确认后上传 HTML 到草稿箱
```

内容生成默认采用透明规则：互动指标排序、原文摘要截取、药物技术关键词和风险/机会判断。这样无需 LLM 即可稳定复跑；后续可在 `brief.json` 人工调整后重新渲染。

生成时会优先保留产业事件，排除泛健康爆文、会议议程等非编辑信号，并按标题去重。发布前仍应人工核对 `brief.json` 与 `wechat_article_img.html` 的事实、公司标签和行动建议。

## 验证

```powershell
pytest -q
earlydata-weekly run --source xlsx --start 2026-05-25 --end 2026-05-31 `
  --xlsx "C:\data\P&B微信公众号5月数据.xlsx" `
  --output-dir data\reports\20260525_20260531
```

`run` 和 `build` 会在写出 HTML 前执行内联样式、禁用标签与 `span leaf` 校验；`publish` 会再次校验，避免未经验证的文件进入草稿箱。
