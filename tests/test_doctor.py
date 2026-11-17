import json
import socket

from earlydata_weekly_publisher.doctor import format_doctor, run_doctor


SECRET = "super-secret-value"
KEYS = (
    "REDFOX_API_KEY",
    "LLM_BACKEND",
    "LLM_API_KEY",
    "LLM_API_MODEL",
    "LLM_API_BASE_URL",
    "WECHAT_APP_ID",
    "WECHAT_APP_SECRET",
    "EARLYDATA_RANKING_CACHE",
    "EARLYDATA_HISTORY_DB",
)


def _isolate(monkeypatch, tmp_path):
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EARLYDATA_RANKING_CACHE", str(tmp_path / "cache" / "ranking.json"))
    monkeypatch.setenv("EARLYDATA_HISTORY_DB", str(tmp_path / "history" / "signals.sqlite3"))


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _checks(report):
    return {check["name"]: check for check in report["checks"]}


def test_doctor_reports_missing_llm_model_without_leaking_secrets(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("LLM_API_KEY", SECRET)

    report = run_doctor(tmp_path, review_port=_free_port())

    assert report["ok"] is False
    assert SECRET not in json.dumps(report, ensure_ascii=False)
    llm = _checks(report)["llm_api"]
    assert llm["status"] == "error"
    assert "LLM_API_MODEL" in llm["detail"]


def test_doctor_passes_with_a_complete_local_configuration(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_BACKEND", "api")
    monkeypatch.setenv("LLM_API_KEY", SECRET)
    monkeypatch.setenv("LLM_API_MODEL", "test-model")
    monkeypatch.setenv("REDFOX_API_KEY", "redfox-key")
    monkeypatch.setenv("WECHAT_APP_ID", "wx1234567890")
    monkeypatch.setenv("WECHAT_APP_SECRET", "a" * 20)

    report = run_doctor(tmp_path, review_port=_free_port())

    assert report["ok"] is True
    assert report["summary"]["error"] == 0
    assert _checks(report)["llm_api"]["status"] == "ok"
    assert _checks(report)["wechat"]["status"] == "ok"
    assert SECRET not in json.dumps(report, ensure_ascii=False)


def test_doctor_flags_a_corrupt_history_database(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    broken = tmp_path / "history" / "signals.sqlite3"
    broken.parent.mkdir(parents=True)
    broken.write_text("not a sqlite database", encoding="utf-8")

    report = run_doctor(tmp_path, review_port=_free_port())

    history = _checks(report)["history_db"]
    assert history["status"] == "error"
    assert "unreadable" in history["detail"]


def test_doctor_text_output_labels_every_check(tmp_path, monkeypatch):
    _isolate(monkeypatch, tmp_path)
    report = run_doctor(tmp_path, review_port=_free_port())

    text = format_doctor(report)

    assert "环境检查" in text
    for check in report["checks"]:
        assert check["name"] in text
