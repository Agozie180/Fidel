"""Tests for safe execution of operator-configured commands.

Guards the regression behind ``/bin/sh: 1: =bnbaent: not found`` - a malformed
command value must never reach a shell, and the agent must keep running.
"""
from __future__ import annotations

import asyncio

import pytest

from backend.config import Settings
from backend.executor import BnbAgentCoordinator
from backend.proc import ToolCommandError, resolve_tool_command, run_tool_command


def test_blank_command_resolves_to_none():
    assert resolve_tool_command("") is None
    assert resolve_tool_command("   ") is None


def test_stray_assignment_token_is_rejected():
    # Exactly the "=bnbaent" dashboard typo: must raise, never shell out.
    with pytest.raises(ToolCommandError):
        resolve_tool_command("=bnbaent", "heartbeat", "--chain", "bsc")


def test_embedded_assignment_is_rejected():
    with pytest.raises(ToolCommandError):
        resolve_tool_command("FOO=bar")


def test_missing_binary_is_rejected_not_executed():
    with pytest.raises(ToolCommandError):
        resolve_tool_command("definitely-not-a-real-binary-xyz")


def test_run_tool_command_returns_none_when_unconfigured():
    assert asyncio.run(run_tool_command("")) is None


def test_heartbeat_survives_malformed_sdk_command():
    # The bug: BnbAgentCoordinator.heartbeat() shelled out a bad command and
    # raised "/bin/sh: 1: =bnbaent: not found". It must now never raise and
    # always return a human-readable status string instead.
    cfg = Settings(bnb_agent_sdk_enabled=False, bnb_agent_sdk_command="=bnbaent")
    message = asyncio.run(BnbAgentCoordinator(cfg).heartbeat())
    assert isinstance(message, str) and message
    # If the bnbagent SDK is not installed in this env, we exercise the command
    # path and prove it degrades gracefully rather than crashing.
    if "misconfigured" in message:
        assert "native coordinator active" in message
