"""Unit tests for scripts/select_instance.py (spot-bid AC-1/AC-2/AC-8).

TDD RED phase for the frozen intent blueprint
docs/intent-blueprints/spot-bid-params-v1.blueprint.md (Acceptance-Criteria ->
Test Mapping). Written before the implementation, so failures are expected
until the spot-bid parameterization lands:

- AC-1: new ``load_price_multiplier()`` env loader (SPOT_PRICE_MULTIPLIER).
- AC-2: ``:.3f`` formatting on both action points + sub-floor loud failure.
- AC-8: without the new env, current bid semantics are preserved.

The module is loaded from its script path; its main() is guarded by
__name__ == "__main__" so importing is side-effect free.
"""

import importlib.util
import re
import types
from pathlib import Path
from typing import IO, Any

import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "select_instance.py"

_spec = importlib.util.spec_from_file_location("select_instance", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None, f"cannot load module from {SCRIPT_PATH}"
select_instance = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(select_instance)

# Exactly three decimal places (SpotPriceLimit API constraint, blueprint C2).
THREE_DECIMALS_RE = re.compile(r"^\d+\.\d{3}$")

INSTANCE_TYPE = "ecs.c7.xlarge"

# Stub advisor rows use the field names main() consumes via get_field_value /
# filter_instances_for_specific_type. Values chosen so the 1.2x limit has more
# than 3 significant decimals, making .4f vs .3f observable:
#   0.3422/core  * 2 cores -> limit 0.82128  -> "0.821" at :.3f
#   0.2915/core  * 2 cores -> limit 0.6996   -> "0.700" at :.3f
#   0.00004/core * 8 cores -> limit 0.000384 < 0.0005 rounding floor


def _advisor_row(zone_id: str, price_per_core: str, cores: str) -> dict[str, str]:
    """Build one spot-instance-advisor JSON row with the fields main() reads."""
    return {
        "instanceTypeId": INSTANCE_TYPE,
        "zoneId": zone_id,
        "pricePerCore": price_per_core,
        "cpuCoreCount": cores,
    }


def _drive_main_with_stub(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    stub_rows: list[dict[str, str]],
) -> tuple[str, str]:
    """Run main() in specific-instance-type mode against a stubbed advisor query.

    Places a dummy (never executed) advisor binary in tmp_path, points the
    required env at fake credentials, maps zone suffixes k/j to VSwitch IDs,
    and replaces query_specific_instance_type with a stub returning
    ``stub_rows``. CANDIDATES_FILE temp files are redirected into tmp_path so
    tests can inspect them even when main() exits before printing
    CANDIDATES_FILE= (the AC-2 floor-guard cases).

    Returns (stdout, stderr) captured via capsys.
    """
    advisor = tmp_path / "spot-instance-advisor"
    advisor.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    advisor.chmod(0o755)

    monkeypatch.delenv("SPOT_PRICE_MULTIPLIER", raising=False)
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("ALIYUN_ACCESS_KEY_SECRET", "test-key-secret")
    monkeypatch.setenv("ALIYUN_REGION_ID", "cn-test")
    monkeypatch.setenv("SPOT_ADVISOR_BINARY", str(advisor))
    monkeypatch.setenv("ALIYUN_INSTANCE_TYPE", INSTANCE_TYPE)
    monkeypatch.setenv("ALIYUN_VSWITCH_ID_K", "vsw-zone-k")
    monkeypatch.setenv("ALIYUN_VSWITCH_ID_J", "vsw-zone-j")

    rows = [dict(row) for row in stub_rows]
    monkeypatch.setattr(
        select_instance, "query_specific_instance_type", lambda *args, **kwargs: rows
    )

    real_tempfile = select_instance.tempfile

    def _named_temp_file(*args: Any, **kwargs: Any) -> IO[str]:
        kwargs["dir"] = str(tmp_path)
        return real_tempfile.NamedTemporaryFile(*args, **kwargs)

    monkeypatch.setattr(
        select_instance, "tempfile", types.SimpleNamespace(NamedTemporaryFile=_named_temp_file)
    )

    select_instance.main()
    captured = capsys.readouterr()
    return captured.out, captured.err


def _output_value(stdout: str, key: str) -> str:
    """Return the value of the single ``KEY=value`` stdout line."""
    matches = [line for line in stdout.splitlines() if line.startswith(f"{key}=")]
    assert len(matches) == 1, f"expected exactly one {key}= line in stdout, got: {matches}"
    return matches[0].split("=", 1)[1]


def test_price_multiplier_default_and_custom(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """spot-bid AC-1: SPOT_PRICE_MULTIPLIER loading — defaults, custom, 0<m<1.

    Missing env and empty string fall back to the current-behavior default 1.2
    (the MIN_CPU/MAX_CPU empty-string pattern, NOT load_ttl_minutes' loud
    failure). Custom values parse through. A multiplier in (0, 1) is a legal,
    riskier bid choice: the loader must return it without exiting AND emit
    the stderr Warning (frozen granularity-note clause — asserted here at
    loader level, where the Warning is actually emitted).
    """
    monkeypatch.delenv("SPOT_PRICE_MULTIPLIER", raising=False)
    assert select_instance.load_price_multiplier() == 1.2

    monkeypatch.setenv("SPOT_PRICE_MULTIPLIER", "")
    assert select_instance.load_price_multiplier() == 1.2

    monkeypatch.setenv("SPOT_PRICE_MULTIPLIER", "1.5")
    assert select_instance.load_price_multiplier() == 1.5

    # 0<m<1 case: return value + no exception + stderr Warning (the frozen
    # AC-1 clause "SPOT_PRICE_MULTIPLIER='0.5' → exit 0、stderr 含 Warning").
    monkeypatch.setenv("SPOT_PRICE_MULTIPLIER", "0.5")
    assert select_instance.load_price_multiplier() == 0.5
    captured = capsys.readouterr()
    assert "Warning: SPOT_PRICE_MULTIPLIER is below 1.0" in captured.err


@pytest.mark.parametrize("raw_value", ["abc", "-1", "0", "nan", "inf", "-inf"])
def test_price_multiplier_invalid_fails_loudly(
    monkeypatch: pytest.MonkeyPatch, raw_value: str
) -> None:
    """spot-bid AC-1: non-numeric, <=0, or non-finite (nan/inf) input exits 1.

    Never silently clamps: error_exit prints to stderr and sys.exit(1).
    """
    monkeypatch.setenv("SPOT_PRICE_MULTIPLIER", raw_value)
    with pytest.raises(SystemExit) as excinfo:
        select_instance.load_price_multiplier()
    assert excinfo.value.code == 1


def test_spot_price_limit_formatted_to_three_decimals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """spot-bid AC-2: both formatting points and stderr debug lines use :.3f.

    Drives main() with a stubbed advisor query and asserts, via capsys
    dual-stream capture: the stdout SPOT_PRICE_LIMIT= line, every
    CANDIDATES_FILE row's 4th column (the per-row limit), and the stderr
    "Total price:" / "Spot price limit:" debug lines all carry exactly 3
    decimals.
    """
    stdout, stderr = _drive_main_with_stub(
        monkeypatch,
        tmp_path,
        capsys,
        [
            _advisor_row("cn-test-k", "0.3422", "2"),
            _advisor_row("cn-test-j", "0.2915", "2"),
        ],
    )

    # Main output point: 0.3422 * 2 * 1.2 = 0.82128 -> "0.821", not "0.8214".
    limit = _output_value(stdout, "SPOT_PRICE_LIMIT")
    assert limit == "0.821"
    assert THREE_DECIMALS_RE.match(limit)

    # Candidates-file point: every row's 4th column at 3 decimals.
    #   zone k: 0.3422 * 2 * 1.2 = 0.82128 -> "0.821"
    #   zone j: 0.2915 * 2 * 1.2 = 0.6996  -> "0.700"
    candidates_path = Path(_output_value(stdout, "CANDIDATES_FILE"))
    rows = candidates_path.read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2
    limits_by_zone = {row.split("|")[1]: row.split("|")[3] for row in rows}
    assert limits_by_zone == {"cn-test-k": "0.821", "cn-test-j": "0.700"}
    for zone, cand_limit in limits_by_zone.items():
        assert THREE_DECIMALS_RE.match(cand_limit), (
            f"spot-bid AC-2: candidates row for {zone} must carry a 3-decimal "
            f"limit, got {cand_limit!r}"
        )

    # stderr debug lines (the same two formatting sites): exactly 3 decimals.
    err_lines = stderr.splitlines()
    assert "  Total price: 0.684" in err_lines  # 0.3422 * 2
    assert "  Spot price limit: 0.821" in err_lines


def test_defaults_preserve_current_behavior(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """spot-bid AC-8: no new env -> multiplier default 1.2 semantics unchanged.

    Asserts the semantic default (price * cores * 1.2 formatted to 3
    decimals), not a .4f snapshot: .4f -> .3f is an enumerated intentional
    difference under AC-8, so only the multiplier semantics are pinned.
    """
    monkeypatch.delenv("SPOT_PRICE_MULTIPLIER", raising=False)
    assert select_instance.load_price_multiplier() == 1.2

    stdout, _stderr = _drive_main_with_stub(
        monkeypatch, tmp_path, capsys, [_advisor_row("cn-test-k", "0.3422", "2")]
    )
    expected_limit = f"{0.3422 * 2 * 1.2:.3f}"
    assert _output_value(stdout, "SPOT_PRICE_LIMIT") == expected_limit


@pytest.mark.parametrize(
    ("rows", "action_point"),
    [
        pytest.param(
            [
                _advisor_row("cn-test-k", "0.00004", "8"),
                _advisor_row("cn-test-j", "0.3422", "2"),
            ],
            "main-output",
            id="main-output-path",
        ),
        pytest.param(
            [
                _advisor_row("cn-test-k", "0.3422", "2"),
                _advisor_row("cn-test-j", "0.00004", "8"),
            ],
            "candidates-row",
            id="candidates-row-path",
        ),
    ],
)
def test_spot_price_limit_below_rounding_floor_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    rows: list[dict[str, str]],
    action_point: str,
) -> None:
    """spot-bid AC-2: any computed limit < 0.0005 must error_exit(1), never "0.000".

    Parameterized over both floor action points: the primary SPOT_PRICE_LIMIT
    output (tiny row selected) and an individual CANDIDATES_FILE row (normal
    row selected, tiny row among the candidates). In both cases main() must
    exit with code 1, and no candidates file may survive carrying a
    zero-formatted ("0.000") limit row — "绝不发送 0 限价".
    """
    # 0.00004 * 8 * 1.2 = 0.000384 < 0.0005 (would round to "0.000" at :.3f).
    with pytest.raises(SystemExit) as excinfo:
        _drive_main_with_stub(monkeypatch, tmp_path, capsys, rows)
    assert excinfo.value.code == 1

    # Direct pin of the no-half-write property: a sub-floor limit aborts
    # BEFORE the candidates file is created at all (AC-2 "绝不发送 0 限价").
    assert list(tmp_path.glob("*.txt")) == [], (
        f"spot-bid AC-2 ({action_point}): a candidates file was created "
        f"despite the sub-floor abort: {[p.name for p in tmp_path.glob('*.txt')]}"
    )
