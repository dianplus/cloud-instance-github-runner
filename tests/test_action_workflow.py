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
    env_match = re.search(r"(?im)^\s*CONSOLE_LOG_FILE:\s*(\S+)", "\n".join(cleanup_block))
    path_match = re.search(r"(?im)^\s*path:\s*(\S+)", "\n".join(upload_block))
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
