"""Structural contract tests for templates/user-data.sh (AC-1/AC-1b/AC-2/AC-3).

user-data.sh runs inside cloud-init on the ECS instance and cannot be exercised
behaviorally in this credential-free repo (see the blueprint's note on the
honest coverage limit of structural ACs). These tests encode the blueprint's
chapter-ordering anchors as plain-text line-order assertions.
"""

import re
from pathlib import Path

USER_DATA_PATH = Path(__file__).resolve().parent.parent / "templates" / "user-data.sh"
USER_DATA_TEXT = USER_DATA_PATH.read_text(encoding="utf-8")
USER_DATA_LINES = USER_DATA_TEXT.splitlines()


def first_line_containing(fragment):
    for idx, line in enumerate(USER_DATA_LINES, start=1):
        if fragment in line:
            return idx
    return None


def first_line_matching(pattern):
    rx = re.compile(pattern)
    for idx, line in enumerate(USER_DATA_LINES, start=1):
        if rx.search(line):
            return idx
    return None


def test_self_destruct_armed_before_runner_install():
    # AC-1: the whole self-destruct arming chapter must precede the runner
    # install chapter, so any runner-step failure leaves the destruct armed.
    runner_header = first_line_containing("=== Installing GitHub Actions Runner ===")
    assert runner_header is not None, (
        "AC-1: '=== Installing GitHub Actions Runner ===' anchor missing"
    )

    anchors = {
        "self-destruct chapter header": first_line_containing(
            "=== Setting up instance self-destruct mechanism ==="
        ),
        "self-destruct.sh script path": first_line_containing("/usr/local/bin/self-destruct.sh"),
        "runner-watchdog.sh script path": first_line_containing(
            "/usr/local/bin/runner-watchdog.sh"
        ),
        "watchdog systemd unit enable": first_line_matching(
            r"(?i)(systemctl.*enable.*watchdog|watchdog.*systemctl.*enable)"
        ),
    }
    for name, line_no in anchors.items():
        assert line_no is not None, (
            f"AC-1: anchor '{name}' not found in templates/user-data.sh; the "
            "self-destruct arming chapter (self-destruct.sh + runner-watchdog.sh "
            "+ watchdog unit enable) is incomplete"
        )
        assert line_no < runner_header, (
            f"AC-1: expected chapter order 'self-destruct arming' < "
            f"'=== Installing GitHub Actions Runner ===', but anchor '{name}' is at "
            f"line {line_no} while the runner chapter starts at line {runner_header}"
        )

    config_sh = first_line_containing("./config.sh")
    assert config_sh is not None, "AC-1: runner registration call './config.sh' not found"
    assert config_sh > runner_header, (
        f"AC-1: './config.sh' (runner registration, line {config_sh}) must come "
        f"after '=== Installing GitHub Actions Runner ===' (line {runner_header})"
    )


def test_watchdog_deadman_semantics():
    # AC-1b: runner-watchdog.sh must be a dead-man switch -- bounded wait
    # (BOOTSTRAP_WATCH_TIMEOUT) for actions.runner.* to appear, self-destruct on
    # timeout; never "glob no match == already stopped".
    assert re.search(r"runner-watchdog", USER_DATA_TEXT), (
        "AC-1b: templates/user-data.sh must create a runner-watchdog.sh dead-man "
        "watchdog; no 'runner-watchdog' reference found"
    )
    assert "BOOTSTRAP_WATCH_TIMEOUT" in USER_DATA_TEXT, (
        "AC-1b: the watchdog must bound its wait for the runner service with "
        "BOOTSTRAP_WATCH_TIMEOUT; knob not found"
    )
    assert re.search(r"actions\.runner", USER_DATA_TEXT), (
        "AC-1b: the watchdog must wait on the 'actions.runner' service"
    )
    assert re.search(r"self-destruct", USER_DATA_TEXT), (
        "AC-1b: the timeout path must lead to self-destruct"
    )
    legacy_glob_wait = "systemctl is-active --quiet actions.runner." in USER_DATA_TEXT
    if legacy_glob_wait:
        assert "BOOTSTRAP_WATCH_TIMEOUT" in USER_DATA_TEXT, (
            "AC-1b: legacy glob wait 'while systemctl is-active --quiet "
            "actions.runner.*' is present without a BOOTSTRAP_WATCH_TIMEOUT guard; "
            "the glob loop exits immediately when the runner service never appears "
            "(race) -- both keywords must coexist so the bounded guard governs the wait"
        )


def _function_body(name):
    m = re.search(rf"{name}\s*\(\)\s*\{{", USER_DATA_TEXT)
    if m is None:
        m = re.search(rf"function\s+{name}\b", USER_DATA_TEXT)
    if m is None:
        return None
    start = m.start()
    end = USER_DATA_TEXT.find("\n}", start)
    return USER_DATA_TEXT[start:] if end == -1 else USER_DATA_TEXT[start:end]


def test_exit_trap_arms_self_destruct_on_failure():
    # AC-2: a non-zero exit of user-data must trigger the self-destruct path
    # via trap on_user_data_exit EXIT; zero exit must not.
    assert "trap on_user_data_exit EXIT" in USER_DATA_TEXT, (
        "AC-2: exact trap 'trap on_user_data_exit EXIT' not installed in templates/user-data.sh"
    )
    body = _function_body("on_user_data_exit")
    assert body is not None, "AC-2: handler function 'on_user_data_exit()' must be defined"
    assert re.search(r"(\$\?|EXIT_CODE|exit_code)[^\n]{0,80}(-ne|-gt)\s*0", body), (
        "AC-2: handler must arm self-destruct only on non-zero exit "
        "($?/EXIT_CODE compared with -ne 0/-gt 0); no such condition in:\n" + body
    )
    assert "self-destruct" in body, (
        "AC-2: handler must reference the self-destruct script/path on failure;\n" + body
    )


def test_post_job_hook_created_before_service_start():
    # AC-3: post-job-hook.sh must exist before ./svc.sh start runs.
    hook_write = first_line_matching(r"cat\s*>.*post-job-hook\.sh")
    assert hook_write is not None, "AC-3: heredoc write of ${RUNNER_DIR}/post-job-hook.sh not found"
    svc_start = first_line_containing("./svc.sh start")
    assert svc_start is not None, "AC-3: './svc.sh start' not found"
    assert hook_write < svc_start, (
        f"AC-3: expected order 'write post-job-hook.sh' < './svc.sh start', but "
        f"write is at line {hook_write} and service start at line {svc_start} "
        "(hook must exist before the service starts)"
    )
