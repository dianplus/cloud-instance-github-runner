"""Structural contract tests for templates/user-data.sh.

Anchors from fix-instance-leak-three-defenses (AC-1/AC-1b/AC-2) plus the
watchdog-hardening-v1 contract (wh AC-1..AC-6, wh AC-9). The retired AC-3
post-job-hook pin was replaced by test_post_job_hook_dead_config_removed
(wh AC-5/AC-6): ACTIONS_RUNNER_HOOK_POST_JOB was never read by actions/runner,
so the hook was dead config from day one, not a defense line.

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


# `exec`/`exit` used as a command (statement position), not as prose in comments.
_EXEC_CMD = re.compile(r"(?:^\s*|&&\s+|\|\|\s+)exec\b")
_EXIT_CMD = re.compile(r"(?:^\s*|&&\s+|\|\|\s+)exit\b")


def _watchdog_heredoc():
    """Inner text of the runner-watchdog.sh heredoc (between WATCHDOG_EOF markers)."""
    m = re.search(r"<<\s*'WATCHDOG_EOF'\n(.*?)\nWATCHDOG_EOF", USER_DATA_TEXT, re.DOTALL)
    return m.group(1) if m else None


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


def test_watchdog_probe_distinguishes_query_failure():
    # wh AC-1: the watchdog probe must be three-state. Non-zero systemctl
    # exit -> "unknown" (query failure, NOT stop evidence); exit 0 + empty
    # output -> confirmed-inactive; exit 0 + non-empty output -> active.
    # The old single predicate let a swallowed-stderr query failure (empty
    # output) masquerade as "not active" and kill a healthy runner.
    watchdog = _watchdog_heredoc()
    assert watchdog is not None, "wh AC-1: watchdog heredoc (WATCHDOG_EOF) not found"

    for word in ("active", "unknown"):
        assert word in watchdog, (
            f"wh AC-1: probe tri-state vocabulary must include '{word}' inside the "
            "watchdog script (active / confirmed-inactive / unknown)"
        )

    # stderr suppression is fine to keep, but the exit code must still be
    # checked: rc capture and 2>/dev/null must coexist in the probe.
    assert "2>/dev/null" in watchdog, (
        "wh AC-1: expected the probe to keep suppressing probe stderr (2>/dev/null)"
    )
    rc_capture = re.search(r"\w+\s*=\s*\$\?", watchdog) or re.search(
        r"if\s+[^\n]*systemctl[^\n]*;\s*then", watchdog
    )
    assert rc_capture, (
        "wh AC-1: probe must capture the systemctl exit code ('$?' assignment or "
        "an if-condition on the systemctl call); 2>/dev/null alone makes a query "
        "failure indistinguishable from 'not active'"
    )

    # negative: the legacy single-predicate shape (non-empty output == active,
    # everything else == stopped, no rc check) must be gone.
    legacy = re.search(r'\[\[ -n "\$\(systemctl[^\n]*2>/dev/null\)" \]\]', watchdog)
    assert legacy is None, (
        "wh AC-1: legacy single-predicate probe still present "
        f"({legacy.group(0)!r}); a failed query must not count as stop evidence"
    )


def test_watchdog_requires_consecutive_confirmations():
    # wh AC-2: phase-2 self-destruction requires STOP_CONFIRMATIONS_REQUIRED
    # (default 6, i.e. 6 x POLL_INTERVAL_SECONDS 5s = 30s) consecutive
    # confirmed-inactive probes; any active probe resets the streak.
    watchdog = _watchdog_heredoc()
    assert watchdog is not None, "wh AC-2: watchdog heredoc (WATCHDOG_EOF) not found"

    assert "STOP_CONFIRMATIONS_REQUIRED" in watchdog, (
        "wh AC-2: STOP_CONFIRMATIONS_REQUIRED must be referenced inside the watchdog script"
    )
    assert re.search(r"STOP_CONFIRMATIONS_REQUIRED.{0,60}?(:-6|=6)", watchdog), (
        "wh AC-2: STOP_CONFIRMATIONS_REQUIRED default must be 6 in the watchdog "
        "(':-6' or '=6' text)"
    )
    assert re.search(r"(?i)(6\s*[x×*]\s*5|\b30\s?s\b)", watchdog), (
        "wh AC-2: the confirmation-window arithmetic (6 x 5s = 30s) must be documented"
    )

    wlines = watchdog.splitlines()
    counter_zero = re.compile(r"(?i)\w*(?:confirm|counter|consecutive|streak)\w*\s*=\s*0\b")
    reset_lines = [i for i, line in enumerate(wlines) if counter_zero.search(line)]
    assert reset_lines, (
        "wh AC-2: a consecutive-count variable (counter/confirmations-like name) "
        "assigned 0 is missing; the streak must be resettable"
    )
    near_active = [
        i
        for i in reset_lines
        if any("active" in wlines[j] for j in range(max(0, i - 3), min(len(wlines), i + 2)))
    ]
    assert near_active, (
        "wh AC-2: the counter reset (=0) must live in the branch that observes "
        "'active' (an active probe clears the confirmation streak)"
    )
    assert re.search(r"\(\(\s*\w+\s*\+\s*1\s*\)\)", watchdog), (
        "wh AC-2: the consecutive counter must be incremented ((${var} + 1)) on "
        "confirmed-inactive probes"
    )
    assert any("STOP_CONFIRMATIONS_REQUIRED" in line and "-ge" in line for line in wlines), (
        "wh AC-2: the destruction condition must compare the streak against "
        "STOP_CONFIRMATIONS_REQUIRED (-ge) -- consecutive confirmations, not one hit"
    )


def test_watchdog_phase1_semantics_preserved():
    # wh AC-3: phase-1 dead-man semantics survive the tri-state probe:
    # BOOTSTRAP_WATCH_TIMEOUT stays a bounded wait (default 1800s), timeout
    # still execs self-destruct, and 'unknown' falls into the sleep-and-
    # continue branch (a query failure is not bootstrap death). The phase-1
    # anchors themselves stay pinned by test_watchdog_deadman_semantics.
    watchdog = _watchdog_heredoc()
    assert watchdog is not None, "wh AC-3: watchdog heredoc (WATCHDOG_EOF) not found"

    assert re.search(r"BOOTSTRAP_WATCH_TIMEOUT[^\n]*:-1800", watchdog), (
        "wh AC-3: BOOTSTRAP_WATCH_TIMEOUT default must stay 1800 (':-1800') -- "
        "bounded phase-1 wait unchanged by this blueprint"
    )

    wlines = watchdog.splitlines()
    timeout_lines = [i for i, line in enumerate(wlines) if "BOOTSTRAP_WATCH_TIMEOUT" in line]
    exec_lines = [i for i, line in enumerate(wlines) if _EXEC_CMD.search(line)]
    assert any(0 < e - t <= 3 for t in timeout_lines for e in exec_lines), (
        "wh AC-3: the timeout branch must still reach an 'exec' of self-destruct "
        "in the same segment (BOOTSTRAP_WATCH_TIMEOUT branch/log followed by exec)"
    )

    unknown_lines = [i for i, line in enumerate(wlines) if "unknown" in line]
    sleep_lines = [i for i, line in enumerate(wlines) if re.search(r"\bsleep\b", line)]
    assert unknown_lines, "wh AC-3: the tri-state probe must surface 'unknown' in the watchdog"
    assert sleep_lines, "wh AC-3: the poll loop must keep sleeping between probes"
    assert any(abs(u - s) <= 8 for u in unknown_lines for s in sleep_lines), (
        "wh AC-3: 'unknown' must be handled inside the sleep-and-continue poll "
        "loop (keep waiting), not as a separate destruction branch"
    )
    for i in unknown_lines:
        line = wlines[i]
        assert not (_EXEC_CMD.search(line) or _EXIT_CMD.search(line)), (
            f"wh AC-3: 'unknown' must not appear on a command line that execs or "
            f"exits ({line!r}); a query failure is not stop evidence"
        )


def test_watchdog_pre_destroy_forensics_dump():
    # wh AC-4: before self-destruction the watchdog dumps forensics: the probe
    # timeline (tri-state, timestamped, already in the watchdog log), a
    # systemctl status tail, a journal tail -- each size-capped (head/tail -c)
    # -- written to /var/log/runner-watchdog.log and tee'd to /dev/console
    # (GetInstanceConsoleOutput can capture serial output pre-delete).
    # Best-effort: the dump must not block the exec self-destruct path.
    watchdog = _watchdog_heredoc()
    assert watchdog is not None, "wh AC-4: watchdog heredoc (WATCHDOG_EOF) not found"

    for word in ("active", "inactive", "unknown"):
        assert word in watchdog, (
            f"wh AC-4: probe timeline vocabulary must include '{word}' "
            "(the timeline records all three probe states)"
        )
    assert "/var/log/runner-watchdog.log" in watchdog, (
        "wh AC-4: timeline target /var/log/runner-watchdog.log missing from the watchdog"
    )

    wlines = watchdog.splitlines()
    assert any(re.search(r"systemctl[^\n]*\bstatus\b", line) for line in wlines), (
        "wh AC-4: the dump must collect 'systemctl status' output"
    )
    assert "journalctl" in watchdog, "wh AC-4: the dump must collect the journal tail (journalctl)"
    assert "/dev/console" in watchdog and "tee" in watchdog, (
        "wh AC-4: the dump must tee to /dev/console (serial console capture)"
    )
    assert re.search(r"\b(?:head|tail)\b[^\n]*-c\s", watchdog), (
        "wh AC-4: each collected segment must be size-capped (head/tail -c)"
    )
    assert any(
        "/var/log/runner-watchdog.log" in line and re.search(r"\b(?:head|tail)\b", line)
        for line in wlines
    ), (
        "wh AC-4: the probe timeline itself must be dumped with a size cap "
        "(head/tail of /var/log/runner-watchdog.log)"
    )

    collect_idx = [
        i
        for i, line in enumerate(wlines)
        if "journalctl" in line
        or "/dev/console" in line
        or re.search(r"systemctl[^\n]*\bstatus\b", line)
    ]
    exec_idx = [i for i, line in enumerate(wlines) if _EXEC_CMD.search(line)]
    assert collect_idx and any(e > max(collect_idx) for e in exec_idx), (
        "wh AC-4: an 'exec' self-destruct call must remain reachable after the "
        "forensics dump (best-effort: dump failure must not block destruction; "
        "the watchdog deliberately has no 'set -e')"
    )


def test_post_job_hook_dead_config_removed():
    # wh AC-5/AC-6 (replaces the retired leak-blueprint AC-3 pin
    # test_post_job_hook_created_before_service_start): ACTIONS_RUNNER_HOOK_POST_JOB
    # was never read by actions/runner (the official hook variable is
    # ACTIONS_RUNNER_HOOK_JOB_COMPLETED), so the post-job hook was dead config
    # from the initial commit -- remove it entirely, wording included.
    assert "ACTIONS_RUNNER_HOOK_POST_JOB" not in USER_DATA_TEXT, (
        "wh AC-5: ACTIONS_RUNNER_HOOK_POST_JOB is dead config (actions/runner "
        "never reads it) and must be removed from templates/user-data.sh"
    )
    assert "POST_JOB" not in USER_DATA_TEXT, (
        "wh AC-5: no POST_JOB variable may remain anywhere in templates/user-data.sh"
    )
    assert "export ACTIONS_RUNNER_HOOK_POST_JOB" not in USER_DATA_TEXT, (
        "wh AC-5: the .env export line of the dead hook variable must be removed"
    )
    assert "post-job-hook" not in USER_DATA_TEXT, (
        "wh AC-5: the post-job-hook.sh heredoc must be removed"
    )
    assert "post-job" not in USER_DATA_TEXT, (
        "wh AC-5: the string 'post-job' must appear nowhere in "
        "templates/user-data.sh (script, .env export, comments, echoes)"
    )

    # positive anchor: the chapter order contract survives the removal (also
    # carried by test_self_destruct_armed_before_runner_install).
    self_destruct_chapter = first_line_containing(
        "=== Setting up instance self-destruct mechanism ==="
    )
    runner_chapter = first_line_containing("=== Installing GitHub Actions Runner ===")
    assert self_destruct_chapter is not None and runner_chapter is not None, (
        "wh AC-5: chapter headers missing after the post-job hook removal"
    )
    assert self_destruct_chapter < runner_chapter, (
        f"wh AC-5: chapter order must stay 'self-destruct arming' (line "
        f"{self_destruct_chapter}) before 'Installing GitHub Actions Runner' "
        f"(line {runner_chapter}) after the post-job hook removal"
    )


def test_watchdog_invalid_confirmations_fails_loudly():
    # wh AC-9: STOP_CONFIRMATIONS_REQUIRED is validated at bootstrap time
    # against the operator escape-hatch channel (/etc/environment -- the file
    # the watchdog unit's EnvironmentFile consumes). Position-pinned AFTER
    # 'trap on_user_data_exit EXIT' (non-zero exit must arm self-destruct via
    # the trap; before it, a bad value would leak a live instance silently)
    # and BEFORE the watchdog heredoc -- never inside the watchdog script
    # (Restart=on-failure would loop a runtime validation failure into
    # start-limit and silently kill the dead-man switch).
    trap_line = first_line_containing("trap on_user_data_exit EXIT")
    watchdog_start = first_line_containing("WATCHDOG_EOF")
    assert trap_line is not None, "wh AC-9: 'trap on_user_data_exit EXIT' not found"
    assert watchdog_start is not None, "wh AC-9: watchdog heredoc marker (WATCHDOG_EOF) not found"

    bootstrap = USER_DATA_LINES[trap_line : watchdog_start - 1]
    slice_text = "\n".join(bootstrap)
    key_lines = [i for i, line in enumerate(bootstrap) if "STOP_CONFIRMATIONS_REQUIRED" in line]
    assert key_lines, (
        f"wh AC-9: the STOP_CONFIRMATIONS_REQUIRED validation block must sit "
        f"between 'trap on_user_data_exit EXIT' (line {trap_line}) and the "
        f"watchdog heredoc (line {watchdog_start})"
    )

    # pinned read shape: line-anchored key, last duplicate wins (tail -1),
    # value past the first '=', double quotes stripped.
    assert re.search(r"\^STOP_CONFIRMATIONS_REQUIRED=", slice_text), (
        "wh AC-9: the key read must be line-anchored (^STOP_CONFIRMATIONS_REQUIRED=)"
    )
    assert re.search(r"\btail\s+(?:-n\s+1|-1)\b", slice_text), (
        "wh AC-9: duplicate keys must resolve to the last one (tail -1)"
    )
    assert "cut -d= -f2-" in slice_text, (
        "wh AC-9: the value must be extracted with 'cut -d= -f2-' (values may contain '=')"
    )
    assert "tr -d '\"'" in slice_text, (
        "wh AC-9: double quotes must be stripped (tr -d '\"'), matching this "
        "file's quoted /etc/environment write convention"
    )

    env_lines = [i for i, line in enumerate(bootstrap) if "/etc/environment" in line]
    assert env_lines and any(abs(k - e) <= 3 for k in key_lines for e in env_lines), (
        "wh AC-9: the validation must read STOP_CONFIRMATIONS_REQUIRED from "
        "/etc/environment (same channel the watchdog unit consumes)"
    )

    assert ("=~" in slice_text) or ("[0-9]" in slice_text) or re.search(r"-gt\s+0", slice_text), (
        "wh AC-9: the value must be validated as a positive integer ('=~' with "
        "[0-9], or a -gt 0 comparison)"
    )
    assert re.search(r"\bexit\s+[1-9]", slice_text), (
        "wh AC-9: an invalid value must exit non-zero (exit 1) so the EXIT trap "
        "triggers self-destruct -- loud failure, no residual instance"
    )

    # a missing key is the legal 'no override expressed' path: guarded read,
    # no exit, documented default 6.
    assert ("|| true" in slice_text) or re.search(r"if\s+[^;\n]*grep", slice_text), (
        "wh AC-9: the /etc/environment read must be guarded (if-grep or '|| true'); "
        "under 'set -euo pipefail' an unguarded no-match grep exits non-zero and "
        "inverts the semantics into 'missing key -> self-destruct'"
    )
    assert re.search(r"STOP_CONFIRMATIONS_REQUIRED.{0,80}?(:-6|=6)", slice_text), (
        "wh AC-9: a missing key must fall back to the documented default 6 (':-6' or '=6' text)"
    )

    # negative: the validation must not run inside the watchdog script.
    watchdog = _watchdog_heredoc()
    assert watchdog is not None, "wh AC-9: watchdog heredoc (WATCHDOG_EOF) not found"
    for line in watchdog.splitlines():
        if "STOP_CONFIRMATIONS_REQUIRED" in line:
            assert "grep" not in line and not _EXIT_CMD.search(line), (
                f"wh AC-9: validation logic must not live inside the watchdog "
                f"script ({line!r}); a non-zero exit there loops via "
                "Restart=on-failure into start-limit (silent dead-man death)"
            )
