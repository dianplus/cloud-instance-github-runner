"""Behavioral tests for scripts/wait-for-runner.sh.

The script polls the GitHub runners API via curl and matches with jq (both
are real here: curl is stubbed via a PATH shim, jq runs for real — the
selection/filter logic is part of the contract under test).

Stub contract (marker files in the stub dir):
- ``runners_json``: the runners list body to return (default ``{"runners": []}``)
- ``http_seq``: one HTTP status code per line; the Nth call uses the Nth
  line and the last line repeats afterwards (default ``200``)
"""

import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WAIT_SCRIPT = REPO_ROOT / "scripts" / "wait-for-runner.sh"
RUNNER_NAME = "ci-runner-test-123"

CURL_STUB = r"""#!/usr/bin/env bash
# curl stub driven by marker files in $STUB_DIR (see module docstring).
body="$(cat "${STUB_DIR}/runners_json" 2>/dev/null || printf '{"runners": []}')"
n="$(cat "${STUB_DIR}/call_count" 2>/dev/null || printf 0)"
n=$((n + 1))
printf '%s' "$n" > "${STUB_DIR}/call_count"
if [[ -f "${STUB_DIR}/http_seq" ]]; then
  code="$(sed -n "${n}p" "${STUB_DIR}/http_seq")"
  code="${code:-$(tail -1 "${STUB_DIR}/http_seq")}"
else
  code=200
fi
printf '%s\n%s\n' "$body" "$code"
"""


def _write_stub(tmp_path, body=None, http_seq=None):
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir(exist_ok=True)
    (stub_bin / "curl").write_text(CURL_STUB, encoding="utf-8")
    (stub_bin / "curl").chmod(0o755)
    if body is not None:
        (tmp_path / "runners_json").write_text(body, encoding="utf-8")
    if http_seq is not None:
        (tmp_path / "http_seq").write_text(http_seq, encoding="utf-8")
    return stub_bin


def _run_wait(tmp_path, stub_bin, env_overrides=None):
    env = {
        "PATH": f"{stub_bin}:/usr/bin:/bin",
        "HOME": os.environ.get("HOME", "/tmp"),
        "STUB_DIR": str(tmp_path),
        "GITHUB_TOKEN": "test-token",
        "GITHUB_REPOSITORY": "octo-org/example-repo",
        "RUNNER_NAME": RUNNER_NAME,
        "TIMEOUT": "2",
        "INTERVAL": "1",
        "GITHUB_OUTPUT": str(tmp_path / "github_output"),
    }
    if env_overrides is not None:
        env.update(env_overrides)
    proc = subprocess.run(
        ["bash", str(WAIT_SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    out = proc.stdout + proc.stderr
    gh_output_path = tmp_path / "github_output"
    gh_output = gh_output_path.read_text(encoding="utf-8") if gh_output_path.exists() else ""
    return proc.returncode, out, gh_output


def test_runner_online_exits_zero_and_writes_output(tmp_path):
    # Happy path: the runner appears in the list with status online ->
    # exit 0 and runner_online=true in GITHUB_OUTPUT.
    stub_bin = _write_stub(
        tmp_path,
        body=('{"runners": [{"name": "' + RUNNER_NAME + '", "id": 7, "status": "online"}]}'),
    )
    rc, out, gh_output = _run_wait(tmp_path, stub_bin)
    assert rc == 0, f"online runner must exit 0; got rc={rc}, output:\n{out}"
    assert "runner_online=true" in gh_output, (
        f"GITHUB_OUTPUT must carry runner_online=true; got:\n{gh_output}"
    )
    assert "Runner is online" in out, f"stdout must report online; got:\n{out}"


def test_timeout_when_runner_never_appears(tmp_path):
    # The runner never shows up: bounded polling (TIMEOUT=2/INTERVAL=1 ->
    # 2 attempts), then exit 1 with runner_online=false.
    stub_bin = _write_stub(tmp_path)  # default body: {"runners": []}
    rc, out, gh_output = _run_wait(tmp_path, stub_bin)
    assert rc == 1, (
        f"a runner that never appears must exit 1 after the timeout; got rc={rc}, output:\n{out}"
    )
    assert "runner_online=false" in gh_output, (
        f"GITHUB_OUTPUT must carry runner_online=false; got:\n{gh_output}"
    )
    assert "did not come online" in out, f"the timeout must be reported; got:\n{out}"
    calls = (tmp_path / "call_count").read_text(encoding="utf-8")
    assert calls == "2", f"TIMEOUT=2/INTERVAL=1 means exactly 2 polls; got {calls}"


def test_transient_http_error_then_online(tmp_path):
    # A transient API error (HTTP 403) must not fail the wait: the poll
    # loop warns and continues, the next 200 + online succeeds.
    stub_bin = _write_stub(
        tmp_path,
        body=('{"runners": [{"name": "' + RUNNER_NAME + '", "id": 7, "status": "online"}]}'),
        http_seq="403\n200\n",
    )
    rc, out, gh_output = _run_wait(tmp_path, stub_bin)
    assert rc == 0, f"a transient HTTP error must be tolerated; got rc={rc}, output:\n{out}"
    assert "HTTP 403" in out, f"the transient error must be surfaced as a warning; got:\n{out}"
    assert "runner_online=true" in gh_output


def test_missing_token_fails_fast(tmp_path):
    # Required-env validation runs before any polling: no GITHUB_TOKEN ->
    # immediate exit 1 (no curl calls).
    stub_bin = _write_stub(tmp_path)
    rc, out, _ = _run_wait(tmp_path, stub_bin, {"GITHUB_TOKEN": ""})
    assert rc == 1, f"missing GITHUB_TOKEN must fail fast; got rc={rc}:\n{out}"
    assert "GITHUB_TOKEN is required" in out
    assert not (tmp_path / "call_count").exists(), "validation must run before the first curl call"


def test_timeout_comment_matches_default():
    # wh AC-7: the TIMEOUT default line's trailing comment must match the
    # actual default (120 seconds = 2 minutes); the stale "5 minutes"
    # wording must be gone.
    text = WAIT_SCRIPT.read_text(encoding="utf-8")
    m = re.search(r'^TIMEOUT="\$\{TIMEOUT:-(\d+)\}"\s*(#.*)?$', text, re.MULTILINE)
    assert m is not None, (
        'wh AC-7: TIMEOUT default assignment (TIMEOUT="${TIMEOUT:-<n>}") not found '
        "in scripts/wait-for-runner.sh"
    )
    assert m.group(1) == "120", (
        f"wh AC-7: TIMEOUT default must remain 120 seconds; got {m.group(1)}"
    )
    comment = (m.group(2) or "").lower()
    assert "5 minutes" not in comment, (
        f"wh AC-7: the TIMEOUT comment must match the 120s default (2 minutes); "
        f"stale comment present: {m.group(2)!r}"
    )
