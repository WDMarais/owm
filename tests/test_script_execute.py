"""
execute_script: config-aware path resolution, env-contract injection, and
honest failures (no more silent "0 total" when the script can't be found/run).
"""
import json
import os
import sys

import pytest

from owm.scripts import execute_script
from owm.errors import OwmError, SCRIPT_NOT_FOUND, SCRIPT_FAILED


def _instance(ws, name, *, runners, scripts_dir="scripts", with_venv=False):
    """Write a minimal instance with a [scripts.runners] table; optionally a venv
    python (symlinked to this interpreter) so plain runners actually execute."""
    inst = ws / "instances" / name
    inst.mkdir(parents=True)
    runner_lines = "\n".join(
        f'{k} = {{ file = "{f}", type = "{t}" }}' for k, (f, t) in runners.items()
    )
    (inst / "instance.toml").write_text(
        '[repos]\napp = "main"\n'
        f'\n[database]\nname = "db_{name}"\npg_port = 5432\n'
        "\n[server]\nhttp_port = 8100\ngevent_port = 8101\n"
        f'\n[scripts]\nscripts_dir = "{scripts_dir}"\n'
        f"\n[scripts.runners]\n{runner_lines}\n"
    )
    if with_venv:
        venv_bin = inst / ".venv" / "bin"
        venv_bin.mkdir(parents=True)
        os.symlink(sys.executable, venv_bin / "python")
    return inst


@pytest.mark.script_runner
def test_execute_script_unknown_runner_raises(tmp_workspace):
    _instance(tmp_workspace, "feat-1", runners={"test": ("run.py", "plain")})
    with pytest.raises(OwmError) as ei:
        execute_script("feat-1", "nope", str(tmp_workspace))
    assert ei.value.code == SCRIPT_NOT_FOUND
    assert "known: test" in ei.value.args[0]


@pytest.mark.script_runner
def test_execute_script_missing_file_resolves_under_scripts_dir(tmp_workspace):
    _instance(tmp_workspace, "feat-1", runners={"setup": ("setup.py", "plain")})
    with pytest.raises(OwmError) as ei:
        execute_script("feat-1", "setup", str(tmp_workspace))
    assert ei.value.code == SCRIPT_NOT_FOUND
    # resolved via scripts_dir + runner.file, not the old scripts/<instance>/<name>.py
    assert ei.value.args[0].endswith("instances/feat-1/scripts/setup.py")


@pytest.mark.script_runner
def test_execute_script_plain_writes_ndjson_file_and_returns_run_log(tmp_workspace, tmp_path):
    inst = _instance(tmp_workspace, "feat-1", runners={"smoke": ("smoke.py", "plain")}, with_venv=True)
    (inst / "scripts").mkdir()
    # Writes a row (using the injected DB_NAME) to $NDJSON_OUT; prints a run log to stdout.
    (inst / "scripts" / "smoke.py").write_text(
        "import os, json\n"
        "with open(os.environ['NDJSON_OUT'], 'w') as f:\n"
        "    f.write(json.dumps({'case': os.environ['DB_NAME'], 'status': 'OK'}) + '\\n')\n"
        "print('did the setup')\n"
    )
    out_file = tmp_path / "out.ndjson"
    run_log = execute_script("feat-1", "smoke", str(tmp_workspace), ndjson_out=str(out_file))
    # stdout is the run log; structured results live in the NDJSON_OUT file
    assert run_log.strip() == "did the setup"
    assert json.loads(out_file.read_text().strip()) == {"case": "db_feat-1", "status": "OK"}


@pytest.mark.script_runner
def test_execute_script_plain_nonzero_exit_raises(tmp_workspace):
    inst = _instance(tmp_workspace, "feat-1", runners={"boom": ("boom.py", "plain")}, with_venv=True)
    (inst / "scripts").mkdir()
    (inst / "scripts" / "boom.py").write_text("import sys\nsys.stderr.write('kaboom\\n')\nsys.exit(2)\n")
    with pytest.raises(OwmError) as ei:
        execute_script("feat-1", "boom", str(tmp_workspace))
    assert ei.value.code == SCRIPT_FAILED
    assert ei.value.extra["returncode"] == 2
    assert "kaboom" in ei.value.args[0]
