import sys

from earlydata_weekly_publisher.articles import write_articles
from earlydata_weekly_publisher.cli import main
from earlydata_weekly_publisher.locking import report_lock
from earlydata_weekly_publisher.models import Article


def _build_argv(tmp_path):
    source = tmp_path / "articles.json"
    write_articles(
        source,
        [
            Article(
                title="FDA 更新 AI 药物审评要求",
                source="来源",
                published_at="2026-05-30",
                content="监管机构要求补充模型验证材料。",
            )
        ],
    )
    output_dir = tmp_path / "out"
    argv = [
        "earlydata-weekly",
        "build",
        "--start",
        "2026-05-25",
        "--end",
        "2026-05-31",
        "--input",
        str(source),
        "--output-dir",
        str(output_dir),
        "--generator",
        "rules",
        "--no-ranking-cache",
        "--no-history",
    ]
    return argv, output_dir


def test_build_reports_a_held_report_lock(tmp_path, monkeypatch, capsys):
    argv, output_dir = _build_argv(tmp_path)
    output_dir.mkdir()
    lock = report_lock(output_dir, description="build")
    lock.acquire()
    try:
        monkeypatch.setattr(sys, "argv", argv)
        code = main()
    finally:
        lock.release()

    captured = capsys.readouterr()
    assert code == 2
    assert "another build is already running" in captured.err
    assert not (output_dir / "brief.json").exists()


def test_build_runs_normally_after_the_lock_is_released(tmp_path, monkeypatch):
    argv, output_dir = _build_argv(tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    assert main() == 0
    assert (output_dir / "brief.json").is_file()
    assert not (output_dir / ".earlydata.lock").exists()
