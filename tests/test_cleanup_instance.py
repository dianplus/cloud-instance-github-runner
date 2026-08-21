"""Behavioral regression tests for scripts/cleanup-instance.sh (AC-4..AC-8).

Contract knobs (the script under test must honor these environment variables):
CLEANUP_MAX_ATTEMPTS (default 3), CLEANUP_RETRY_DELAY (default 5s),
CLEANUP_VERIFY_POLLS (default 12), CLEANUP_VERIFY_INTERVAL (default 5s).
All tests zero the delay/interval knobs for speed.
"""

import re

CALLS_LOG_NAME = "aliyun-calls.log"


def _calls(tmp_path):
    log = tmp_path / CALLS_LOG_NAME
    if not log.exists():
        return []
    return log.read_text(encoding="utf-8").splitlines()


def _describe_calls(tmp_path):
    return [line for line in _calls(tmp_path) if "DescribeInstances" in line]


def _delete_calls(tmp_path):
    return [line for line in _calls(tmp_path) if "DeleteInstance" in line]


def test_cleanup_fails_loudly_when_cli_missing(run_cleanup):
    # AC-4: no aliyun CLI in PATH -> non-zero exit + explicit "CLI missing" error.
    rc, out = run_cleanup(path_without_aliyun=True)
    assert rc != 0, (
        "AC-4: cleanup must exit non-zero when the aliyun CLI is missing from PATH; "
        f"got rc={rc} with output:\n{out}"
    )
    assert re.search(r"(?i)aliyun.*(not (found|installed)|missing|unavailable)", out), (
        "AC-4: output must explicitly say the aliyun CLI is missing; got:\n" + out
    )
    assert "already deleted" not in out.lower(), (
        "AC-4: a missing CLI must never be reported as 'already deleted'; got:\n" + out
    )


def test_cleanup_exit_zero_when_instance_genuinely_absent(run_cleanup, tmp_path):
    # AC-5: rc=0 + empty instance set -> exit 0, but only after a real query.
    (tmp_path / "describe_empty").touch()
    rc, out = run_cleanup()
    assert rc == 0, (
        "AC-5: a verified-absent instance (rc=0, empty set) must exit 0; "
        f"got rc={rc} with output:\n{out}"
    )
    describes = _describe_calls(tmp_path)
    assert describes, (
        "AC-5: 'confirmed absent' requires an actual DescribeInstances query; "
        "the calls log shows none"
    )
    assert any("i-test-123" in line for line in describes), (
        "AC-5: the DescribeInstances query must target INSTANCE_ID (i-test-123); "
        f"calls log:\n{describes}"
    )


def test_cleanup_fails_when_status_query_errors(run_cleanup, tmp_path):
    # AC-6: DescribeInstances failing (auth/network) is NOT the same as absent.
    (tmp_path / "describe_fail").touch()
    rc, out = run_cleanup(extra_env={"CLEANUP_MAX_ATTEMPTS": "3"})
    assert rc != 0, (
        "AC-6: a failing status query must end non-zero after bounded retries; "
        f"got rc={rc} with output:\n{out}"
    )
    assert "already deleted" not in out.lower(), (
        "AC-6: a failed query must never be conflated with 'already deleted'; got:\n" + out
    )
    describe_count = len(_describe_calls(tmp_path))
    assert 2 <= describe_count <= 3, (
        "AC-6: bounded retry must issue >= 2 and <= CLEANUP_MAX_ATTEMPTS (=3) "
        f"DescribeInstances calls; got {describe_count}:\n{_calls(tmp_path)}"
    )
    assert not _delete_calls(tmp_path), (
        "AC-6: no DeleteInstance may be fired while the status query keeps failing; "
        f"calls log:\n{_calls(tmp_path)}"
    )


def test_cleanup_deletes_stopped_instance(run_cleanup, tmp_path):
    # AC-7: Stopped != deleted (a stopped instance still bills its disks).
    (tmp_path / "describe_status").write_text("Stopped\n", encoding="utf-8")
    rc, out = run_cleanup()
    deletes = _delete_calls(tmp_path)
    assert deletes, (
        "AC-7: a Stopped instance must trigger DeleteInstance; the buggy path "
        f"silently skips it (rc={rc}, output:\n{out})\ncalls log:\n{_calls(tmp_path)}"
    )
    # rc == 0 is only acceptable when a DeleteInstance actually happened above.
    if rc == 0:
        assert deletes, "rc=0 without DeleteInstance means the skip path won"


def test_cleanup_verifies_deletion_completed(run_cleanup, tmp_path):
    # AC-8: after DeleteInstance succeeds, poll DescribeInstances until the
    # instance leaves the result set (stub: 1st post-delete poll still shows
    # Running, 2nd onwards show the empty set).
    (tmp_path / "describe_status").write_text("Running\n", encoding="utf-8")
    rc, out = run_cleanup()
    assert rc == 0, (
        "AC-8: delete + verified-absent polling should complete with rc=0; "
        f"got rc={rc} with output:\n{out}"
    )
    calls = _calls(tmp_path)
    delete_idx = next((i for i, line in enumerate(calls) if "DeleteInstance" in line), None)
    assert delete_idx is not None, f"AC-8: expected a DeleteInstance call; calls log:\n{calls}"
    post_delete_polls = [line for line in calls[delete_idx + 1 :] if "DescribeInstances" in line]
    assert len(post_delete_polls) >= 2, (
        "AC-8: deletion must be verified by >= 2 post-delete DescribeInstances "
        f"polls; calls log:\n{calls}"
    )
