from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
REQUEST_ATTEMPTS = 3


@dataclass(frozen=True)
class LLMConfig:
    api_key: str
    model: str
    base_url: str = DEFAULT_LLM_BASE_URL
    timeout: float = 300.0

    @classmethod
    def from_env(cls) -> "LLMConfig":
        api_key = os.environ.get("LLM_API_KEY", "").strip()
        model = os.environ.get("LLM_API_MODEL", "").strip()
        if not api_key:
            raise RuntimeError("LLM_API_KEY is required when --generator llm is used.")
        if not model:
            raise RuntimeError("LLM_API_MODEL is required when --generator llm is used.")
        try:
            timeout = float(os.environ.get("LLM_API_TIMEOUT", "300"))
        except ValueError as exc:
            raise RuntimeError("LLM_API_TIMEOUT must be a number of seconds.") from exc
        if timeout <= 0:
            raise RuntimeError("LLM_API_TIMEOUT must be greater than zero.")
        return cls(
            api_key=api_key,
            model=model,
            base_url=os.environ.get("LLM_API_BASE_URL", DEFAULT_LLM_BASE_URL).strip() or DEFAULT_LLM_BASE_URL,
            timeout=timeout,
        )


class OpenAICompatibleClient:
    backend = "api"

    def __init__(self, config: LLMConfig | None = None, *, session: Any | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self._session = session or requests.Session()
        self.usage = _new_usage()

    @property
    def model_name(self) -> str:
        return self.config.model

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        }
        response = self._post(payload)
        if response.status_code == 400:
            fallback_payload = {key: value for key, value in payload.items() if key != "response_format"}
            response = self._post(fallback_payload)
        if response.status_code >= 400:
            preview = str(getattr(response, "text", ""))[:300]
            raise RuntimeError(f"LLM API failed with HTTP {response.status_code}: {preview}")
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise RuntimeError("LLM API returned malformed JSON.") from exc
        _record_usage(self, body.get("usage") if isinstance(body, dict) else None)
        message = _assistant_message(body)
        parsed = message.get("parsed") if isinstance(message, dict) else None
        if isinstance(parsed, dict):
            return parsed
        content = _message_content(message)
        return _parse_json_object(content)

    def _post(self, payload: dict[str, Any]) -> Any:
        base = self.config.base_url.rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        last_error: Exception | None = None
        for attempt in range(REQUEST_ATTEMPTS):
            try:
                response = self._session.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.config.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt < REQUEST_ATTEMPTS - 1:
                    time.sleep(min(8.0, 0.5 * 2**attempt))
                    continue
                raise RuntimeError(f"LLM API request failed: {exc}") from exc
            if getattr(response, "status_code", 0) in RETRYABLE_HTTP_STATUS and attempt < REQUEST_ATTEMPTS - 1:
                time.sleep(min(8.0, 0.5 * 2**attempt))
                continue
            return response
        raise RuntimeError(f"LLM API request failed: {last_error}") from last_error


class ClaudeCLIClient:
    backend = "claude"

    def __init__(
        self,
        *,
        executable: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        runner: Any = subprocess.run,
    ) -> None:
        self._executable = executable or shutil.which("claude") or shutil.which("claude.cmd") or ""
        if not self._executable:
            raise RuntimeError("Claude CLI is not installed or not available on PATH.")
        self._model = (model if model is not None else os.environ.get("LLM_CLAUDE_MODEL") or os.environ.get("ANTHROPIC_MODEL") or "").strip()
        try:
            self._timeout = float(timeout if timeout is not None else os.environ.get("LLM_CLAUDE_TIMEOUT", "300"))
        except ValueError as exc:
            raise RuntimeError("LLM_CLAUDE_TIMEOUT must be a number of seconds.") from exc
        if self._timeout <= 0:
            raise RuntimeError("LLM_CLAUDE_TIMEOUT must be greater than zero.")
        self._runner = runner
        self.usage = _new_usage()

    @property
    def model_name(self) -> str:
        return self._model or "claude-cli-default"

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        command = [
            self._executable,
            "-p",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--safe-mode",
            "--tools",
            "",
            "--system-prompt",
            system_prompt,
            "--json-schema",
            json.dumps(schema, ensure_ascii=False, separators=(",", ":")),
        ]
        if self._model:
            command.extend(["--model", self._model])
        try:
            completed = self._runner(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                encoding="utf-8",
                timeout=self._timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError(f"Claude CLI request failed: {exc}") from exc
        if completed.returncode != 0:
            preview = str(completed.stderr or completed.stdout or "")[:500]
            raise RuntimeError(f"Claude CLI failed with exit code {completed.returncode}: {preview}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Claude CLI returned malformed JSON.") from exc
        if isinstance(payload, dict):
            _record_usage(self, payload.get("usage"), cost=payload.get("total_cost_usd"))
        structured = payload.get("structured_output") if isinstance(payload, dict) else None
        if isinstance(structured, dict):
            return structured
        result = payload.get("result") if isinstance(payload, dict) else None
        if isinstance(result, dict):
            return result
        if isinstance(result, str) and result.strip():
            return _parse_json_object(result)
        raise RuntimeError("Claude CLI returned no structured output.")


class CodexCLIClient:
    backend = "codex"

    def __init__(
        self,
        *,
        executable: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        runner: Any = subprocess.run,
    ) -> None:
        self._executable = executable or shutil.which("codex") or shutil.which("codex.exe") or ""
        if not self._executable:
            raise RuntimeError("Codex CLI is not installed or not available on PATH.")
        self._model = (model if model is not None else os.environ.get("LLM_CODEX_MODEL") or "").strip()
        try:
            self._timeout = float(timeout if timeout is not None else os.environ.get("LLM_CODEX_TIMEOUT", "600"))
        except ValueError as exc:
            raise RuntimeError("LLM_CODEX_TIMEOUT must be a number of seconds.") from exc
        if self._timeout <= 0:
            raise RuntimeError("LLM_CODEX_TIMEOUT must be greater than zero.")
        self._runner = runner
        self.usage = _new_usage()

    @property
    def model_name(self) -> str:
        return self._model or "codex-cli-default"

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        del schema_name
        with tempfile.TemporaryDirectory(prefix="earlydata-codex-") as temp_dir:
            root = Path(temp_dir)
            schema_path = root / "schema.json"
            output_path = root / "result.json"
            schema_path.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
            command = [
                self._executable,
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--ignore-rules",
                "--sandbox",
                "read-only",
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ]
            if self._model:
                command[2:2] = ["--model", self._model]
            full_prompt = f"{system_prompt.strip()}\n\n---\n\n{prompt.strip()}"
            try:
                completed = self._runner(
                    command,
                    input=full_prompt,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    timeout=self._timeout,
                    check=False,
                    cwd=temp_dir,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise RuntimeError(f"Codex CLI request failed: {exc}") from exc
            if completed.returncode != 0:
                preview = str(completed.stderr or completed.stdout or "")[-800:]
                raise RuntimeError(f"Codex CLI failed with exit code {completed.returncode}: {preview}")
            if not output_path.is_file():
                raise RuntimeError("Codex CLI did not write its final structured response.")
            _record_usage(self)
            return _parse_json_object(output_path.read_text(encoding="utf-8"))


def create_llm_client(backend: str | None = None) -> Any:
    name = str(backend or os.environ.get("LLM_BACKEND") or "api").strip().lower()
    if name == "api":
        return OpenAICompatibleClient()
    if name == "claude":
        return ClaudeCLIClient()
    if name == "codex":
        return CodexCLIClient()
    raise ValueError("LLM backend must be 'api', 'claude', or 'codex'.")


def _assistant_message(body: Any) -> dict[str, Any]:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("LLM API response is missing choices[0].message.") from exc
    if not isinstance(message, dict):
        raise RuntimeError("LLM API assistant message must be an object.")
    return message


def _message_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    if isinstance(content, list):
        parts = [str(item.get("text") or "").strip() for item in content if isinstance(item, dict)]
        text = "\n".join(part for part in parts if part)
        if text:
            return text
    raise RuntimeError("LLM API assistant message has no text content.")


def _new_usage() -> dict[str, float | int]:
    return {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }


def _record_usage(client: Any, usage: Any = None, *, cost: Any = None) -> None:
    """Accumulate provider usage on the client for the run manifest."""
    target = getattr(client, "usage", None)
    if not isinstance(target, dict):
        target = _new_usage()
        setattr(client, "usage", target)
    target["calls"] = int(target.get("calls", 0)) + 1
    if isinstance(usage, dict):
        prompt = _as_int(usage.get("prompt_tokens", usage.get("input_tokens")))
        completion = _as_int(usage.get("completion_tokens", usage.get("output_tokens")))
        total = _as_int(usage.get("total_tokens")) or prompt + completion
        target["prompt_tokens"] = int(target.get("prompt_tokens", 0)) + prompt
        target["completion_tokens"] = int(target.get("completion_tokens", 0)) + completion
        target["total_tokens"] = int(target.get("total_tokens", 0)) + total
    amount = _as_float(cost)
    if amount:
        target["cost_usd"] = round(float(target.get("cost_usd", 0.0)) + amount, 6)


def _as_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    if isinstance(value, bool):
        return 0.0
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise RuntimeError("LLM response does not contain a JSON object.")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise RuntimeError("LLM response is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise RuntimeError("LLM response must be a JSON object.")
    return value
