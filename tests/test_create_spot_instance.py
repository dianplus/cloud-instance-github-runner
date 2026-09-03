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


# ---------------------------------------------------------------------------
# spot-bid blueprint (AC-3 / AC-4 / AC-5 / AC-8) -- TDD RED phase additions.
# Test names map 1:1 to the frozen "Acceptance-Criteria -> Test Mapping" rows
# in docs/intent-blueprints/spot-bid-params-v1.blueprint.md. The AC-9/AC-10
# tests above belong to earlier blueprints and are intentionally untouched.
# ---------------------------------------------------------------------------


# Optional env that could divert main() away from the path under test.
_OPTIONAL_CREATE_ENV = (
    "CANDIDATES_FILE",
    "SPOT_DURATION",
    "SPOT_PRICE_LIMIT",
    "ALIYUN_IMAGE_FAMILY",
    "ALIYUN_VSWITCH_ID",
    "USER_DATA",
    "USER_DATA_FILE",
    "ALIYUN_KEY_PAIR_NAME",
    "ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME",
    "INSTANCE_TYPE",
)

# Required env for main(); ALIYUN_IMAGE_ID is set (not ALIYUN_IMAGE_FAMILY) so
# the image resolution never issues a DescribeImageFromFamily call.
_REQUIRED_CREATE_ENV = {
    "ALIYUN_ACCESS_KEY_ID": "test-ak",
    "ALIYUN_ACCESS_KEY_SECRET": "test-sk",
    "ALIYUN_REGION_ID": "cn-test",
    "ALIYUN_VPC_ID": "vpc-test",
    "ALIYUN_SECURITY_GROUP_ID": "sg-test",
    "INSTANCE_NAME": "runner-test",
    "ALIYUN_IMAGE_ID": "m-test123",
    "INSTANCE_TTL_MINUTES": "60",
}


def _install_cli_stub(monkeypatch) -> list[list[str]]:
    """Replace the module's subprocess with a recording zero-network stub.

    Returns the argv log. ``aliyun --version`` and ``aliyun configure get``
    preflight calls succeed; RunInstances succeeds with an InstanceIdSets
    body; every other invocation succeeds silently.
    """
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(list(cmd))
        if "RunInstances" in cmd:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout='{"InstanceIdSets": {"InstanceIdSet": ["i-stub-spot-1"]}}',
                stderr="",
            )
        if "--version" in cmd:
            return subprocess.CompletedProcess(
                args=cmd, returncode=0, stdout="3.2.2-stub", stderr=""
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(create_spot_instance, "subprocess", types.SimpleNamespace(run=fake_run))
    return calls


def _prepare_main_env(monkeypatch, extra: dict[str, str] | None = None) -> None:
    """Hermetic env for driving main(): required vars set, optional vars that
    could divert the flow (candidates file / spot duration / image family /
    user data) cleared regardless of the host environment."""
    for name in _OPTIONAL_CREATE_ENV:
        monkeypatch.delenv(name, raising=False)
    for name, value in _REQUIRED_CREATE_ENV.items():
        monkeypatch.setenv(name, value)
    for name, value in (extra or {}).items():
        monkeypatch.setenv(name, value)


def _scrub_exported_credentials(monkeypatch) -> None:
    """main() writes ALIBABA_CLOUD_* credentials into os.environ; remove them
    (via monkeypatch, so originals are restored) so nothing leaks to later tests."""
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET", raising=False)


def _create_instance_call_arg_blocks() -> list[str]:
    """Argument text of every ``create_instance(...)`` call site in the script.

    The ``def create_instance(`` line is excluded. Balanced-paren scan of the
    raw source text (no call-site argument contains parens), per the blueprint
    granularity note that dual call-site pinning may resolve the source as
    text: exactly two call sites (candidate retry + single attempt) are
    expected, each of which must pass spot_duration through.
    """
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    blocks: list[str] = []
    for match in re.finditer(r"\bcreate_instance\(", source):
        if source[max(0, match.start() - 4) : match.start()] == "def ":
            continue
        depth = 0
        for offset in range(match.end() - 1, len(source)):
            char = source[offset]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(source[match.end() : offset])
                    break
    return blocks


@pytest.mark.parametrize("raw", ["2", "60", "abc", "1.5"])
def test_load_spot_duration_validation(monkeypatch, capsys, raw):
    # spot-bid AC-3: load_spot_duration() returns 1 when SPOT_DURATION is
    # unset or empty (API default per blueprint C6), passes 0/1 through as
    # int, and fails loudly (SystemExit code 1, stderr mentions "hours" and
    # "only 0 or 1") for any other value -- never silently clamps.
    load_spot_duration = create_spot_instance.load_spot_duration  # AttributeError => RED

    # Env missing -> default 1.
    monkeypatch.delenv("SPOT_DURATION", raising=False)
    assert load_spot_duration() == 1, "spot-bid AC-3: unset SPOT_DURATION must default to 1"

    # Empty string falls back to the default (select_instance env pattern),
    # NOT the loud-failure shape of load_ttl_minutes.
    monkeypatch.setenv("SPOT_DURATION", "")
    assert load_spot_duration() == 1, "spot-bid AC-3: empty SPOT_DURATION must fall back to 1"

    # Legal domain {0, 1} passes through as int.
    monkeypatch.setenv("SPOT_DURATION", "0")
    assert load_spot_duration() == 0, "spot-bid AC-3: '0' (no protection period) must pass through"
    monkeypatch.setenv("SPOT_DURATION", "1")
    assert load_spot_duration() == 1, "spot-bid AC-3: '1' (1-hour protection) must pass through"

    # Out-of-domain / non-int values must error_exit (exit code 1).
    monkeypatch.setenv("SPOT_DURATION", raw)
    with pytest.raises(SystemExit) as excinfo:
        load_spot_duration()
    assert excinfo.value.code == 1, (
        f"spot-bid AC-3: invalid SPOT_DURATION {raw!r} must exit with code 1, "
        f"got {excinfo.value.code!r}"
    )
    stderr = capsys.readouterr().err
    assert "hours" in stderr, (
        f"spot-bid AC-3: error message must state the unit (hours); got: {stderr!r}"
    )
    assert "only 0 or 1" in stderr, (
        f"spot-bid AC-3: error message must state the accepted domain (only 0 or 1); "
        f"got: {stderr!r}"
    )


@pytest.mark.parametrize(
    ("spot_duration", "expected_value"),
    [(1, "1"), (0, "0"), (None, None)],
)
def test_run_instances_command_includes_spot_duration(
    monkeypatch, tmp_path, spot_duration, expected_value
):
    # spot-bid AC-4 (unit branch): create_instance() gains a
    # spot_duration: int | None = None parameter -- non-None appends
    # --SpotDuration <n> to the RunInstances command, None omits the flag.
    calls = _install_cli_stub(monkeypatch)

    # system_disk_category is passed explicitly so create_instance never falls
    # back to the real get_supported_disk_category network call.
    exit_code, _response = create_spot_instance.create_instance(
        region_id="cn-test",
        image_id="m-test123",
        instance_type="ecs.test-large",
        security_group_id="sg-test",
        vswitch_id="vsw-test",
        instance_name="runner-test",
        system_disk_category="cloud_essd",
        spot_duration=spot_duration,
    )
    assert exit_code == 0, f"stubbed RunInstances should succeed; got {exit_code}"

    cmd = calls[-1]
    assert "RunInstances" in cmd, f"expected a RunInstances call; got:\n{cmd}"
    if expected_value is None:
        assert "--SpotDuration" not in cmd, (
            f"spot-bid AC-4: spot_duration=None must not add --SpotDuration; cmd:\n{cmd}"
        )
    else:
        assert "--SpotDuration" in cmd, (
            f"spot-bid AC-4: spot_duration={spot_duration} must add --SpotDuration; cmd:\n{cmd}"
        )
        flag_idx = cmd.index("--SpotDuration")
        assert cmd[flag_idx + 1] == expected_value, (
            f"spot-bid AC-4: --SpotDuration must be followed by {expected_value!r}; "
            f"got {cmd[flag_idx + 1]!r}; cmd:\n{cmd}"
        )

    # spot-bid AC-4 dual call-site pinning (a): both create_instance call
    # sites in the script source (candidate retry + single attempt) must pass
    # the validated spot_duration through as an argument.
    call_blocks = _create_instance_call_arg_blocks()
    assert len(call_blocks) == 2, (
        "spot-bid AC-4(a): expected exactly two create_instance( call sites "
        f"(candidate retry + single attempt); found {len(call_blocks)}"
    )
    for index, block in enumerate(call_blocks, 1):
        assert re.search(r"\bspot_duration\s*=", block), (
            f"spot-bid AC-4(a): call site #{index} must pass spot_duration=...; block:\n{block}"
        )

    # spot-bid AC-4 dual call-site pinning (b): drive main() through the
    # CANDIDATES_FILE retry path (3 candidates, zones suffixed -a) and pin
    # --SpotDuration on the emitted RunInstances argv.
    candidates_file = tmp_path / "candidates.txt"
    candidates_file.write_text(
        "ecs.test-a|cn-test-a|vsw-xxx|0.1234|8\n"
        "ecs.test-b|cn-test-a|vsw-xxx|0.2345|8\n"
        "ecs.test-c|cn-test-a|vsw-xxx|0.1234|8\n",
        encoding="utf-8",
    )
    _prepare_main_env(
        monkeypatch,
        extra={"CANDIDATES_FILE": str(candidates_file), "ALIYUN_VSWITCH_ID_A": "vsw-xxx-a"},
    )
    calls_before = len(calls)
    # main() exits 0 as soon as the first candidate's RunInstances succeeds.
    with pytest.raises(SystemExit) as excinfo:
        create_spot_instance.main()
    assert excinfo.value.code == 0, (
        f"stubbed first candidate must create successfully; exit code {excinfo.value.code!r}"
    )

    # CLI preflights really went through the stub (main() ran end to end).
    later_calls = calls[calls_before:]
    assert any(c[:2] == ["aliyun", "--version"] for c in later_calls)
    assert any(c[:3] == ["aliyun", "configure", "get"] for c in later_calls)

    retry_cmds = [c for c in later_calls if "RunInstances" in c]
    assert retry_cmds, "spot-bid AC-4(b): retry path must issue a RunInstances call"
    retry_cmd = retry_cmds[0]
    assert "--SpotDuration" in retry_cmd, (
        "spot-bid AC-4(b): candidates retry path RunInstances must carry "
        f"--SpotDuration; argv:\n{retry_cmd}"
    )
    retry_idx = retry_cmd.index("--SpotDuration")
    assert retry_cmd[retry_idx + 1] == "1", (
        "spot-bid AC-4(b): with SPOT_DURATION unset the retry path must send the "
        f"default 1; got {retry_cmd[retry_idx + 1]!r}; argv:\n{retry_cmd}"
    )

    _scrub_exported_credentials(monkeypatch)


def test_spot_duration_defaults_to_one_without_env(monkeypatch, capsys):
    # spot-bid AC-8 (create side): with neither CANDIDATES_FILE nor
    # SPOT_DURATION set, the single-attempt path makes the API default
    # explicit (--SpotDuration 1, blueprint C6) and the startup banner
    # reports "Spot Duration: 1 hour(s)".
    calls = _install_cli_stub(monkeypatch)
    _prepare_main_env(
        monkeypatch,
        extra={"INSTANCE_TYPE": "ecs.test-large", "ALIYUN_VSWITCH_ID": "vsw-test"},
    )

    with pytest.raises(SystemExit) as excinfo:
        create_spot_instance.main()
    assert excinfo.value.code == 0, (
        f"stubbed single-attempt creation must succeed; exit code {excinfo.value.code!r}"
    )

    run_cmds = [c for c in calls if "RunInstances" in c]
    assert run_cmds, "spot-bid AC-8: single path must issue a RunInstances call"
    single_cmd = run_cmds[0]
    assert "--SpotDuration" in single_cmd, (
        "spot-bid AC-8: single-attempt RunInstances must carry the explicit "
        f"default --SpotDuration 1; argv:\n{single_cmd}"
    )
    flag_idx = single_cmd.index("--SpotDuration")
    assert single_cmd[flag_idx + 1] == "1", (
        f"spot-bid AC-8: expected --SpotDuration 1; got {single_cmd[flag_idx + 1]!r}; "
        f"argv:\n{single_cmd}"
    )

    stderr = capsys.readouterr().err
    assert "Spot Duration: 1 hour(s)" in stderr, (
        f"spot-bid AC-8: startup banner must report the protection period; stderr:\n{stderr}"
    )

    _scrub_exported_credentials(monkeypatch)


def test_dead_price_limit_helper_removed():
    # spot-bid AC-5: calculate_spot_price_limit() is dead code (no caller,
    # the third hardcoded 1.2x site) and must be deleted outright, not
    # parameterized in place.
    assert not hasattr(create_spot_instance, "calculate_spot_price_limit"), (
        "spot-bid AC-5: dead helper calculate_spot_price_limit() must be removed "
        "from create_spot_instance.py"
    )


# ---------------------------------------------------------------------------
# spot-bid blueprint v2 (AC-10 / AC-11) -- TDD RED phase additions.
# Test names map 1:1 to the frozen "Acceptance-Criteria -> Test Mapping" rows
# in docs/intent-blueprints/spot-bid-params-v1.blueprint.md (v2 layer:
# AC-8(c)(d) behavior + AC-9..AC-12 pending). The v1-layer spot-bid tests
# above are delivered v1.4.0 regression anchors and stay untouched.
# ---------------------------------------------------------------------------


def _prepare_spot_strategy_env(monkeypatch, extra: dict[str, str] | None = None) -> None:
    """_prepare_main_env plus an explicit SPOT_STRATEGY scrub.

    The pre-v2 _OPTIONAL_CREATE_ENV list predates SPOT_STRATEGY, so existing
    tests are left untouched; v2 tests clear the var here first and let
    ``extra`` set it only when the case under test needs an explicit strategy
    (unset/empty is itself a distinct branch under AC-10).
    """
    monkeypatch.delenv("SPOT_STRATEGY", raising=False)
    _prepare_main_env(monkeypatch, extra=extra)


@pytest.mark.parametrize("invalid", ["NoSpot", "abc", "spot"])
def test_load_spot_strategy_validation(monkeypatch, capsys, invalid):
    # spot-bid AC-10: load_spot_strategy() returns None when SPOT_STRATEGY is
    # unset or empty (keep the v1.4.0 auto fallback), passes the two canonical
    # enum names through verbatim, normalizes case-insensitive input to the
    # canonical enum names, and fails loudly (SystemExit code 1, stderr
    # listing BOTH legal values) for anything else -- NoSpot is a blueprint
    # non-goal and must be rejected, never silently coerced.
    load_spot_strategy = create_spot_instance.load_spot_strategy  # AttributeError => RED

    # Env missing -> None (strategy resolution falls back to the auto logic).
    monkeypatch.delenv("SPOT_STRATEGY", raising=False)
    assert load_spot_strategy() is None, (
        "spot-bid AC-10: unset SPOT_STRATEGY must yield None (auto fallback)"
    )

    # Empty string is the caller actively expressing no choice -> None.
    monkeypatch.setenv("SPOT_STRATEGY", "")
    assert load_spot_strategy() is None, (
        "spot-bid AC-10: empty SPOT_STRATEGY must yield None (auto fallback)"
    )

    # Canonical enum names pass through unchanged.
    monkeypatch.setenv("SPOT_STRATEGY", "SpotWithPriceLimit")
    assert load_spot_strategy() == "SpotWithPriceLimit", (
        "spot-bid AC-10: canonical SpotWithPriceLimit must pass through verbatim"
    )
    monkeypatch.setenv("SPOT_STRATEGY", "SpotAsPriceGo")
    assert load_spot_strategy() == "SpotAsPriceGo", (
        "spot-bid AC-10: canonical SpotAsPriceGo must pass through verbatim"
    )

    # Case-insensitive matching normalizes to the canonical enum names.
    monkeypatch.setenv("SPOT_STRATEGY", "spotaspricego")
    assert load_spot_strategy() == "SpotAsPriceGo", (
        "spot-bid AC-10: 'spotaspricego' must normalize to SpotAsPriceGo"
    )
    monkeypatch.setenv("SPOT_STRATEGY", "SPOTWithPriceLimit")
    assert load_spot_strategy() == "SpotWithPriceLimit", (
        "spot-bid AC-10: 'SPOTWithPriceLimit' must normalize to SpotWithPriceLimit"
    )

    # Any other value must error_exit with BOTH legal values in the message.
    monkeypatch.setenv("SPOT_STRATEGY", invalid)
    with pytest.raises(SystemExit) as excinfo:
        load_spot_strategy()
    assert excinfo.value.code == 1, (
        f"spot-bid AC-10: invalid SPOT_STRATEGY {invalid!r} must exit with code 1, "
        f"got {excinfo.value.code!r}"
    )
    stderr = capsys.readouterr().err
    assert "SpotWithPriceLimit" in stderr, (
        f"spot-bid AC-10: error message must list SpotWithPriceLimit; got: {stderr!r}"
    )
    assert "SpotAsPriceGo" in stderr, (
        f"spot-bid AC-10: error message must list SpotAsPriceGo; got: {stderr!r}"
    )


@pytest.mark.parametrize("path", ["retry", "single"])
def test_spot_as_price_go_overrides_price_limit(monkeypatch, tmp_path, capsys, path):
    # spot-bid AC-11 (ASG branch): explicit SpotAsPriceGo wins over every
    # price-limit source on BOTH creation paths -- RunInstances carries
    # --SpotStrategy SpotAsPriceGo and NOT --SpotPriceLimit, even though a
    # limit exists on the path under test (retry: candidate row column 4;
    # single: SPOT_PRICE_LIMIT env). --SpotDuration 1 is strategy-independent
    # and must stay. This test also carries the ASG-branch banner: the enum
    # name is printed and the Spot Price Limit line is NOT.
    calls = _install_cli_stub(monkeypatch)
    if path == "retry":
        candidates_file = tmp_path / "candidates.txt"
        candidates_file.write_text(
            "ecs.test-a|cn-test-a|vsw-xxx|0.1234|8\n"
            "ecs.test-b|cn-test-a|vsw-xxx|0.2345|8\n"
            "ecs.test-c|cn-test-a|vsw-xxx|0.1234|8\n",
            encoding="utf-8",
        )
        _prepare_spot_strategy_env(
            monkeypatch,
            extra={
                "CANDIDATES_FILE": str(candidates_file),
                "ALIYUN_VSWITCH_ID_A": "vsw-xxx-a",
                "SPOT_STRATEGY": "SpotAsPriceGo",
            },
        )
    else:
        _prepare_spot_strategy_env(
            monkeypatch,
            extra={
                "INSTANCE_TYPE": "ecs.test-large",
                "ALIYUN_VSWITCH_ID": "vsw-test",
                "SPOT_PRICE_LIMIT": "0.4321",
                "SPOT_STRATEGY": "SpotAsPriceGo",
            },
        )

    with pytest.raises(SystemExit) as excinfo:
        create_spot_instance.main()
    assert excinfo.value.code == 0, (
        f"stubbed creation must succeed; exit code {excinfo.value.code!r}"
    )

    run_cmds = [c for c in calls if "RunInstances" in c]
    assert run_cmds, f"spot-bid AC-11: {path} path must issue a RunInstances call"
    cmd = run_cmds[0]
    assert "--SpotStrategy" in cmd, f"spot-bid AC-11: argv must carry --SpotStrategy; argv:\n{cmd}"
    flag_idx = cmd.index("--SpotStrategy")
    assert cmd[flag_idx + 1] == "SpotAsPriceGo", (
        f"spot-bid AC-11: explicit strategy must be sent as the enum name; got "
        f"{cmd[flag_idx + 1]!r}; argv:\n{cmd}"
    )
    assert "--SpotPriceLimit" not in cmd, (
        "spot-bid AC-11: SpotAsPriceGo must NOT send --SpotPriceLimit (the limit "
        f"source on this path exists but must not join the bid); argv:\n{cmd}"
    )
    assert "--SpotDuration" in cmd, (
        f"spot-bid AC-11: --SpotDuration is strategy-independent and must stay; argv:\n{cmd}"
    )
    duration_idx = cmd.index("--SpotDuration")
    assert cmd[duration_idx + 1] == "1", (
        f"spot-bid AC-11: expected --SpotDuration 1; got {cmd[duration_idx + 1]!r}; argv:\n{cmd}"
    )

    # ASG-branch banner: enum name printed; the Spot Price Limit line is
    # omitted under SpotAsPriceGo even though a limit source exists.
    stderr = capsys.readouterr().err
    assert "Spot Strategy: SpotAsPriceGo" in stderr, (
        f"spot-bid AC-11: banner must report the explicit enum name; stderr:\n{stderr}"
    )
    assert "Spot Price Limit:" not in stderr, (
        "spot-bid AC-11: Spot Price Limit banner line must be omitted under "
        f"SpotAsPriceGo; stderr:\n{stderr}"
    )

    _scrub_exported_credentials(monkeypatch)


@pytest.mark.parametrize("path", ["retry", "single"])
def test_explicit_price_limit_without_limit_fails_loudly(monkeypatch, tmp_path, capsys, path):
    # spot-bid AC-11 (WPL guard): explicit SpotWithPriceLimit with an EMPTY
    # limit source for the creation at hand (retry: current candidate row
    # column 4 empty; single: SPOT_PRICE_LIMIT unset) must error_exit with
    # code 1 -- never silently switch to SpotAsPriceGo. The happy path at the
    # end also carries the explicit-WPL banner: valid limit -> both flags on
    # argv plus the enum name on the banner.
    calls = _install_cli_stub(monkeypatch)
    if path == "retry":
        empty_limit_candidates = tmp_path / "candidates-empty-limit.txt"
        empty_limit_candidates.write_text(
            "ecs.test-a|cn-test-a|vsw-xxx||8\n",
            encoding="utf-8",
        )
        _prepare_spot_strategy_env(
            monkeypatch,
            extra={
                "CANDIDATES_FILE": str(empty_limit_candidates),
                "ALIYUN_VSWITCH_ID_A": "vsw-xxx-a",
                "SPOT_STRATEGY": "SpotWithPriceLimit",
            },
        )
    else:
        _prepare_spot_strategy_env(
            monkeypatch,
            extra={
                "INSTANCE_TYPE": "ecs.test-large",
                "ALIYUN_VSWITCH_ID": "vsw-test",
                "SPOT_STRATEGY": "SpotWithPriceLimit",
            },
        )

    with pytest.raises(SystemExit) as excinfo:
        create_spot_instance.main()
    assert excinfo.value.code == 1, (
        f"spot-bid AC-11: explicit SpotWithPriceLimit with an empty limit source "
        f"({path} path) must exit with code 1, got {excinfo.value.code!r}"
    )
    assert not any("RunInstances" in c and "SpotAsPriceGo" in c for c in calls), (
        "spot-bid AC-11: the empty-limit guard must never fall through to a "
        f"silent SpotAsPriceGo creation; calls:\n{calls}"
    )
    stderr = capsys.readouterr().err
    expected_origin = (
        "candidates file" if path == "retry" else "SPOT_PRICE_LIMIT environment variable"
    )
    assert expected_origin in stderr, (
        f"spot-bid AC-11: the guard error must name the limit source "
        f"({expected_origin!r}) for the {path} path; stderr:\n{stderr}"
    )

    # Happy path (explicit-WPL banner carrier, the action-default main path):
    # a valid limit restores the full SpotWithPriceLimit shape.
    if path == "retry":
        priced_candidates = tmp_path / "candidates-priced.txt"
        priced_candidates.write_text(
            "ecs.test-ok|cn-test-a|vsw-xxx|0.1234|8\n",
            encoding="utf-8",
        )
        _prepare_spot_strategy_env(
            monkeypatch,
            extra={
                "CANDIDATES_FILE": str(priced_candidates),
                "ALIYUN_VSWITCH_ID_A": "vsw-xxx-a",
                "SPOT_STRATEGY": "SpotWithPriceLimit",
            },
        )
    else:
        _prepare_spot_strategy_env(
            monkeypatch,
            extra={
                "INSTANCE_TYPE": "ecs.test-large",
                "ALIYUN_VSWITCH_ID": "vsw-test",
                "SPOT_PRICE_LIMIT": "0.4321",
                "SPOT_STRATEGY": "SpotWithPriceLimit",
            },
        )

    with pytest.raises(SystemExit) as excinfo:
        create_spot_instance.main()
    assert excinfo.value.code == 0, (
        f"stubbed creation must succeed; exit code {excinfo.value.code!r}"
    )

    run_cmds = [c for c in calls if "RunInstances" in c]
    assert run_cmds, f"spot-bid AC-11: {path} happy path must issue a RunInstances call"
    cmd = run_cmds[-1]
    assert "--SpotStrategy" in cmd, f"spot-bid AC-11: argv must carry --SpotStrategy; argv:\n{cmd}"
    flag_idx = cmd.index("--SpotStrategy")
    assert cmd[flag_idx + 1] == "SpotWithPriceLimit", (
        f"spot-bid AC-11: explicit strategy must be sent as the enum name; got "
        f"{cmd[flag_idx + 1]!r}; argv:\n{cmd}"
    )
    assert "--SpotPriceLimit" in cmd, (
        "spot-bid AC-11: SpotWithPriceLimit with a valid limit must carry both "
        f"flags (--SpotStrategy + --SpotPriceLimit); argv:\n{cmd}"
    )

    stderr = capsys.readouterr().err
    assert "Spot Strategy: SpotWithPriceLimit" in stderr, (
        f"spot-bid AC-11: banner must report the explicit enum name; stderr:\n{stderr}"
    )

    _scrub_exported_credentials(monkeypatch)


@pytest.mark.parametrize(
    ("row_limit", "expected_strategy"),
    [("0.1234", "SpotWithPriceLimit"), ("", "SpotAsPriceGo")],
)
def test_default_strategy_fallback_unchanged(
    monkeypatch, tmp_path, capsys, row_limit, expected_strategy
):
    # spot-bid AC-11 (unset branch, v1.4.0 regression): with SPOT_STRATEGY not
    # set, the retry path keeps the pre-v2 fallback exactly -- candidate row
    # with a limit -> SpotWithPriceLimit + --SpotPriceLimit carrying the row
    # value; row with an empty limit column -> SpotAsPriceGo with no limit
    # flag (the v1.4.0 silent fallback is deliberately preserved). This test
    # also carries the unset-branch banner: the literal value "auto".
    calls = _install_cli_stub(monkeypatch)
    candidates_file = tmp_path / "candidates.txt"
    candidates_file.write_text(
        f"ecs.test-a|cn-test-a|vsw-xxx|{row_limit}|8\n",
        encoding="utf-8",
    )
    _prepare_spot_strategy_env(
        monkeypatch,
        extra={"CANDIDATES_FILE": str(candidates_file), "ALIYUN_VSWITCH_ID_A": "vsw-xxx-a"},
    )

    with pytest.raises(SystemExit) as excinfo:
        create_spot_instance.main()
    assert excinfo.value.code == 0, (
        f"stubbed fallback creation must succeed; exit code {excinfo.value.code!r}"
    )

    run_cmds = [c for c in calls if "RunInstances" in c]
    assert run_cmds, "spot-bid AC-11: retry path must issue a RunInstances call"
    cmd = run_cmds[0]
    assert "--SpotStrategy" in cmd, f"spot-bid AC-11: argv must carry --SpotStrategy; argv:\n{cmd}"
    flag_idx = cmd.index("--SpotStrategy")
    assert cmd[flag_idx + 1] == expected_strategy, (
        f"spot-bid AC-11: unset SPOT_STRATEGY must keep the v1.4.0 fallback "
        f"(row limit {row_limit!r} -> {expected_strategy}); got "
        f"{cmd[flag_idx + 1]!r}; argv:\n{cmd}"
    )
    if expected_strategy == "SpotWithPriceLimit":
        assert "--SpotPriceLimit" in cmd, (
            f"spot-bid AC-11: fallback WPL must carry the row's limit; argv:\n{cmd}"
        )
        limit_idx = cmd.index("--SpotPriceLimit")
        assert cmd[limit_idx + 1] == row_limit, (
            f"spot-bid AC-11: --SpotPriceLimit must use the candidate row value "
            f"{row_limit!r}; got {cmd[limit_idx + 1]!r}; argv:\n{cmd}"
        )
    else:
        assert "--SpotPriceLimit" not in cmd, (
            "spot-bid AC-11: empty row limit must keep the v1.4.0 silent fallback "
            f"to SpotAsPriceGo with no limit flag; argv:\n{cmd}"
        )

    # Unset-branch banner: exactly the two-word literal form -- the enum is
    # resolved per creation, but the banner prints the literal "auto" with no
    # parenthetical annotation.
    stderr = capsys.readouterr().err
    assert re.search(r"^Spot Strategy: auto$", stderr, re.MULTILINE), (
        "spot-bid AC-11: unset-strategy banner must be exactly 'Spot Strategy: auto' "
        f"(literal value, no annotations); stderr:\n{stderr}"
    )

    _scrub_exported_credentials(monkeypatch)
