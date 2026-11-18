from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Callable

from .articles import (
    filter_articles_by_window,
    parse_day,
    read_articles,
    validate_window,
    window_slug,
    write_articles,
)
from .brief import generate_brief, read_brief, write_brief_outputs, write_rendered_outputs
from .config import load_dotenv
from .locking import LockError, report_lock
from .models import ensure_article_ids
from .render import DEFAULT_COVER
from .sources import SourceRequest, get_source, source_names
from .wechat import publish_draft
from .ranking_cache import DEFAULT_RANKING_CACHE
from .run_manifest import RunManifest
from .signal_history import default_history_db, record_report, trend_summary


def main() -> int:
    parser = argparse.ArgumentParser(description="EarlyData weekly WeChat publishing pipeline")
    parser.add_argument("--env-root", default=".", help="Directory containing .env (default: current directory).")
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="Fetch articles from RedFox API.")
    _window_args(fetch)
    fetch.add_argument("--account", action="append", default=[], help="WeChat account name; repeatable.")
    fetch.add_argument("--no-content", action="store_true", help="Skip RedFox detail API calls.")
    fetch.add_argument("--output", required=True, help="Output articles.json path.")

    ingest = commands.add_parser("ingest-xlsx", help="Read P&B-format Excel into articles.json.")
    _window_args(ingest)
    ingest.add_argument("--xlsx", required=True, help="P&B Excel file.")
    ingest.add_argument("--output", required=True, help="Output articles.json path.")

    build = commands.add_parser("build", help="Generate LLM-ranked brief.json, Markdown, and compliant HTML.")
    _window_args(build)
    build.add_argument("--input", required=True, help="Input articles.json.")
    build.add_argument("--output-dir", default=None, help="Default: data/reports/YYYYMMDD_YYYYMMDD.")
    build.add_argument("--title", default=None, help="Optional article title override.")
    _generator_args(build)
    _context_args(build)

    run = commands.add_parser("run", help="Acquire then build locally; never publishes.")
    _window_args(run)
    run.add_argument("--source", choices=source_names(), required=True)
    run.add_argument("--account", action="append", default=[])
    run.add_argument("--xlsx", help="Required for --source xlsx.")
    run.add_argument("--no-content", action="store_true")
    run.add_argument("--output-dir", default=None)
    run.add_argument("--title", default=None)
    _generator_args(run)
    _context_args(run)

    render = commands.add_parser("render", help="Render an edited brief.json without calling the LLM.")
    render.add_argument("--input", required=True, help="Reviewed brief.json path.")
    render.add_argument("--output-dir", default=None, help="Default: directory containing brief.json.")

    review = commands.add_parser("review", help="Open the local editorial review workbench.")
    review.add_argument("--report-dir", required=True, help="Directory containing brief.json and generated HTML.")
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=8765)
    review.add_argument("--no-browser", action="store_true")
    review.add_argument("--history-db", default=None, help="Signal history SQLite path for the trend panel.")
    review.add_argument("--no-history", action="store_true")

    status = commands.add_parser("status", help="Inspect reusable artifacts and recommend the next workflow step.")
    status.add_argument("--report-dir", default=None, help="Report directory; otherwise derived from --start/--end.")
    status.add_argument("--start", default=None, help="YYYY-MM-DD")
    status.add_argument("--end", default=None, help="YYYY-MM-DD")

    doctor = commands.add_parser("doctor", help="Check local configuration, credentials, and data files.")
    doctor.add_argument("--format", choices=("json", "text"), default="json")
    doctor.add_argument("--review-port", type=int, default=8765)

    history = commands.add_parser("history", help="Record reports and inspect cross-week signal trends.")
    history_commands = history.add_subparsers(dest="history_command", required=True)
    history_record = history_commands.add_parser("record", help="Record one report's signals into the history database.")
    history_record.add_argument("--report-dir", required=True)
    history_record.add_argument("--history-db", default=None)
    history_report = history_commands.add_parser("report", help="Show signal counts and entity streaks across recent reports.")
    history_report.add_argument("--history-db", default=None)
    history_report.add_argument("--end", default=None, help="Inclusive YYYY-MM-DD upper bound.")
    history_report.add_argument("--weeks", type=int, default=8)
    history_report.add_argument("--format", choices=("json", "text"), default="json")

    publish = commands.add_parser("publish", help="Upload confirmed HTML to the WeChat draft box.")
    publish_input = publish.add_mutually_exclusive_group(required=True)
    publish_input.add_argument("--report-dir", help="Approved report directory from the review workbench.")
    publish_input.add_argument("--file", help="Validated HTML path for explicit legacy publishing.")
    publish.add_argument("--title", default=None, help="Defaults to the approved brief title with --report-dir.")
    publish.add_argument("--cover", default=DEFAULT_COVER)
    publish.add_argument("--author", default=None)
    publish.add_argument("--digest", default="")
    publish.add_argument("--source-url", default="")
    publish.add_argument("--confirm", action="store_true", help="Required acknowledgement before draft creation.")
    publish.add_argument("--allow-unreviewed", action="store_true", help="Required with --file to bypass the review gate.")
    draft_mode = publish.add_mutually_exclusive_group()
    draft_mode.add_argument("--force-new-draft", action="store_true", help="Create another draft even when this approved version has a receipt.")
    draft_mode.add_argument("--update-draft", action="store_true", help="Update the existing receipt draft after re-approval.")

    args = parser.parse_args()
    load_dotenv(Path(args.env_root))
    if args.command == "fetch":
        articles = get_source("redfox").fetch(
            SourceRequest(
                start=parse_day(args.start),
                end=parse_day(args.end),
                accounts=tuple(args.account),
                include_content=not args.no_content,
            )
        )
        write_articles(Path(args.output), articles)
        print(f"Fetched {len(articles)} articles -> {args.output}")
        return 0
    if args.command == "ingest-xlsx":
        articles = get_source("xlsx").fetch(
            SourceRequest(
                start=parse_day(args.start),
                end=parse_day(args.end),
                path=Path(args.xlsx),
            )
        )
        write_articles(Path(args.output), articles)
        print(f"Ingested {len(articles)} articles -> {args.output}")
        return 0
    if args.command == "build":
        return _build(args)
    if args.command == "run":
        return _run(args)
    if args.command == "render":
        return _render(args)
    if args.command == "review":
        from .review_app import serve_review_workbench

        history_db = None if args.no_history else (Path(args.history_db) if args.history_db else default_history_db())
        serve_review_workbench(
            Path(args.report_dir),
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
            history_db=history_db,
        )
        return 0
    if args.command == "history":
        return _history(args)
    if args.command == "doctor":
        from .doctor import format_doctor, run_doctor

        report = run_doctor(Path(args.env_root), review_port=args.review_port)
        if args.format == "text":
            print(format_doctor(report))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["ok"] else 1
    if args.command == "status":
        from .workflow_status import discover_report_dir, inspect_workflow_status

        if bool(args.start) != bool(args.end):
            parser.error("status requires both --start and --end when either is supplied.")
        start = parse_day(args.start) if args.start else None
        end = parse_day(args.end) if args.end else None
        if not args.report_dir and not (start and end):
            parser.error("status requires --report-dir or both --start and --end.")
        if start and end:
            validate_window(start, end)
        report_dir = Path(args.report_dir) if args.report_dir else discover_report_dir(Path("data/reports"), start=start, end=end)
        print(json.dumps(inspect_workflow_status(report_dir, start=start, end=end), ensure_ascii=False, indent=2))
        return 0
    if not args.confirm:
        parser.error("publish requires --confirm; this writes to the WeChat draft box.")
    artifact = None
    update_media_id: str | None = None
    if args.report_dir:
        from .approval import (
            load_approved_artifact,
            matching_publication_receipt,
            read_publication_receipt,
            write_publication_receipt,
        )

        artifact = load_approved_artifact(Path(args.report_dir))
        receipt = matching_publication_receipt(artifact)
        if receipt and not args.force_new_draft:
            print(json.dumps({**receipt, "status": "draft_already_created"}, ensure_ascii=False))
            return 0
        if args.update_draft:
            previous = read_publication_receipt(artifact.report_dir)
            update_media_id = str(previous.get("media_id") or "")
            if not update_media_id:
                parser.error("--update-draft requires an existing publication_receipt.json.")
        html_path = artifact.html_path
        title = args.title or artifact.title
    else:
        if args.update_draft:
            parser.error("--update-draft requires --report-dir.")
        if not args.allow_unreviewed:
            parser.error("publish --file requires --allow-unreviewed; prefer --report-dir for reviewed publishing.")
        if not args.title:
            parser.error("publish --file requires --title.")
        html_path = Path(args.file)
        title = args.title
    author = args.author or os.environ.get("WECHAT_AUTHOR", "EARLY DATA")
    media_id = publish_draft(
        html_path,
        title=title,
        cover=args.cover,
        author=author,
        digest=args.digest,
        source_url=args.source_url,
        update_media_id=update_media_id,
    )
    if artifact is not None:
        write_publication_receipt(artifact, media_id=media_id, title=title, updated=bool(update_media_id))
    print(
        json.dumps(
            {"media_id": media_id, "status": "draft_updated" if update_media_id else "draft_created"},
            ensure_ascii=False,
        )
    )
    return 0


def _window_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--start", required=True, help="YYYY-MM-DD")
    command.add_argument("--end", required=True, help="YYYY-MM-DD")


def _generator_args(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--generator",
        choices=("llm", "rules"),
        default="llm",
        help="Content generator. Default: llm; rules is an explicit offline fallback.",
    )
    command.add_argument(
        "--llm-backend",
        choices=("api", "claude", "codex"),
        default=None,
        help="LLM transport. Default: LLM_BACKEND or api.",
    )


def _context_args(command: argparse.ArgumentParser) -> None:
    command.add_argument("--ranking-cache", default=None, help="Ranking cache path. Default: data/cache/ranking.json.")
    command.add_argument("--no-ranking-cache", action="store_true", help="Disable ranking cache reads and writes.")
    command.add_argument("--history-db", default=None, help="Signal history SQLite path. Default: data/history/signals.sqlite3.")
    command.add_argument("--no-history", action="store_true", help="Do not read or write signal history.")


def _cache_path(args: argparse.Namespace) -> Path | None:
    if args.no_ranking_cache:
        return None
    return Path(args.ranking_cache or os.environ.get("EARLYDATA_RANKING_CACHE") or DEFAULT_RANKING_CACHE)


def _history_path(args: argparse.Namespace) -> Path | None:
    if args.no_history:
        return None
    return Path(args.history_db) if args.history_db else default_history_db()


def _with_report_lock(output_dir: Path, description: str, action: Callable[[], int]) -> int:
    lock = report_lock(output_dir, description=description)
    try:
        lock.acquire()
    except LockError as exc:
        print(f"[lock] {exc}", file=sys.stderr)
        return 2
    try:
        return action()
    finally:
        lock.release()


def _build(args: argparse.Namespace) -> int:
    start, end = parse_day(args.start), parse_day(args.end)
    validate_window(start, end)
    output_dir = Path(args.output_dir or Path("data/reports") / window_slug(start, end))
    return _with_report_lock(output_dir, "build", lambda: _build_locked(args, start, end, output_dir))


def _build_locked(args: argparse.Namespace, start: date, end: date, output_dir: Path) -> int:
    cache_path, history_path = _cache_path(args), _history_path(args)
    with RunManifest(output_dir, command="build", start=start, end=end) as manifest:
        manifest.set("input", str(Path(args.input)))
        manifest.set("cache", {"enabled": cache_path is not None and args.generator == "llm", "path": str(cache_path) if cache_path else ""})
        manifest.set("history", {"enabled": history_path is not None, "path": str(history_path) if history_path else ""})
        articles = ensure_article_ids(read_articles(Path(args.input)))
        in_window, excluded = filter_articles_by_window(articles, start, end)
        if not in_window:
            raise ValueError(f"No articles in {args.input} fall inside {start.isoformat()}..{end.isoformat()}.")
        if excluded:
            print(f"[window] excluded {excluded} articles outside {start.isoformat()}..{end.isoformat()}", file=sys.stderr, flush=True)
        manifest.set("counts", {"in_window_count": len(in_window)})
        # Keep the full source snapshot (now with stable IDs); generation filters it.
        write_articles(output_dir / "articles.json", articles)
        brief = generate_brief(
            articles,
            start,
            end,
            args.title,
            generator=args.generator,
            llm_backend=args.llm_backend,
            ranking_cache_path=cache_path,
            history_db=history_path,
        )
        outputs = write_brief_outputs(brief, output_dir)
        manifest.record(brief, outputs)
        print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False))
    return 0


def _run(args: argparse.Namespace) -> int:
    start, end = parse_day(args.start), parse_day(args.end)
    validate_window(start, end)
    output_dir = Path(args.output_dir or Path("data/reports") / window_slug(start, end))
    return _with_report_lock(output_dir, "run", lambda: _run_locked(args, start, end, output_dir))


def _run_locked(args: argparse.Namespace, start: date, end: date, output_dir: Path) -> int:
    raw_path = output_dir / "articles.json"
    cache_path, history_path = _cache_path(args), _history_path(args)
    with RunManifest(output_dir, command="run", start=start, end=end) as manifest:
        manifest.set("cache", {"enabled": cache_path is not None and args.generator == "llm", "path": str(cache_path) if cache_path else ""})
        manifest.set("history", {"enabled": history_path is not None, "path": str(history_path) if history_path else ""})
        source = get_source(args.source)
        articles = source.fetch(
            SourceRequest(
                start=start,
                end=end,
                accounts=tuple(args.account),
                path=Path(args.xlsx) if args.xlsx else None,
                include_content=not args.no_content,
            )
        )
        acquired = len(ensure_article_ids(articles))
        articles, excluded = filter_articles_by_window(articles, start, end)
        if not articles:
            raise ValueError(f"No articles fall inside {start.isoformat()}..{end.isoformat()}.")
        if excluded:
            print(f"[window] excluded {excluded} articles outside {start.isoformat()}..{end.isoformat()}", file=sys.stderr, flush=True)
        manifest.set(
            "acquisition",
            {
                "source": source.info.name,
                "source_label": source.info.label,
                "account_count": len(args.account),
                "acquired_count": acquired,
                "excluded_outside_window": excluded,
            },
        )
        manifest.set("counts", {"in_window_count": len(articles)})
        write_articles(raw_path, articles)
        brief = generate_brief(
            articles,
            start,
            end,
            args.title,
            generator=args.generator,
            llm_backend=args.llm_backend,
            ranking_cache_path=cache_path,
            history_db=history_path,
        )
        outputs = write_brief_outputs(brief, output_dir)
        manifest.record(brief, outputs)
        print(json.dumps({"articles": str(raw_path), **{key: str(value) for key, value in outputs.items()}}, ensure_ascii=False))
    return 0


def _render(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    outputs = write_rendered_outputs(read_brief(input_path), output_dir)
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False))
    return 0


def _history(args: argparse.Namespace) -> int:
    db_path = Path(args.history_db) if args.history_db else default_history_db()
    if args.history_command == "record":
        print(json.dumps(record_report(Path(args.report_dir), db_path=db_path), ensure_ascii=False, indent=2))
        return 0
    if args.weeks < 1:
        raise ValueError("--weeks must be greater than zero.")
    until = parse_day(args.end) if args.end else None
    summary = trend_summary(db_path, until=until, weeks=args.weeks)
    if args.format == "text":
        print(_format_history(summary))
    else:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _format_history(summary: dict) -> str:
    if not summary.get("window_count"):
        return "暂无历史记录。"
    lines = [f"覆盖 {summary['window_count']} 期历史"]
    for week in summary.get("weeks", []):
        counts = " · ".join(f"{name} {count}" for name, count in (week.get("signal_counts") or {}).items()) or "无信号"
        lines.append(f"{week['window_start']}..{week['window_end']}：{counts}")
    persistent = summary.get("persistent_entities") or []
    if persistent:
        lines.append("连续出现：" + "、".join(f"{entry['name']}（{entry['streak']} 期）" for entry in persistent[:10]))
    return "\n".join(lines)
