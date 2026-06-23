"""Safe execution of operator-configured external commands.

Operator-supplied commands (``BNB_AGENT_SDK_COMMAND``, ``CMC_MCP_COMMAND``)
used to be interpolated straight into ``create_subprocess_shell``. A single
typo in the Railway dashboard - e.g. ``BNB_AGENT_SDK_COMMAND`` accidentally
saved as ``=bnbaent`` - then reached ``/bin/sh`` as the literal token
``=bnbaent`` and produced ``/bin/sh: 1: =bnbaent: not found``. The shell
treated it as a malformed assignment/command and the call failed noisily.

These helpers parse the command with ``shlex``, reject tokens the shell would
never accept as an executable, resolve the binary on ``PATH``, and run it with
``create_subprocess_exec`` (no shell). A misconfigured command now raises a
clear :class:`ToolCommandError` instead of spawning a broken shell.
"""
from __future__ import annotations

import asyncio
import shlex
import shutil


class ToolCommandError(RuntimeError):
    """Raised when a configured command is present but unusable."""


def resolve_tool_command(command: str, *args: str) -> list[str] | None:
    """Turn a configured command string plus fixed args into a safe argv list.

    Returns ``None`` when nothing is configured (blank/whitespace), so callers
    can cleanly skip the integration. Raises :class:`ToolCommandError` when a
    command *is* configured but cannot be turned into a real executable, so a
    typo such as ``=bnbaent`` can never be handed to a shell.
    """
    if not command or not command.strip():
        return None
    try:
        parts = shlex.split(command)
    except ValueError as exc:  # unbalanced quotes, etc.
        raise ToolCommandError(f"invalid command {command!r}: {exc}") from exc
    if not parts:
        return None
    binary = parts[0]
    # A leading '=' (or an embedded '=' in the program word) is what the shell
    # interprets as a variable assignment rather than a command - exactly the
    # "=bnbaent" failure. Reject it before it can reach a subprocess.
    if binary.startswith("=") or "=" in binary:
        raise ToolCommandError(
            f"command {binary!r} is not a valid executable name "
            "(looks like a stray environment assignment)"
        )
    resolved = shutil.which(binary)
    if resolved is None:
        raise ToolCommandError(f"command {binary!r} was not found on PATH")
    return [resolved, *parts[1:], *args]


async def run_tool_command(command: str, *args: str) -> tuple[int, str, str] | None:
    """Run a configured command safely.

    Returns ``(returncode, stdout, stderr)`` with decoded/stripped text, or
    ``None`` when no command is configured. Raises :class:`ToolCommandError`
    for a configured-but-unusable command.
    """
    argv = resolve_tool_command(command, *args)
    if argv is None:
        return None
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    return proc.returncode, out.decode().strip(), err.decode().strip()
