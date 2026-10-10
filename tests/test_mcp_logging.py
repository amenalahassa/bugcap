"""BUGS.md: `bugcap mcp-serve` logs startup, client initialize, tool calls and errors, never to stdout."""
import asyncio
import logging
import os
import subprocess
import sys

import pytest
from bugcap import logs


@pytest.fixture(autouse=True)
def _clean_loggers():
    yield
    for name in logs.LOGGER_NAMES:
        logger = logging.getLogger(name)
        for handler in [h for h in logger.handlers if getattr(h, logs._MARK, False)]:
            logger.removeHandler(handler)
            handler.close()


def test_install_hint_names_the_running_interpreter():
    """Report #9: a user who'd already installed the mcp extra elsewhere still hit this
    hint, because a stale `bugcap` shim on PATH kept running a different, extra-less
    install. Naming the interpreter actually running lets that be diagnosed instead of
    repeating the same unhelpful "pipx install" suggestion."""
    from bugcap import mcp_server

    hint = mcp_server._install_hint()
    assert sys.executable in hint
    assert "extra" in hint.lower()
    assert "force" in hint.lower()  # points at the fix for a shadowed shim


def test_default_log_location_is_in_the_data_dir(bugcap_home):
    assert logs.default_log_path() == bugcap_home / "data" / "logs" / "mcp-server.log"


def test_level_precedence(bugcap_home, monkeypatch):
    from bugcap import config

    assert logs.resolve_level() == logging.INFO
    config.set_value("log.level", "warning")
    assert logs.resolve_level() == logging.WARNING
    monkeypatch.setenv("BUGCAP_LOG_LEVEL", "debug")
    assert logs.resolve_level() == logging.DEBUG
    assert logs.resolve_level("error") == logging.ERROR
    monkeypatch.setenv("BUGCAP_LOG_LEVEL", "nonsense")
    assert logs.resolve_level() == logging.WARNING  # unknown values are ignored


def test_setup_writes_file_and_stderr_never_stdout(bugcap_home, capsys):
    logger, path = logs.setup_logging("info")
    logger.info("hello log")
    logger.debug("hidden at info")
    for handler in logger.handlers:
        handler.flush()
    out, err = capsys.readouterr()
    assert out == "" and "hello log" in err
    text = path.read_text()
    assert "hello log" in text and "hidden at info" not in text and "INFO bugcap.mcp" in text


def test_setup_is_idempotent(bugcap_home):
    logger, path = logs.setup_logging("info")
    logs.setup_logging("debug")
    ours = [h for h in logger.handlers if getattr(h, logs._MARK, False)]
    assert len(ours) == 2 and logger.level == logging.DEBUG


def test_unwritable_log_file_falls_back_to_stderr(bugcap_home, tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    logger, path = logs.setup_logging("info", str(blocker / "sub" / "x.log"))
    assert path is None
    logger.info("still logged")
    assert "still logged" in capsys.readouterr().err


def _call(server, name, args=None):
    return asyncio.run(server.call_tool(name, args or {}))


def test_tool_calls_are_logged_with_outcome_and_duration(bugcap_home):
    pytest.importorskip("mcp")
    from bugcap import mcp_server

    _, path = logs.setup_logging("info")
    server = mcp_server.build_server()
    _call(server, "list_reports")
    text = path.read_text()
    assert "tool list_reports called (arguments: all, limit, status)" in text
    assert "tool list_reports ok in" in text and " ms" in text


def test_tool_error_result_is_logged_as_warning(bugcap_home):
    pytest.importorskip("mcp")
    from bugcap import mcp_server

    _, path = logs.setup_logging("info")
    _call(mcp_server.build_server(), "update_notes", {"id": 99, "notes": "private text"})
    text = path.read_text()
    assert "WARNING bugcap.mcp: tool update_notes returned an error" in text and "not_found" in text
    assert "private text" not in text  # argument values are not logged at info


def test_argument_values_only_at_debug(bugcap_home):
    pytest.importorskip("mcp")
    from bugcap import mcp_server

    _, path = logs.setup_logging("debug")
    _call(mcp_server.build_server(), "update_notes", {"id": 99, "notes": "visible at debug"})
    assert "visible at debug" in path.read_text()


def test_exception_logged_with_traceback_and_reraised(bugcap_home, monkeypatch):
    pytest.importorskip("mcp")
    from bugcap import agent_api, mcp_server

    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(agent_api, "list_reports", boom)
    _, path = logs.setup_logging("info")
    with pytest.raises(Exception):
        _call(mcp_server.build_server(), "list_reports")
    text = path.read_text()
    assert "ERROR bugcap.mcp: tool list_reports failed after" in text
    assert "Traceback" in text and "RuntimeError: kaboom" in text


def test_problem_detection():
    from bugcap.mcp_server import _problem

    assert _problem('{"error": "bad", "code": "not_found"}') == "not_found: bad"
    assert _problem(['{"status": "cancelled", "message": "no"}', object()]) == "cancelled: no"
    assert _problem('{"status": "captured"}') is None
    assert _problem("not json") is None and _problem(5) is None


def test_stdio_server_logs_startup_initialize_and_calls(bugcap_home):
    pytest.importorskip("mcp")
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def drive():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "bugcap.cli", "mcp-serve"],
            env=dict(os.environ, BUGCAP_HOME=str(bugcap_home)),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("list_reports", {})

    asyncio.run(asyncio.wait_for(drive(), timeout=30))
    text = (bugcap_home / "data" / "logs" / "mcp-server.log").read_text()
    assert "starting bugcap" in text and "database" in text
    assert "client initialize:" in text
    assert "tool list_reports ok in" in text and "server stopped" in text


def test_log_file_flag_and_stdout_stays_clean(bugcap_home, tmp_path):
    pytest.importorskip("mcp")
    target = tmp_path / "custom.log"
    proc = subprocess.run(
        [sys.executable, "-m", "bugcap.cli", "mcp-serve", "--log-level", "debug", "--log-file", str(target)],
        input="", capture_output=True, text=True, timeout=30,
        env=dict(os.environ, BUGCAP_HOME=str(bugcap_home)),
    )
    assert proc.stdout == ""  # stdout is reserved for the protocol
    assert f"logging to {target}" in proc.stderr
    assert "starting bugcap" in target.read_text()


def test_missing_sdk_is_logged_and_reported(bugcap_home):
    code = (
        "import sys; sys.modules['mcp']=None; sys.modules['mcp.server']=None; "
        "sys.modules['mcp.server.fastmcp']=None; "
        "from bugcap import cli; raise SystemExit(cli.main(['mcp-serve']))"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                          env=dict(os.environ, BUGCAP_HOME=str(bugcap_home)))
    assert proc.returncode == 1 and "extra" in proc.stderr.lower()
    assert "cannot start" in (bugcap_home / "data" / "logs" / "mcp-server.log").read_text()
