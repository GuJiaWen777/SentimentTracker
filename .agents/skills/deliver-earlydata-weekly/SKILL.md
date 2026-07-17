---
name: deliver-earlydata-weekly
description: >-
  Guide an EarlyData biopharma weekly report from a natural-language date request through source selection,
  artifact reuse, LLM ranking and synthesis, editorial review, approval, and WeChat draft publishing. Use when
  the user asks to generate or continue a weekly report, choose RedFox or Excel data, reuse an existing report,
  open or continue 审核, regenerate the WeChat HTML, check delivery status, or publish to 微信公众号草稿箱.
---

# EarlyData 周报引导交付

Operate the project as a resumable conversation:

```text
确认窗口 → 检查已有状态 → 选择或复用来源 → LLM 生成 → 人工审核 → 确认发布 → 草稿箱
```

Keep deterministic work in `earlydata-weekly`; use conversation only for decisions that require the user.

## Conversation rules

1. Ask one blocking question at a time. Use a guided-choice tool when available; otherwise ask concise natural language.
2. Recommend reuse whenever compatible artifacts already exist. Never fetch or rerun the LLM merely because the user started a new conversation.
3. Confirm the date window before acquisition or generation.
4. Treat editorial approval and WeChat publishing consent as separate gates.
5. Never publish automatically after generation or approval. Never trigger group sending.
6. Do not expose `.env` values, API keys, app secrets, prompts containing credentials, or complete provider error bodies.

## Start every request

Locate the repository root by finding `pyproject.toml` with project name `earlydata-weekly-publisher`. Run commands from that root.

Normalize the requested window to inclusive `YYYY-MM-DD` dates and derive:

```text
window_slug = YYYYMMDD_YYYYMMDD
report_dir  = data/reports/{window_slug}
```

If either date is missing or ambiguous, ask for the missing date before running the workflow. If both are clear, restate them briefly and inspect state:

```powershell
earlydata-weekly status --start {start} --end {end}
```

Without `--report-dir`, `status` compares directories matching `{window_slug}*` and selects the most advanced valid state. If the user gives a specific report directory, add `--report-dir "{path}"` and honor it.

Do not ask for a source until after reading `stage`, `next_action`, `reuse`, `gates`, and `issues`. Follow [references/state-machine.md](references/state-machine.md) when the state is unclear or inconsistent.

## Guide the next decision

### `empty`

Ask the user to choose a source:

- **RedFox API**: fetch online for the confirmed window.
- **Local P&B Excel**: use an existing `.xlsx` and filter it to the window.

Recommend a source only when evidence supports it. Prefer an already discovered matching Excel file; otherwise recommend RedFox when `REDFOX_API_KEY` is configured. Do not reveal whether a secret is present beyond “configured / not configured”.

For RedFox, obtain at least one account name before fetching. For Excel, discover likely `.xlsx` files under `data/` and present the best matching path; ask only if no unique match exists.

### `articles_ready`

Say how many articles were found and recommend reusing them. Ask whether to:

- continue LLM generation with existing articles; or
- reacquire data intentionally.

Default to reuse when the user says “继续”, “按现有数据”, “不用重拉”, or equivalent.

### `ready_for_review`

Do not ask for a source and do not rerun the LLM. Open the review workbench.

### `review_in_progress`

Continue from `brief.reviewed.json`. Do not overwrite it with `brief.json` or rerun generation unless the user explicitly requests a new model draft.

### `approved`

Report that the reviewed brief and HTML hashes are valid. Ask whether to publish this approved version to the WeChat draft box or reopen review.

### `published`

Show the existing receipt and stop. Only offer a new draft when the user explicitly requests another draft; use `--force-new-draft` after confirmation.

## Acquire only when needed

Create or reuse `{report_dir}`.

RedFox:

```powershell
earlydata-weekly fetch `
  --start {start} --end {end} `
  --account "{account}" `
  --output "{report_dir}/articles.json"
```

Repeat `--account` for multiple accounts.

P&B Excel:

```powershell
earlydata-weekly ingest-xlsx `
  --start {start} --end {end} `
  --xlsx "{xlsx_path}" `
  --output "{report_dir}/articles.json"
```

After acquisition, rerun `status`. Require `stage=articles_ready` and a nonzero `source_count` before generation.

## Generate with LLM semantics

Use the full LLM path by default. Do not switch to rules silently.

```powershell
earlydata-weekly build `
  --start {start} --end {end} `
  --input "{report_dir}/articles.json" `
  --output-dir "{report_dir}"
```

Use `--llm-backend api|claude|codex` only when the user selected a backend or the configured default is unavailable. If an LLM call fails, preserve existing artifacts, explain the error category, and offer retry or another configured LLM Adapter. Do not disguise failure with `--generator rules`.

After generation, rerun `status`. Require `ready_for_review` before opening the workbench.

## Review and approve

Start the workbench:

```powershell
earlydata-weekly review --report-dir "{report_dir}"
```

Keep the local server running and give the user its URL. The user can edit, lock fields, inspect ranking evidence, resolve quality findings, save, and click **确认发布稿**.

Wait for the user to say review is complete. Then rerun `status`:

- `review_in_progress`: explain that the report is saved but not approved; do not publish.
- `approved`: summarize the title, source count, quality issues, and reviewed HTML path.
- Any blocking quality error: keep the workflow in review.

To regenerate HTML after a direct JSON edit without invoking the LLM:

```powershell
earlydata-weekly render --input "{report_dir}/brief.reviewed.json" --output-dir "{report_dir}/reviewed"
```

Direct edits invalidate approval. Reopen the workbench and approve again.

## Confirm and publish

Publishing consent must identify the approved window and title. Ask:

```text
已确认发布稿：{title}
窗口：{start} 至 {end}
将写入微信公众号草稿箱，不会群发。是否确认发布？
```

Only after an explicit “确认发布”, “发布”, “可以发”, or equivalent, run:

```powershell
earlydata-weekly publish --report-dir "{report_dir}" --confirm
```

The command validates approval hashes and writes `publication_receipt.json`. If the same HTML already has a receipt, report the existing `media_id`; do not create a duplicate draft. Use `--force-new-draft` only after the user explicitly asks for another draft.

## Finish the conversation

Report only the useful delivery state:

- confirmed window and source used;
- reused versus newly generated artifacts;
- article count and LLM model;
- review and approval status;
- reviewed HTML path and local workbench URL;
- publication status and `media_id`, when published;
- any skipped step or unresolved issue.

Never claim a draft was created without a successful receipt.
