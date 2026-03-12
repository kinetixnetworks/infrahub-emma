"""Utilities for invoking the Claude Code CLI binary."""

import json
import shutil
import subprocess  # noqa: S404
import tempfile
from pathlib import Path
from typing import Any


class ClaudeCodeError(Exception):
    """Raised when the Claude Code CLI returns an error."""

    def __init__(self, message: str, stderr: str = ""):
        self.stderr = stderr
        super().__init__(message)


def get_claude_binary() -> str:
    """Find the claude binary on the system PATH."""
    binary = shutil.which("claude")
    if not binary:
        raise ClaudeCodeError("Claude Code CLI binary not found. Please install it first.")
    return binary


def _build_command(
    binary: str,
    system_prompt: str | None,
    session_id: str | None,
    resume: bool,
    model: str | None,
    max_budget_usd: float | None,
    allowed_tools: list[str] | None,
) -> list[str]:
    """Build the CLI command arguments."""
    cmd = [binary, "--print", "--output-format", "json"]

    if system_prompt:
        cmd.extend(["--system-prompt", system_prompt])
    if session_id and resume:
        cmd.extend(["--resume", session_id])
    elif session_id:
        cmd.extend(["--session-id", session_id])
    if model:
        cmd.extend(["--model", model])
    if max_budget_usd is not None:
        cmd.extend(["--max-budget-usd", str(max_budget_usd)])
    if allowed_tools is not None:
        cmd.extend(["--allowedTools", ",".join(allowed_tools)])
    else:
        cmd.extend(["--tools", ""])

    return cmd


def _prepare_context_prompt(prompt: str, context_files: dict[str, str] | None) -> tuple[str, str | None]:
    """Write context files to a temp dir and build the full prompt.

    Returns:
        Tuple of (full_prompt, temp_dir_path_or_None).
    """
    if not context_files:
        return prompt, None

    temp_dir = tempfile.mkdtemp(prefix="emma_claude_")
    file_refs = []
    for filename, content in context_files.items():
        file_path = Path(temp_dir) / filename
        file_path.write_text(content, encoding="utf-8")
        file_refs.append(str(file_path))

    files_section = "\n".join(f"[File: {ref}]" for ref in file_refs)
    full_prompt = f"I have provided the following files for context:\n{files_section}\n\n{prompt}"
    return full_prompt, temp_dir


def _parse_response(stdout: str, session_id: str | None) -> dict[str, Any]:
    """Parse the JSON response from the Claude Code CLI."""
    fallback_session = session_id or ""

    try:
        response = json.loads(stdout)
    except json.JSONDecodeError:
        return {"output": stdout.strip(), "session_id": fallback_session, "cost": {}}

    if isinstance(response, dict):
        return {
            "output": response.get("result", response.get("output", stdout.strip())),
            "session_id": response.get("session_id", fallback_session),
            "cost": response.get("cost_usd", response.get("cost", {})),
        }

    if isinstance(response, list):
        for msg in response:
            if isinstance(msg, dict) and msg.get("type") == "result":
                return {
                    "output": msg.get("result", ""),
                    "session_id": msg.get("session_id", fallback_session),
                    "cost": msg.get("cost_usd", {}),
                }
        return {"output": stdout.strip(), "session_id": fallback_session, "cost": {}}

    return {"output": str(response), "session_id": fallback_session, "cost": {}}


def invoke_claude(
    prompt: str,
    system_prompt: str | None = None,
    session_id: str | None = None,
    resume: bool = False,
    context_files: dict[str, str] | None = None,
    model: str | None = None,
    max_budget_usd: float | None = None,
    allowed_tools: list[str] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Invoke the Claude Code CLI and return structured output.

    Args:
        prompt: The user prompt to send.
        system_prompt: Optional system prompt to prepend.
        session_id: Optional session ID for conversation continuity.
        resume: If True, resume the session specified by session_id.
        context_files: Dict of {filename: content} to write as temp files
                       and include in the prompt as file references.
        model: Optional model override (e.g. 'sonnet', 'opus').
        max_budget_usd: Optional max spend limit.
        allowed_tools: Optional list of allowed tools (e.g. ["Read"]).
        cwd: Working directory for the claude process.

    Returns:
        Dict with keys: 'output' (str), 'session_id' (str), 'cost' (dict).
    """
    cmd = _build_command(
        binary=get_claude_binary(),
        system_prompt=system_prompt,
        session_id=session_id,
        resume=resume,
        model=model,
        max_budget_usd=max_budget_usd,
        allowed_tools=allowed_tools,
    )

    full_prompt, temp_dir = _prepare_context_prompt(prompt, context_files)
    cmd.extend(["--no-session-persistence", "-p", full_prompt])

    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=cwd or str(Path.cwd()),
        )
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCodeError("Claude Code CLI timed out after 5 minutes.") from exc
    finally:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

    if result.returncode != 0:
        raise ClaudeCodeError(
            f"Claude Code CLI returned exit code {result.returncode}: {result.stderr}",
            stderr=result.stderr,
        )

    return _parse_response(result.stdout, session_id)


def invoke_claude_with_history(
    messages: list[dict[str, str]],
    system_prompt: str | None = None,
    context_files: dict[str, str] | None = None,
    model: str | None = None,
    allowed_tools: list[str] | None = None,
    cwd: str | None = None,
) -> dict[str, Any]:
    """Invoke Claude Code with full conversation history in the prompt.

    Since the Claude Code CLI doesn't natively support multi-turn threads
    like OpenAI Assistants, we build a formatted conversation history and
    pass it as part of the prompt.

    Args:
        messages: List of {"role": "user"|"assistant", "content": str} dicts.
        system_prompt: Optional system prompt.
        context_files: Optional context files.
        model: Optional model override.
        allowed_tools: Optional list of allowed tools.
        cwd: Working directory for the claude process.

    Returns:
        Dict with keys: 'output' (str), 'session_id' (str), 'cost' (dict).
    """
    # Build conversation history as a formatted prompt
    history_parts = []
    for msg in messages[:-1]:  # All messages except the last one (which is the new user message)
        role = msg["role"]
        content = msg["content"]
        if role == "user":
            history_parts.append(f"<user>\n{content}\n</user>")
        elif role in ("assistant", "ai"):
            history_parts.append(f"<assistant>\n{content}\n</assistant>")

    # The last message is the current user prompt
    current_prompt = messages[-1]["content"] if messages else ""

    if history_parts:
        full_prompt = (
            "Here is our conversation so far:\n\n"
            + "\n\n".join(history_parts)
            + f"\n\nNow respond to this new message:\n\n{current_prompt}"
        )
    else:
        full_prompt = current_prompt

    return invoke_claude(
        prompt=full_prompt,
        system_prompt=system_prompt,
        context_files=context_files,
        model=model,
        allowed_tools=allowed_tools,
        cwd=cwd,
    )
