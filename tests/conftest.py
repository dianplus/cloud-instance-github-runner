"""Shared fixtures for the fix-instance-leak-three-defenses regression suite (TDD RED phase).

The ``aliyun`` stub emulates the real Aliyun CLI's observable contract for the
subset of calls used by ``scripts/cleanup-instance.sh``:

* ``DescribeInstances`` prints the raw API JSON on stdout with rc 0.
* When invoked with ``--query <path> --output text`` (the current script's
  calling convention), the real CLI extracts the queried value; when the query
  path has no match -- e.g. the instance set is empty -- the real CLI exits
  rc != 0 with empty stdout. The stub reproduces both behaviors for the query
  ``Instances.Instance[0].Status`` (the only query this repo uses).
* ``DeleteInstance`` succeeds (rc 0), creates a ``deleted`` marker, and arms
  post-delete polling: the 1st subsequent ``DescribeInstances`` still reports
  the pre-delete status; the 2nd onwards report the empty set (counted via the
  ``poll-count`` file).
* ``GetInstanceConsoleOutput`` (blueprint failure-forensics-console-output-v1,
  AC-5): when the ``console_b64`` marker file exists, prints
  ``{"ConsoleOutput": "<raw marker content>"}`` on stdout with rc 0 (python3
  assembles the JSON so multi-line base64 payloads are escaped safely); with
  no marker, exits rc 1 with a simulated stderr error. The invocation is
  recorded in ``aliyun-calls.log`` like every other subcommand.

Behavior modes are selected by marker files under ``tmp_path``:

* ``describe_empty`` -- instance set is empty (rc 0 + empty JSON body)
* ``describe_fail``  -- DescribeInstances fails: rc 1 + stderr error message
* ``console_b64``    -- GetInstanceConsoleOutput payload: the raw file content
  is embedded verbatim as the JSON ``ConsoleOutput`` string (the script under
  test must base64-decode it after JSON parsing); absent marker -> rc 1 error
* default            -- single instance whose status is the content of the
  ``describe_status`` file (the fixture seeds it with ``Running``)
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

STUB_ALIYUN_SCRIPT = r"""#!/bin/bash
# Test stub for the aliyun CLI. The behavior contract is documented in
# tests/conftest.py. Semantics choice: this stub emulates the REAL aliyun CLI,
# not the buggy script's assumptions -- with `--query <path> --output text` it
# extracts the queried value, and a query path with no match (empty instance
# set) exits rc != 0 with empty stdout, exactly like the real CLI does.

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CALLS_LOG="${BASE_DIR}/aliyun-calls.log"
STATUS_FILE="${BASE_DIR}/describe_status"

# Record the invocation: one line per call, argv joined by single spaces.
echo "$*" >> "${CALLS_LOG}"

SUBCOMMAND="other"
for arg in "$@"; do
  case "${arg}" in
    DescribeInstances)         SUBCOMMAND="describe" ;;
    DeleteInstance)            SUBCOMMAND="delete" ;;
    GetInstanceConsoleOutput)  SUBCOMMAND="console" ;;
    version)                   SUBCOMMAND="version" ;;
  esac
done

QUERY=""
OUTPUT_MODE=""
prev_arg=""
for arg in "$@"; do
  case "${prev_arg}" in
    --query)  QUERY="${arg}" ;;
    --output) OUTPUT_MODE="${arg}" ;;
  esac
  prev_arg="${arg}"
done

STATUS="Running"
if [[ -f "${STATUS_FILE}" ]]; then
  STATUS="$(tr -d '[:space:]' < "${STATUS_FILE}")"
fi

STATUS_JSON='{"Instances": {"Instance": [{"InstanceId": "i-test-123", "Status": "'"${STATUS}"'"}]}}'
EMPTY_JSON='{"Instances": {"Instance": []}}'

describe_body() {
  # Emits the DescribeInstances response body according to marker files.
  if [[ -f "${BASE_DIR}/describe_fail" ]]; then
    echo "STUB aliyun: simulated DescribeInstances failure (auth/network error)" >&2
    return 1
  fi
  if [[ -f "${BASE_DIR}/deleted" ]]; then
    # Post-delete polling: 1st poll still reports the pre-delete status,
    # 2nd onwards report the empty set.
    local poll_count=0
    if [[ -f "${BASE_DIR}/poll-count" ]]; then
      poll_count="$(cat "${BASE_DIR}/poll-count")"
    fi
    poll_count=$((poll_count + 1))
    echo "${poll_count}" > "${BASE_DIR}/poll-count"
    if [[ "${poll_count}" -ge 2 ]]; then
      echo "${EMPTY_JSON}"
    else
      echo "${STATUS_JSON}"
    fi
    return 0
  fi
  if [[ -f "${BASE_DIR}/describe_empty" ]]; then
    echo "${EMPTY_JSON}"
    return 0
  fi
  echo "${STATUS_JSON}"
  return 0
}

case "${SUBCOMMAND}" in
  describe)
    BODY="$(describe_body)"
    BODY_RC=$?
    if [[ "${BODY_RC}" -ne 0 ]]; then
      exit "${BODY_RC}"
    fi
    if [[ "${OUTPUT_MODE}" == "text" && -n "${QUERY}" ]]; then
      # Real-CLI --query/--output text semantics: extract the queried value;
      # no match in an empty instance set -> rc != 0 with empty stdout.
      if [[ "${BODY}" == "${EMPTY_JSON}" ]]; then
        echo "STUB aliyun: query path '${QUERY}' has no match in response" >&2
        exit 1
      fi
      if [[ "${QUERY}" == "Instances.Instance[0].Status" ]]; then
        printf '%s\n' "${BODY}" | sed -n 's/.*"Status": *"\([^"]*\)".*/\1/p'
        exit 0
      fi
      # Unknown query paths: fall through and print the full JSON body
      # (documented simplification; the fix under test must not rely on it).
    fi
    echo "${BODY}"
    exit 0
    ;;
  delete)
    touch "${BASE_DIR}/deleted"
    echo '{"RequestId": "stub-delete-ok"}'
    exit 0
    ;;
  version)
    echo "3.2.2-stub"
    exit 0
    ;;
  console)
    # Blueprint failure-forensics-console-output-v1 (AC-5): marker-driven
    # GetInstanceConsoleOutput emulation. No marker -> simulated API failure.
    CONSOLE_B64_FILE="${BASE_DIR}/console_b64"
    if [[ ! -f "${CONSOLE_B64_FILE}" ]]; then
      echo "STUB aliyun: simulated GetInstanceConsoleOutput failure (instance gone)" >&2
      exit 1
    fi
    # Emit {"ConsoleOutput": "<raw marker content>"}; python3 assembles the
    # JSON so multi-line base64 payloads are escaped safely.
    python3 - "${CONSOLE_B64_FILE}" <<'PYEOF'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    payload = fh.read()
print(json.dumps({"ConsoleOutput": payload}))
PYEOF
    exit 0
    ;;
  *)
    exit 0
    ;;
esac
"""


@pytest.fixture
def aliyun_stub(tmp_path):
    """Install a fake ``aliyun`` executable under tmp_path/bin and seed defaults.

    Returns tmp_path so tests can place mode marker files (describe_empty,
    describe_fail, describe_status) and read back aliyun-calls.log.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "aliyun"
    stub.write_text(STUB_ALIYUN_SCRIPT, encoding="utf-8")
    stub.chmod(0o755)
    # Deterministic default status for the default mode; tests overwrite as needed.
    (tmp_path / "describe_status").write_text("Running\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def run_cleanup(tmp_path, aliyun_stub):
    """Return a runner for scripts/cleanup-instance.sh under a minimal controlled env."""

    def _run(path_without_aliyun=False, extra_env=None):
        stub_bin = tmp_path / "bin"
        if path_without_aliyun:
            # Minimal PATH with no aliyun binary (host aliyun lives in
            # /opt/homebrew/bin, deliberately excluded).
            path_env = "/usr/bin:/bin"
        else:
            path_env = f"{stub_bin}:/usr/bin:/bin"
        env = {
            "PATH": path_env,
            "HOME": os.environ.get("HOME", "/tmp"),
            "ALIYUN_ACCESS_KEY_ID": "test-id",
            "ALIYUN_ACCESS_KEY_SECRET": "test-secret",
            "ALIYUN_REGION_ID": "cn-test",
            "INSTANCE_ID": "i-test-123",
            # Contract knobs (script defaults: 5s / 5s) zeroed for test speed.
            "CLEANUP_RETRY_DELAY": "0",
            "CLEANUP_VERIFY_INTERVAL": "0",
        }
        if extra_env:
            env.update(extra_env)
        proc = subprocess.run(
            ["bash", "scripts/cleanup-instance.sh"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return proc.returncode, proc.stdout + proc.stderr

    return _run
