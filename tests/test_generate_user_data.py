"""Emergent-coupling contract: generate-user-data.sh's sed injection patterns
must keep matching templates/user-data.sh's variable-default lines.

generate-user-data.sh rewrites exact `${VAR:-...}` default lines in the
template; if either side drifts (rename, reformat, reordering), injection
silently stops and the instance boots with empty credentials. This test runs
the real generator with fake values and locks the contract in.
"""

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

FAKE_VALUES = {
    "RUNNER_REGISTRATION_TOKEN": "ABCD1234fake_token_for_test",
    "GITHUB_REPOSITORY": "octo-org/example-repo",
    "RUNNER_NAME": "ci-runner-amd64-spot-1787310000-1234",
    "RUNNER_VERSION": "2.330.0",
    "HTTP_PROXY": "http://proxy.example.com:8080",
    "HTTPS_PROXY": "http://proxy.example.com:8080",
    "NO_PROXY": "localhost,.aliyun.com",
    "ALIYUN_ECS_SELF_DESTRUCT_ROLE_NAME": "runner-self-destruct-role",
}
# RUNNER_LABELS is deliberately NOT injected: optional values must leave the
# template default line untouched.
UNSET_OPTIONALS = ("RUNNER_LABELS",)


def test_generate_user_data_injection_contract(tmp_path):
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(tmp_path),
        "TEMPLATE_FILE": str(REPO / "templates" / "user-data.sh"),
        **FAKE_VALUES,
    }
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "generate-user-data.sh")],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, f"generator failed: {result.stderr}"
    generated = result.stdout

    # Every provided value must be injected into the rendered user-data.
    for var, value in FAKE_VALUES.items():
        assert value in generated, f"{var} not injected into template output"

    # Unset optionals must keep their template default lines (no injection,
    # no corruption) so runtime defaults still apply on the instance.
    assert 'RUNNER_LABELS="${RUNNER_LABELS:-}"' in generated, (
        "unset optional RUNNER_LABELS must retain its template default line"
    )

    # The rendered script must stay syntactically valid bash.
    rendered = tmp_path / "rendered-user-data.sh"
    rendered.write_text(generated, encoding="utf-8")
    syntax = subprocess.run(
        ["bash", "-n", str(rendered)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert syntax.returncode == 0, f"rendered user-data failed bash -n: {syntax.stderr}"
