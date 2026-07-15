# 运行与发布手册

## 一次完整本地生成

在项目根目录创建 `.env`，其中 `REDFOX_API_KEY` 用于 API 采集，`WECHAT_APP_ID`、`WECHAT_APP_SECRET` 和可选的 `WECHAT_AUTHOR` 用于发布。`.env` 已被 Git 忽略。

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

检查对应目录中的四个产物：

1. `articles.json`：文章数量、日期窗口和原始链接正确。
2. `brief.json`：重点信号不重复，公司/技术标签没有误识别，行动建议能由原文支持。
3. `wechat_article.md`：标题、日期和封面 URL 正确。
4. `wechat_article_img.html`：在浏览器或公众号编辑器预览中确认层级、文字换行和链接。

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
| Excel 输出为 0 篇 | 核对日期列和 `--start` / `--end`；日期范围是闭区间。 |
| HTML 校验失败 | 检查是否引入 `style`、`script`、`div`、`class` 或漏掉 `span leaf`。 |
| 微信 token / IP 白名单错误 | 在公众号后台将执行机器的公网 IP 加入白名单。 |
| 封面上传失败 | 确认 URL 可公开访问，或传入可读取的本地图片路径。 |

草稿写入后若需要撤回或删除，应在公众号后台操作；该项目不提供自动删除草稿的命令。
