"""Behavioral regression tests for scripts/fetch-console-output.sh.

Blueprint: failure-forensics-console-output-v1 (AC-1, AC-2).

Contract under test is DELIBERATELY different from cleanup-instance.sh's
fail-loud semantics: forensics is best-effort, billing safety first. Every
fetch failure (CLI missing / API error / base64 decode failure) must produce a
stderr ``Warning: ...`` and exit 0 so the subsequent cleanup-instance.sh
destruction is never blocked. See the blueprint's design decision
"best-effort forensics vs loud cleanup".
"""

import base64
import os
import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FETCH_SCRIPT = REPO_ROOT / "scripts" / "fetch-console-output.sh"
CALLS_LOG_NAME = "aliyun-calls.log"
# Multi-line plaintext on purpose: proves the script survives base64 payloads
# that decode to more than one line (real console output is multi-line).
PLAINTEXT = "=== User Data Script Started ===\nbootstrap failed here\n"


@pytest.fixture
def run_fetch(tmp_path, aliyun_stub):
    """Return a runner for scripts/fetch-console-output.sh under a controlled env."""

    def _run(path_without_aliyun=False, extra_env=None):
        stub_bin = tmp_path / "bin"
        if path_without_aliyun:
            # Minimal PATH with no aliyun binary (host aliyun lives in
            # /opt/homebrew/bin, deliberately excluded).
            path_env = "/usr/bin:/bin"
        else:
            path_env = f"{stub_bin}:/usr/bin:/bin"
        console_log = tmp_path / "console.log"
        env = {
            "PATH": path_env,
            "HOME": os.environ.get("HOME", "/tmp"),
            "ALIYUN_ACCESS_KEY_ID": "test-id",
            "ALIYUN_ACCESS_KEY_SECRET": "test-secret",
            "ALIYUN_REGION_ID": "cn-test",
            "INSTANCE_ID": "i-test-123",
            "CONSOLE_LOG_FILE": str(console_log),
        }
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            ["bash", "scripts/fetch-console-output.sh"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr, console_log

    return _run


def _calls(tmp_path):
    log = tmp_path / CALLS_LOG_NAME
    if not log.exists():
        return []
    return log.read_text(encoding="utf-8").splitlines()


def _console_calls(tmp_path):
    return [line for line in _calls(tmp_path) if "GetInstanceConsoleOutput" in line]


def test_fetch_decodes_console_output_to_file(run_fetch, tmp_path):
    # AC-1 success path: stub returns a base64 console payload -> the script
    # must decode it and write the exact plaintext to CONSOLE_LOG_FILE.
    (tmp_path / "console_b64").write_text(
        base64.b64encode(PLAINTEXT.encode("utf-8")).decode("ascii"), encoding="utf-8"
    )

    rc, out, console_log = run_fetch()

    assert rc == 0, (
        "AC-1: the success path (API rc=0, valid base64) must exit 0; "
        f"got rc={rc} with output:\n{out}"
    )
    assert console_log.exists(), (
        f"AC-1: CONSOLE_LOG_FILE must exist after a successful fetch; output:\n{out}"
    )
    assert console_log.read_text(encoding="utf-8") == PLAINTEXT, (
        "AC-1: CONSOLE_LOG_FILE must contain exactly the base64-decoded console "
        f"output; got {console_log.read_text(encoding='utf-8')!r}"
    )
    console_calls = _console_calls(tmp_path)
    assert console_calls and any("i-test-123" in line for line in console_calls), (
        "AC-1: the script must call GetInstanceConsoleOutput targeting INSTANCE_ID "
        f"(i-test-123); calls log:\n{_calls(tmp_path)}"
    )
    assert re.search(r"(?i)(\blines?\b|\bwrote\b)", out), (
        f"AC-1: stdout must report what was captured (line count / wrote); got:\n{out}"
    )


@pytest.mark.parametrize(
    ("scenario", "path_without_aliyun", "marker_content"),
    [
        # (a) aliyun CLI missing from PATH entirely.
        ("cli_missing_from_path", True, None),
        # (b) API call fails: no console_b64 marker -> stub exits rc 1.
        ("api_returns_error", False, None),
        # (c) API succeeds but ConsoleOutput is not valid base64 -> decode fails.
        ("console_output_not_valid_base64", False, "not-base64!!!"),
    ],
)
def test_fetch_forensic_failures_never_block_cleanup(
    run_fetch, tmp_path, scenario, path_without_aliyun, marker_content
):
    # AC-1 failure paths + AC-2 negative assertions: forensics is best-effort.
    # Every fetch failure must warn (stderr) and exit 0 -- cleanup-instance.sh
    # must NEVER be blocked -- and must not leave a half-written log behind.
    if marker_content is not None:
        (tmp_path / "console_b64").write_text(marker_content, encoding="utf-8")

    rc, out, console_log = run_fetch(path_without_aliyun=path_without_aliyun)

    assert rc == 0, (
        f"AC-1 (scenario: {scenario}): a forensic fetch failure must still exit 0 "
        f"(best-effort contract; cleanup must never be blocked); got rc={rc} "
        f"with output:\n{out}"
    )
    assert re.search(r"(?i)warning", out), (
        f"AC-1 (scenario: {scenario}): the failure must be surfaced as a "
        f"'Warning: ...' message; got:\n{out}"
    )
    assert (not console_log.exists()) or (console_log.stat().st_size == 0), (
        f"AC-1 (scenario: {scenario}): a failed fetch must not leave a partial "
        "CONSOLE_LOG_FILE (write to a temp file then atomic mv, or delete on "
        "failure)"
    )

    # AC-2 static negative assertion. Implementation note: this deliberately
    # takes the aggressive-but-simple reading -- the script text must not
    # contain a literal "exit 1" at all. Justification: blueprint AC-2 states
    # the fetch script must not exit non-zero under the best-effort contract,
    # so NO path (CLI preflight, API failure, decode failure) may terminate
    # with "exit 1"; any occurrence, including a "command -v aliyun" hard-fail
    # preflight, is a contract violation.
    assert FETCH_SCRIPT.exists(), (
        "AC-2 static check: scripts/fetch-console-output.sh does not exist yet "
        "(TDD RED state); create it per blueprint AC-1/AC-2"
    )
    script_text = FETCH_SCRIPT.read_text(encoding="utf-8")
    assert "exit 1" not in script_text, (
        "AC-2: fetch-console-output.sh must never exit non-zero -- no "
        "'command -v aliyun' hard-fail preflight, no 'exit 1' on any path"
    )


def test_fetch_call_is_bounded():
    # AC-6 (blueprint v2): the GetInstanceConsoleOutput call must carry CLI
    # native bound flags -- an unbounded call (SDK default retries + long
    # timeouts) could eat the cancellation grace window and push deletion to
    # the TTL backstop.
    script_text = FETCH_SCRIPT.read_text(encoding="utf-8")
    for flag, knob, default in (
        ("--connect-timeout", "CONSOLE_FETCH_CONNECT_TIMEOUT", "10"),
        ("--read-timeout", "CONSOLE_FETCH_READ_TIMEOUT", "30"),
        ("--retry-count", "CONSOLE_FETCH_RETRY_COUNT", "0"),
    ):
        # The script declares each knob as its own `${KNOB:-default}` line and
        # references the variable at the call site -- assert both halves.
        default_decl = re.escape(f"${{{knob}:-{default}}}")
        call_site = re.escape(f'{flag} "${{{knob}}}"')
        assert re.search(default_decl, script_text), (
            f"AC-6: {knob} must default to {default} via "
            f"${{{knob}:-{default}}} (env-overridable); script:\n{script_text}"
        )
        assert re.search(call_site, script_text), (
            f'AC-6: the fetch call must pass {flag} "${{{knob}}}" '
            f"(bounded call site); script:\n{script_text}"
        )
