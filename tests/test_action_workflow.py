"""Workflow contract tests for action.yml (AC-11) -- plain text assertions.

PyYAML is deliberately NOT used: the project has no yaml runtime dependency
and NFR-3 forbids adding one.
"""

import re
from pathlib import Path

ACTION_YML_PATH = Path(__file__).resolve().parent.parent / "action.yml"
ACTION_YML_TEXT = ACTION_YML_PATH.read_text(encoding="utf-8")
ACTION_YML_LINES = ACTION_YML_TEXT.splitlines()


def _line_index_of(fragment):
    for idx, line in enumerate(ACTION_YML_LINES):
        if fragment in line:
            return idx
    return None


def test_cleanup_step_runs_on_failure_or_cancelled():
    # AC-11: cleanup must also run on cancellation, the TTL input must exist
    # with default "240", and the create step must inject INSTANCE_TTL_MINUTES.
    step_idx = _line_index_of("- name: Cleanup on Failure")
    assert step_idx is not None, "AC-11: 'Cleanup on Failure' step not declared in action.yml"

    window = "\n".join(ACTION_YML_LINES[step_idx + 1 : step_idx + 6])
    assert re.search(r"if:\s*failure\(\)\s*\|\|\s*cancelled\(\)", window), (
        "AC-11: within 5 lines after 'Cleanup on Failure' the condition must be "
        f"'if: failure() || cancelled()' (cancelled runs leak instances too); window:\n{window}"
    )

    assert "instance_ttl_minutes" in ACTION_YML_TEXT, (
        "AC-11: action.yml must declare the 'instance_ttl_minutes' input"
    )
    input_decl = re.search(r"instance_ttl_minutes\s*:(.{0,300})", ACTION_YML_TEXT, re.DOTALL)
    assert input_decl and re.search(r'default:\s*"240"', input_decl.group(1)), (
        'AC-11: the instance_ttl_minutes input must declare default: "240"'
    )

    create_idx = _line_index_of("- name: Create Spot Instance")
    assert create_idx is not None, "AC-11: 'Create Spot Instance' step not found"
    wait_idx = _line_index_of("- name: Wait for Runner Online")
    assert wait_idx is not None, "AC-11: 'Wait for Runner Online' step not found (layout anchor)"
    create_block = "\n".join(ACTION_YML_LINES[create_idx:wait_idx])
    assert re.search(r"INSTANCE_TTL_MINUTES\s*:", create_block), (
        "AC-11: the Create Spot Instance step env must inject INSTANCE_TTL_MINUTES "
        "so user-data/cloud-side TTL has a single source of truth"
    )


def _step_block_containing(fragment):
    """Return the lines of the workflow step block containing a line with fragment.

    The block spans from the nearest preceding '- name:' line up to (excluding)
    the next '- name:' line or EOF. Returns None when no line contains fragment.
    """
    hit_idx = _line_index_of(fragment)
    if hit_idx is None:
        return None
    start_idx = hit_idx
    while start_idx > 0 and not re.match(r"^\s*-\s+name:", ACTION_YML_LINES[start_idx]):
        start_idx -= 1
    end_idx = start_idx + 1
    while end_idx < len(ACTION_YML_LINES) and not re.match(
        r"^\s*-\s+name:", ACTION_YML_LINES[end_idx]
    ):
        end_idx += 1
    return ACTION_YML_LINES[start_idx:end_idx]


def test_cleanup_captures_console_output_before_deletion():
    # Blueprint failure-forensics-console-output-v1:
    # AC-3: inside Cleanup on Failure, fetch-console-output.sh must run BEFORE
    #       cleanup-instance.sh (console output only survives until deletion).
    # AC-4: a follow-up upload-artifact@v4 step archives the console log on
    #       failure()/cancelled() and must not error when the log is absent.
    cleanup_block = _step_block_containing("- name: Cleanup on Failure")
    assert cleanup_block is not None, "AC-3: 'Cleanup on Failure' step not declared in action.yml"

    fetch_idx = next(
        (i for i, line in enumerate(cleanup_block) if "fetch-console-output.sh" in line), None
    )
    assert fetch_idx is not None, (
        "AC-3: the Cleanup on Failure step must invoke fetch-console-output.sh "
        "(forensics before destruction); step block:\n" + "\n".join(cleanup_block)
    )
    delete_idx = next(
        (i for i, line in enumerate(cleanup_block) if "cleanup-instance.sh" in line), None
    )
    assert delete_idx is not None, (
        "AC-3: the Cleanup on Failure step must still invoke cleanup-instance.sh; "
        "step block:\n" + "\n".join(cleanup_block)
    )
    assert fetch_idx < delete_idx, (
        "AC-3: fetch-console-output.sh must be invoked BEFORE cleanup-instance.sh -- "
        "console output is unrecoverable once the instance is deleted"
    )

    upload_block = _step_block_containing("actions/upload-artifact@v4")
    assert upload_block is not None, (
        "AC-4: action.yml must declare an upload-artifact@v4 step that archives "
        "the instance console log"
    )
    if_lines = [line for line in upload_block if re.match(r"^\s*if:", line)]
    assert any("failure()" in line and "cancelled()" in line for line in if_lines), (
        "AC-4: the upload step's if condition must cover both failure() and "
        "cancelled(); step block:\n" + "\n".join(upload_block)
    )
    assert re.search(r"(?im)^\s*path:.*(console\.log|console_log_file)", "\n".join(upload_block)), (
        "AC-4: upload-artifact 'with.path' must point at the CONSOLE_LOG_FILE "
        "location (console.log semantics); step block:\n" + "\n".join(upload_block)
    )
    assert re.search(r"(?im)^\s*if-no-files-found:\s*ignore\s*$", "\n".join(upload_block)), (
        "AC-4: upload-artifact must set if-no-files-found: ignore so neither the "
        "success path nor a forensic fetch failure produces an empty-artifact "
        "error; step block:\n" + "\n".join(upload_block)
    )

    # Outer-review Note-3: the artifact name must be identifiable per instance
    # (references the create-instance instance_id output).
    name_lines = [line for line in upload_block if re.match(r"(?i)^\s*name:", line)]
    assert name_lines and all(
        "instance_id" in line and "instance-console" in line for line in name_lines
    ), (
        "AC-4: the artifact name must reference steps.create-instance.outputs."
        "instance_id so the archive is identifiable per instance; step block:\n"
        + "\n".join(upload_block)
    )

    # Outer-review Note-4: the CONSOLE_LOG_FILE env literal and the upload
    # path literal must be exactly equal -- two hand-maintained copies that
    # can silently drift.
    env_match = re.search(
        r"(?im)^[ \t]*CONSOLE_LOG_FILE:[ \t]*(.+?)[ \t]*$", "\n".join(cleanup_block)
    )
    path_match = re.search(r"(?im)^[ \t]*path:[ \t]*(.+?)[ \t]*$", "\n".join(upload_block))
    assert env_match and path_match, (
        "AC-4: cleanup step must set CONSOLE_LOG_FILE env and the upload step "
        "must declare with.path; blocks:\n"
        + "\n".join(cleanup_block)
        + "\n---\n"
        + "\n".join(upload_block)
    )
    assert env_match.group(1) == path_match.group(1), (
        "AC-4: CONSOLE_LOG_FILE env and upload-artifact path literals must be "
        f"identical (got {env_match.group(1)!r} vs {path_match.group(1)!r}); "
        "drift loses the forensics artifact"
    )


def test_spot_inputs_and_env_wiring():
    # Blueprint spot-bid-params-v1 (spot-bid AC-6): action.yml must declare
    # the spot_price_multiplier / spot_duration inputs as bare string inputs
    # (defaults "1.2" / "1" preserve current behavior). Neither may declare
    # type: boolean -- GitHub coerces a boolean input's "0"/empty string to
    # false, which breaks downstream int parsing. The multiplier env must be
    # injected into the select step (it is consumed where prices are known);
    # the duration env into the create step (it rides the RunInstances call).
    for input_name, default_value in (
        ("spot_price_multiplier", "1.2"),
        ("spot_duration", "1"),
    ):
        decl_match = re.search(rf"(?m)^  {input_name}:\n((?:    .*\n?)*)", ACTION_YML_TEXT)
        assert decl_match is not None, (
            f"spot-bid AC-6: action.yml must declare the '{input_name}' input "
            "so callers can tune the spot bid strategy"
        )
        decl_block = decl_match.group(1)
        assert re.search(rf'default:\s*"{default_value}"', decl_block), (
            f"spot-bid AC-6: the '{input_name}' input must declare "
            f'default: "{default_value}" to preserve current behavior; '
            f"declaration block:\n{decl_block}"
        )
        assert not re.search(r"type:\s*boolean", decl_block), (
            f"spot-bid AC-6: the '{input_name}' input must NOT declare "
            'type: boolean -- GitHub coerces a boolean input\'s "0"/empty '
            "string to false, breaking downstream int parsing; "
            f"declaration block:\n{decl_block}"
        )

    select_block = _step_block_containing("- name: Select Optimal Instance")
    assert select_block is not None, (
        "spot-bid AC-6: 'Select Optimal Instance' step not declared in action.yml"
    )
    assert re.search(r"(?m)^\s*SPOT_PRICE_MULTIPLIER\s*:", "\n".join(select_block)), (
        "spot-bid AC-6: the Select Optimal Instance step env must inject "
        "SPOT_PRICE_MULTIPLIER (the multiplier is applied where price data "
        "lives, feeding both the main SPOT_PRICE_LIMIT and every retry "
        "candidate); step block:\n" + "\n".join(select_block)
    )

    create_block = _step_block_containing("- name: Create Spot Instance")
    assert create_block is not None, (
        "spot-bid AC-6: 'Create Spot Instance' step not declared in action.yml"
    )
    assert re.search(r"(?m)^\s*SPOT_DURATION\s*:", "\n".join(create_block)), (
        "spot-bid AC-6: the Create Spot Instance step env must inject "
        "SPOT_DURATION so the protection period reaches "
        "create_spot_instance.py's RunInstances call; "
        "step block:\n" + "\n".join(create_block)
    )


def test_spot_strategy_input_and_env_wiring():
    """spot-bid v2 AC-9: action.yml must declare the spot_strategy input
    (bare string, default "SpotWithPriceLimit") and wire SPOT_STRATEGY into
    ONLY the create step -- the strategy is consumed exclusively by
    create_spot_instance.py's RunInstances call, so the select step must stay
    byte-identical (select-side pricing/sorting is untouched by the strategy).
    """
    decl_match = re.search(r"(?m)^  spot_strategy:\n((?:    .*\n?)*)", ACTION_YML_TEXT)
    assert decl_match is not None, (
        "spot-bid v2 AC-9: action.yml must declare the 'spot_strategy' input "
        "so callers can explicitly opt into automatic bidding (SpotAsPriceGo)"
    )
    decl_block = decl_match.group(1)
    assert re.search(r'default:\s*"SpotWithPriceLimit"', decl_block), (
        "spot-bid v2 AC-9: the 'spot_strategy' input must declare "
        'default: "SpotWithPriceLimit"" '
        "(v1.4.0 behavior preserved on the default path; with no price limit "
        "the delta is AC-8(c)'s loud error_exit); "
        f"declaration block:\n{decl_block}"
    )
    assert not re.search(r"type:\s*boolean", decl_block), (
        "spot-bid v2 AC-9: the 'spot_strategy' input must NOT declare "
        "type: boolean -- GitHub coerces a boolean input to true/false, "
        "which cannot carry the SpotWithPriceLimit/SpotAsPriceGo enum; "
        f"declaration block:\n{decl_block}"
    )

    create_block = _step_block_containing("- name: Create Spot Instance")
    assert create_block is not None, (
        "spot-bid v2 AC-9: 'Create Spot Instance' step not declared in action.yml"
    )
    assert re.search(r"(?m)^\s*SPOT_STRATEGY\s*:", "\n".join(create_block)), (
        "spot-bid v2 AC-9: the Create Spot Instance step env must inject "
        "SPOT_STRATEGY so load_spot_strategy() in create_spot_instance.py can "
        "apply the v2 three-branch semantics on the RunInstances command; "
        "step block:\n" + "\n".join(create_block)
    )

    select_block = _step_block_containing("- name: Select Optimal Instance")
    assert select_block is not None, (
        "spot-bid v2 AC-9: 'Select Optimal Instance' step not declared in action.yml"
    )
    assert not re.search(r"(?m)^\s*SPOT_STRATEGY\s*:", "\n".join(select_block)), (
        "spot-bid v2 AC-9 (reverse pin): the Select Optimal Instance step env "
        "must NOT inject SPOT_STRATEGY -- the strategy is consumed only on "
        "the create side; select_instance.py stays zero-change (advisor prices "
        "still drive ranking and the candidates file); "
        "step block:\n" + "\n".join(select_block)
    )


# ---------------------------------------------------------------------------
# pr2-intervention-v1 (AC-4/AC-5/AC-6): auto-latest runner version with a
# proxy-scoped probe, watchdog window input, README/doc sync.
# ---------------------------------------------------------------------------

README_PATH = ACTION_YML_PATH.parent / "README.md"
README_CN_PATH = ACTION_YML_PATH.parent / "README.cn.md"


def test_runner_version_resolve_step_wiring():
    # pi AC-4: a Resolve Runner Version step must exist with the proxy env
    # trio (the probe runs INSIDE the proxy scope or VPC-hosted agents can
    # never reach github.com), redirect-based tag extraction, a loud
    # ::warning:: fallback, and its output consumed by the user-data step.
    step_idx = _line_index_of("- name: Resolve Runner Version")
    assert step_idx is not None, "pi AC-4: 'Resolve Runner Version' step not declared"

    step_block = "\n".join(ACTION_YML_LINES[step_idx : step_idx + 60])
    for env_key in ("http_proxy:", "https_proxy:", "no_proxy:"):
        assert env_key in step_block, (
            f"pi AC-4: the resolve step env must carry {env_key} (proxy scope)"
        )
    assert "releases/latest" in step_block and "-fsSI" in step_block, (
        "pi AC-4: the probe must be a HEAD against the releases/latest redirect"
    )
    assert re.search(r"::warning::", step_block), (
        "pi AC-4: probe failure must degrade LOUDLY (::warning::) before falling back"
    )
    assert "RUNNER_FALLBACK_VERSION" in step_block, (
        "pi AC-4: the fallback constant must be consumed by the resolve step"
    )
    assert 'echo "version=' in step_block, "pi AC-4: the step must write the version= output"
    assert len(re.findall(r'if ! LATEST="\$', step_block)) == 2, (
        "pi AC-4: BOTH probe attempts must be guarded (if ! LATEST=...) -- composite "
        "steps run bash -eo pipefail and an unguarded failing pipeline aborts the step "
        "before the fallback branch (dead-code degradation)"
    )
    assert "--noproxy '*'" in step_block, (
        "pi AC-4: the direct retry attempt (--noproxy '*') is missing -- a VPC-internal "
        "proxy is unreachable from GitHub-hosted setup runners and would poison the probe"
    )
    assert "INPUT_RUNNER_VERSION" in step_block, (
        "pi AC-4: the pin must be read through env (INPUT_RUNNER_VERSION), not interpolated"
    )
    run_body = step_block.split("run: |", 1)[-1] if "run: |" in step_block else step_block
    assert "${{ inputs.runner_version }}" not in run_body, (
        "pi AC-4: caller-controlled input must never be interpolated into the script "
        "body (env wiring in the env: block is the required route)"
    )
    for src in ("source=pin", "source=latest", "source=fallback"):
        assert src in step_block, f"pi AC-4: resolve step must emit {src} for provenance"

    gen_idx = _line_index_of("- name: Generate User Data")
    assert gen_idx is not None
    gen_block = "\n".join(ACTION_YML_LINES[gen_idx : gen_idx + 25])
    assert "steps.runner-version.outputs.version" in gen_block, (
        "pi AC-4: the user-data step must consume steps.runner-version.outputs.version"
    )
    assert "inputs.runner_version" not in gen_block, (
        "pi AC-4: the raw input must not flow into user-data (resolve step owns the default)"
    )

    # The input itself must have NO default (empty path must be reachable).
    decl = re.search(r"\n  runner_version:\n(.*?)(?=\n  [a-z_]+:)", ACTION_YML_TEXT, re.DOTALL)
    assert decl is not None, "pi AC-4: runner_version input not declared"
    assert not re.search(r"default:\s*\"", decl.group(1)), (
        "pi AC-4: runner_version must declare no default -- the resolve step "
        "owns the empty path (pinned/latest/fallback)"
    )

    # The watchdog window input must exist with NO default (unset must stay
    # reachable so the image pre-baked escape hatch survives) and reach user-data.
    win_decl = re.search(
        r"\n  watchdog_stop_window_seconds:\n(.*?)(?=\n  [a-z_]+:)", ACTION_YML_TEXT, re.DOTALL
    )
    assert win_decl is not None, "pi AC-5: watchdog_stop_window_seconds input not declared"
    assert not re.search(r"default\s*:", win_decl.group(1)), (
        "pi AC-5: watchdog_stop_window_seconds must declare NO default -- with a "
        "default, unset is unreachable and the action silently overrides any "
        "STOP_CONFIRMATIONS_REQUIRED pre-baked into a custom image"
    )
    assert re.search(r"(?i)max seconds of continuous", win_decl.group(1)), (
        "pi AC-5: the input description must state the max-window semantics"
    )
    assert (
        "WATCHDOG_STOP_WINDOW_SECONDS: ${{ inputs.watchdog_stop_window_seconds }}" in gen_block
    ), "pi AC-5: the user-data step env must inject the window input"


def test_no_pinned_runner_version_literals():
    # pi AC-4: the stale pin must be gone from all three sites (input
    # default, template fallback, generator sed pattern); the ONLY sanctioned
    # literal is the RUNNER_FALLBACK_VERSION declaration line.
    allowed = re.compile(r"RUNNER_FALLBACK_VERSION", re.IGNORECASE)
    version_literal = re.compile(r"\b2\.\d{3}\.\d+\b")

    for label, text in (
        ("action.yml", ACTION_YML_TEXT),
        (
            "templates/user-data.sh",
            (ACTION_YML_PATH.parent / "templates" / "user-data.sh").read_text(),
        ),
        (
            "scripts/generate-user-data.sh",
            (ACTION_YML_PATH.parent / "scripts" / "generate-user-data.sh").read_text(),
        ),
    ):
        for idx, line in enumerate(text.splitlines(), start=1):
            if version_literal.search(line) and not allowed.search(line):
                raise AssertionError(
                    f"pi AC-4: stale runner-version literal in {label}:{idx}: {line.strip()}"
                )

    fallback_sites = re.findall(r"RUNNER_FALLBACK_VERSION:\s*\"(\d+\.\d+\.\d+)\"", ACTION_YML_TEXT)
    assert len(fallback_sites) == 1, (
        f"pi AC-4: the RUNNER_FALLBACK_VERSION constant must be declared at exactly ONE "
        f"site; found {len(fallback_sites)}"
    )


def test_readme_stop_window_docs_synced():
    # pi AC-6: both READMEs document the new stop-verdict window (24/2min,
    # replacing the stale 6), carry the new input row, describe the
    # auto-latest runner_version semantics, and state the 420 default.
    readme = README_PATH.read_text(encoding="utf-8")
    readme_cn = README_CN_PATH.read_text(encoding="utf-8")

    assert "24 consecutive inactive probes" in readme, (
        "pi AC-6: README.md troubleshooting must say 24 consecutive inactive probes"
    )
    assert "24 次连续 inactive 探测" in readme_cn, (
        "pi AC-6: README.cn.md troubleshooting must carry the exact 24-probe window prose"
    )
    for doc, label in ((readme, "README.md"), (readme_cn, "README.cn.md")):
        assert "watchdog_stop_window_seconds" in doc, (
            f"pi AC-6: {label} must document the watchdog_stop_window_seconds input"
        )
        assert "runner_version" in doc, f"pi AC-6: {label} must document the runner_version input"
    assert re.search(r"(?i)max seconds of continuous", readme), (
        "pi AC-6: README.md must state the max-window semantics for the new input"
    )
    for doc, label in ((readme, "README.md"), (readme_cn, "README.cn.md")):
        assert re.search(r"runner_wait_timeout.*\| `420`", doc, re.DOTALL), (
            f"pi AC-6: {label} must carry the exact `420` default cell for runner_wait_timeout"
        )
        assert re.search(r"watchdog_stop_window_seconds.*unset", doc, re.DOTALL) or re.search(
            r"watchdog_stop_window_seconds.*未设置", doc, re.DOTALL
        ), f"pi AC-6: {label} must document the window input's unset semantics (no action default)"
        assert re.search(r"\| `runner_version_source`", doc), (
            f"pi AC-6: {label} must document the new runner_version_source output row"
        )


def test_user_data_b64_masked_and_no_dead_debug():
    # PR #3 companion: the Create step's env banner prints
    # USER_DATA_B64 verbatim; setSecret on the raw token cannot mask the
    # decodable derived form -- the generate step must register it with
    # ::add-mask:: BEFORE the create step runs.
    gen_idx = _line_index_of("- name: Generate User Data")
    assert gen_idx is not None
    mask_line = _line_index_of('echo "::add-mask::${USER_DATA_B64}"')
    out_line = _line_index_of('echo "user_data_b64=${USER_DATA_B64}" >> $GITHUB_OUTPUT')
    assert mask_line is not None, (
        "pr3 companion: generate step must emit ::add-mask:: for USER_DATA_B64"
    )
    assert out_line is not None and mask_line < out_line, (
        "pr3 companion: the mask registration must precede the output write"
    )
    # dead DEBUG export must stay gone
    assert "export DEBUG=true" not in ACTION_YML_TEXT, (
        "pr3 companion: the dead `export DEBUG=true` must not reappear (zero consumers)"
    )


def test_spot_runner_name_wiring_pinned():
    # PR #4 companion (psv4 C5/C6): the carried name rides SPOT_RUNNER_NAME in
    # BOTH consumer steps, and no step env block re-declares the injected
    # default name RUNNER_NAME (an assignment there is ignored on
    # self-hosted hosts -- the very defect this PR fixes).
    gen_idx = _line_index_of("- name: Generate User Data")
    wait_idx = _line_index_of("- name: Wait for Runner Online")
    assert gen_idx is not None and wait_idx is not None
    gen_block = "\n".join(ACTION_YML_LINES[gen_idx : gen_idx + 25])
    wait_block = "\n".join(ACTION_YML_LINES[wait_idx : wait_idx + 12])
    assert "SPOT_RUNNER_NAME: ${{ steps.runner-name.outputs.name }}" in gen_block, (
        "PR4 companion: the user-data step env must carry SPOT_RUNNER_NAME"
    )
    assert "SPOT_RUNNER_NAME: ${{ steps.runner-name.outputs.name }}" in wait_block, (
        "PR4 companion: the wait step env must carry SPOT_RUNNER_NAME"
    )
    import re as _re

    for block, label in ((gen_block, "user-data step"), (wait_block, "wait step")):
        assert not _re.search(r"(?m)^\s*RUNNER_NAME\s*:", block), (
            f"PR4 companion: the {label} env must NOT declare RUNNER_NAME -- the "
            "runner-injected default ignores the assignment (variables reference: "
            "'the assignment is ignored')"
        )
