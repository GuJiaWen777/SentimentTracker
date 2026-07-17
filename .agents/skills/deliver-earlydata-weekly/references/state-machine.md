# Workflow State Machine

Use `earlydata-weekly status` as the source of truth. Inspect filesystem details only to diagnose an `issues` entry.

| Stage | Reuse | User-facing decision | Next command |
| --- | --- | --- | --- |
| `empty` | None | Choose RedFox or P&B Excel | `fetch` or `ingest-xlsx` |
| `articles_ready` | `articles.json` | Reuse articles or intentionally reacquire | `build` when reusing |
| `ready_for_review` | Model brief and generated HTML | Open review | `review` |
| `review_in_progress` | Human edits and locks | Continue review; do not regenerate | `review` |
| `approved` | Hash-verified reviewed brief and HTML | Publish or reopen review | `publish --report-dir ... --confirm` after consent |
| `published` | Existing draft receipt | Stop or explicitly create another draft | No command by default |

## Reuse policy

Apply the strongest available reusable artifact:

```text
publication receipt > approved HTML > reviewed brief > generated brief > articles > no data
```

- Do not reacquire when `reuse.articles=true` unless the user asks for fresh data or the requested window differs.
- Do not rebuild when `reuse.generated_report=true` unless the user asks for a new model draft or the report window is incompatible.
- Do not overwrite `brief.reviewed.json` when `reuse.reviewed_report=true`.
- Do not republish when `gates.published=true` unless the user explicitly asks for another draft.

## Issues

Handle status issues before moving forward:

- **Window mismatch**: stop and ask whether to use the existing window or create the requested window.
- **Invalid articles**: do not generate; reacquire or repair the input.
- **Invalid brief**: do not review or publish; repair or regenerate.
- **Missing `articles.json` with a generated brief**: allow review of the existing draft, but explain that source evidence is unavailable. Offer to restore the matching source snapshot without rerunning the LLM.
- **Approval hash mismatch**: reopen review and approve again. Never bypass with legacy file publishing.

## Guided prompts

Keep prompts short and specific.

Source choice:

```text
本期尚无数据。请选择来源：RedFox 在线获取，或使用本地 P&B Excel？
```

Reuse choice:

```text
发现该窗口已有 {source_count} 篇文章。建议直接复用并进入 LLM 生成；是否继续？
```

Review handoff:

```text
模型稿已存在，无需重新生成。我已打开审核工作台；完成修改并点击“确认发布稿”后告诉我继续。
```

Publish gate:

```text
审核稿已通过哈希校验。确认写入微信公众号草稿箱吗？这不会自动群发。
```
