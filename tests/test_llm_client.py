import json

import pytest

from pathlib import Path

from earlydata_weekly_publisher.llm_client import ClaudeCLIClient, CodexCLIClient, LLMConfig, OpenAICompatibleClient


class FakeResponse:
    def __init__(self, status_code, payload, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_llm_config_requires_key_and_model(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_MODEL", raising=False)

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        LLMConfig.from_env()

    monkeypatch.setenv("LLM_API_KEY", "test-key")
    with pytest.raises(RuntimeError, match="LLM_API_MODEL"):
        LLMConfig.from_env()


def test_client_retries_without_schema_when_provider_rejects_it():
    session = FakeSession(
        [
            FakeResponse(400, {"error": "unsupported"}, "response_format unsupported"),
            FakeResponse(
                200,
                {"choices": [{"message": {"content": json.dumps({"ok": True})}}]},
            ),
        ]
    )
    client = OpenAICompatibleClient(
        LLMConfig(api_key="secret", model="test-model", base_url="https://llm.example/v1", timeout=12),
        session=session,
    )

    result = client.complete_json(
        system_prompt="system",
        prompt="prompt",
        schema_name="test_output",
        schema={"type": "object"},
    )

    assert result == {"ok": True}
    assert len(session.calls) == 2
    first_url, first = session.calls[0]
    _second_url, second = session.calls[1]
    assert first_url == "https://llm.example/v1/chat/completions"
    assert first["headers"]["Authorization"] == "Bearer secret"
    assert first["json"]["model"] == "test-model"
    assert first["json"]["response_format"]["type"] == "json_schema"
    assert "response_format" not in second["json"]


def test_claude_cli_client_returns_structured_output():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps({"structured_output": {"ok": True}}),
                "stderr": "",
            },
        )()

    client = ClaudeCLIClient(executable="claude.cmd", model="test-claude", timeout=15, runner=runner)

    result = client.complete_json(
        system_prompt="system",
        prompt="prompt",
        schema_name="test",
        schema={"type": "object"},
    )

    assert result == {"ok": True}
    command, kwargs = calls[0]
    assert "--json-schema" in command
    assert command[-2:] == ["--model", "test-claude"]
    assert kwargs["input"] == "prompt"


def test_codex_cli_client_reads_schema_validated_last_message():
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        output_path = Path(command[command.index("--output-last-message") + 1])
        output_path.write_text(json.dumps({"ok": True}), encoding="utf-8")
        return type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    client = CodexCLIClient(executable="codex.exe", model="test-codex", timeout=20, runner=runner)

    result = client.complete_json(
        system_prompt="system",
        prompt="prompt",
        schema_name="test",
        schema={"type": "object"},
    )

    assert result == {"ok": True}
    command, kwargs = calls[0]
    assert command[:4] == ["codex.exe", "exec", "--model", "test-codex"]
    assert "--output-schema" in command
    assert "system" in kwargs["input"] and "prompt" in kwargs["input"]
