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
