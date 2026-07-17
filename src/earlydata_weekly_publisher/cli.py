from __future__ import annotations

import argparse
import json
from pathlib import Path

from .pipeline import (
    DEFAULT_COVER,
    fetch_redfox,
    generate_brief,
    ingest_pb_xlsx,
    load_dotenv,
    parse_day,
    publish_draft,
    read_articles,
    read_brief,
    window_slug,
    write_articles,
    write_brief_outputs,
    write_rendered_outputs,
)


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

    run = commands.add_parser("run", help="Acquire then build locally; never publishes.")
    _window_args(run)
    run.add_argument("--source", choices=("redfox", "xlsx"), required=True)
    run.add_argument("--account", action="append", default=[])
    run.add_argument("--xlsx", help="Required for --source xlsx.")
    run.add_argument("--no-content", action="store_true")
    run.add_argument("--output-dir", default=None)
    run.add_argument("--title", default=None)
    _generator_args(run)

    render = commands.add_parser("render", help="Render an edited brief.json without calling the LLM.")
    render.add_argument("--input", required=True, help="Reviewed brief.json path.")
    render.add_argument("--output-dir", default=None, help="Default: directory containing brief.json.")

    review = commands.add_parser("review", help="Open the local editorial review workbench.")
    review.add_argument("--report-dir", required=True, help="Directory containing brief.json and generated HTML.")
    review.add_argument("--host", default="127.0.0.1")
    review.add_argument("--port", type=int, default=8765)
    review.add_argument("--no-browser", action="store_true")

    status = commands.add_parser("status", help="Inspect reusable artifacts and recommend the next workflow step.")
    status.add_argument("--report-dir", default=None, help="Report directory; otherwise derived from --start/--end.")
    status.add_argument("--start", default=None, help="YYYY-MM-DD")
    status.add_argument("--end", default=None, help="YYYY-MM-DD")

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
    publish.add_argument("--force-new-draft", action="store_true", help="Create another draft even when this approved version has a receipt.")

    args = parser.parse_args()
    load_dotenv(Path(args.env_root))
    if args.command == "fetch":
        articles = fetch_redfox(parse_day(args.start), parse_day(args.end), args.account, include_content=not args.no_content)
        write_articles(Path(args.output), articles)
        print(f"Fetched {len(articles)} articles -> {args.output}")
        return 0
    if args.command == "ingest-xlsx":
        articles = ingest_pb_xlsx(Path(args.xlsx), parse_day(args.start), parse_day(args.end))
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

        serve_review_workbench(Path(args.report_dir), host=args.host, port=args.port, open_browser=not args.no_browser)
        return 0
    if args.command == "status":
        from .workflow_status import inspect_workflow_status

        if bool(args.start) != bool(args.end):
            parser.error("status requires both --start and --end when either is supplied.")
        start = parse_day(args.start) if args.start else None
        end = parse_day(args.end) if args.end else None
        if not args.report_dir and not (start and end):
            parser.error("status requires --report-dir or both --start and --end.")
        report_dir = Path(args.report_dir) if args.report_dir else Path("data/reports") / window_slug(start, end)
        print(json.dumps(inspect_workflow_status(report_dir, start=start, end=end), ensure_ascii=False, indent=2))
        return 0
    if not args.confirm:
        parser.error("publish requires --confirm; this writes to the WeChat draft box.")
    artifact = None
    if args.report_dir:
        from .approval import load_approved_artifact, matching_publication_receipt, write_publication_receipt

        artifact = load_approved_artifact(Path(args.report_dir))
        receipt = matching_publication_receipt(artifact)
        if receipt and not args.force_new_draft:
            print(json.dumps({**receipt, "status": "draft_already_created"}, ensure_ascii=False))
            return 0
        html_path = artifact.html_path
        title = args.title or artifact.title
    else:
        if not args.allow_unreviewed:
            parser.error("publish --file requires --allow-unreviewed; prefer --report-dir for reviewed publishing.")
        if not args.title:
            parser.error("publish --file requires --title.")
        html_path = Path(args.file)
        title = args.title
    author = args.author or __import__("os").environ.get("WECHAT_AUTHOR", "EARLY DATA")
    media_id = publish_draft(html_path, title=title, cover=args.cover, author=author, digest=args.digest, source_url=args.source_url)
    if artifact is not None:
        write_publication_receipt(artifact, media_id=media_id, title=title)
    print(json.dumps({"media_id": media_id, "status": "draft_created"}, ensure_ascii=False))
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


def _build(args: argparse.Namespace) -> int:
    start, end = parse_day(args.start), parse_day(args.end)
    output_dir = Path(args.output_dir or Path("data/reports") / window_slug(start, end))
    articles = read_articles(Path(args.input))
    write_articles(output_dir / "articles.json", articles)
    brief = generate_brief(
        articles,
        start,
        end,
        args.title,
        generator=args.generator,
        llm_backend=args.llm_backend,
    )
    outputs = write_brief_outputs(brief, output_dir)
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False))
    return 0


def _run(args: argparse.Namespace) -> int:
    start, end = parse_day(args.start), parse_day(args.end)
    output_dir = Path(args.output_dir or Path("data/reports") / window_slug(start, end))
    raw_path = output_dir / "articles.json"
    if args.source == "redfox":
        articles = fetch_redfox(start, end, args.account, include_content=not args.no_content)
    else:
        if not args.xlsx:
            raise ValueError("--xlsx is required when --source xlsx.")
        articles = ingest_pb_xlsx(Path(args.xlsx), start, end)
    write_articles(raw_path, articles)
    brief = generate_brief(
        articles,
        start,
        end,
        args.title,
        generator=args.generator,
        llm_backend=args.llm_backend,
    )
    outputs = write_brief_outputs(brief, output_dir)
    print(json.dumps({"articles": str(raw_path), **{key: str(value) for key, value in outputs.items()}}, ensure_ascii=False))
    return 0


def _render(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_dir = Path(args.output_dir) if args.output_dir else input_path.parent
    outputs = write_rendered_outputs(read_brief(input_path), output_dir)
    print(json.dumps({key: str(value) for key, value in outputs.items()}, ensure_ascii=False))
    return 0
