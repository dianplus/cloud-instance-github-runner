"""Unit tests for scripts/create_spot_instance.py (AC-9 / AC-10).

The module is loaded from its script path; its main() is guarded by
__name__ == "__main__" so importing is side-effect free.
"""

import importlib.util
import random
import re
import subprocess
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "create_spot_instance.py"

_spec = importlib.util.spec_from_file_location("create_spot_instance", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None, f"cannot load module from {SCRIPT_PATH}"
create_spot_instance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(create_spot_instance)

ISO_Z_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:00Z$")


def test_auto_release_time_format_and_minimum():
    # AC-9: ttl=240 -> ISO8601 UTC with seconds :00, equal to now + ttl
    # truncated to the minute (tolerance 1 minute).
    release_time = create_spot_instance.compute_auto_release_time(
        ttl_minutes=240, now_epoch=1789000000.0
    )
    assert ISO_Z_RE.match(release_time), (
        "AC-9: compute_auto_release_time must return yyyy-MM-ddTHH:mm:00Z "
        f"(seconds truncated to 00); got {release_time!r}"
    )
    actual = datetime.fromisoformat(release_time.replace("Z", "+00:00"))
    expected = datetime.fromtimestamp(1789000000.0 + 240 * 60, tz=timezone.utc)
    delta_seconds = abs((actual - expected).total_seconds())
    assert delta_seconds <= 60, (
        f"AC-9: release time must equal now + 240 minutes (minute-truncated); "
        f"got {actual.isoformat()} vs expected {expected.isoformat()} "
        f"(delta {delta_seconds}s)"
    )

    # AC-9: TTL below the 30-minute floor must fail loudly (error_exit ->
    # SystemExit), never silently clamp.
    with pytest.raises(SystemExit):
        create_spot_instance.compute_auto_release_time(ttl_minutes=29, now_epoch=1789000000.0)

    # Boundary: exactly 30 minutes is legal.
    boundary = create_spot_instance.compute_auto_release_time(
        ttl_minutes=30, now_epoch=1789000000.0
    )
    assert ISO_Z_RE.match(boundary), (
        f"AC-9: ttl=30 is the legal minimum; expected ISO Z timestamp, got {boundary!r}"
    )


def test_run_instances_command_includes_auto_release_time(monkeypatch):
    # AC-10: RunInstances must carry --AutoReleaseTime <computed ISO value>.
    captured = {}

    def fake_run(cmd, **_kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout='{"InstanceIdSets": {"InstanceIdSet": ["i-x"]}}',
            stderr="",
        )

    monkeypatch.setattr(create_spot_instance, "subprocess", types.SimpleNamespace(run=fake_run))

    # system_disk_category is passed explicitly so create_instance never falls
    # back to the real get_supported_disk_category network call.
    exit_code, response = create_spot_instance.create_instance(
        region_id="cn-test",
        image_id="img",
        instance_type="t",
        security_group_id="sg",
        vswitch_id="vsw",
        instance_name="n",
        system_disk_category="cloud_essd",
    )

    assert exit_code == 0, f"stubbed RunInstances should succeed; got {exit_code}, {response}"
    cmd = captured["cmd"]
    assert "--AutoReleaseTime" in cmd, (
        "AC-10: RunInstances command must include --AutoReleaseTime (cloud-side "
        f"billing backstop); cmd:\n{cmd}"
    )
    flag_idx = cmd.index("--AutoReleaseTime")
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", cmd[flag_idx + 1]), (
        "AC-10: --AutoReleaseTime must be followed by an ISO8601 UTC value; "
        f"got {cmd[flag_idx + 1]!r}; cmd:\n{cmd}"
    )


def test_auto_release_time_random_boundary_property():
    # Boundary property of the ceil-to-minute computation: for ANY fractional
    # now and legal ttl, the release time is never earlier than now + ttl
    # minutes (the 30-minute API minimum holds even at ttl=30 with a nonzero
    # second fraction) and never more than one minute beyond it.
    # Seeded regression carrier for the one-off 200k-sample outer-review check.
    rng = random.Random(20260821)
    for _ in range(20_000):
        now = rng.uniform(1_700_000_000, 1_900_000_000)
        ttl = rng.choice((30, 31, 240, 480))
        release_time = create_spot_instance.compute_auto_release_time(ttl, now)
        assert ISO_Z_RE.match(release_time), f"bad format {release_time!r} (now={now})"
        ts = datetime.fromisoformat(release_time.replace("Z", "+00:00")).timestamp()
        delta = ts - now
        assert ttl * 60 <= delta < ttl * 60 + 60, (
            f"release must be within [now+ttl, now+ttl+60s); "
            f"got delta={delta:.1f}s for ttl={ttl}, now={now}, rt={release_time}"
        )
