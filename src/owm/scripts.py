import json
import os
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from owm.config import load_instance_config
from owm.env import resolve_env
from owm.errors import OwmError, SCRIPT_NOT_FOUND, SCRIPT_FAILED


class FailureMode(StrEnum):
    ROW_LEVEL = "row_level"
    CONTRACT  = "contract"


VALID_ROW_STATUSES = frozenset({"OK", "FAIL", "WARN", "NONE"})


@dataclass
class ScriptSummary:
    ok: int
    fail: int
    warn: int
    none: int
    total: int
    non_conforming: int = 0
    unexpected_changes: int = 0


@dataclass
class ScriptResult:
    status: Literal["abort", "ok", "fail"]
    summary: ScriptSummary
    rows: list
    rows_run: int | None = None
    abort_reason: str | None = None
    blocker: str | None = None
    contract_violation: bool = False


@dataclass
class CompareResult:
    status: Literal["error", "ok", "unexpected_changes"]
    base_instance: str | None = None
    feat_instance: str | None = None
    summary: ScriptSummary | None = None
    unexpected: list = field(default_factory=list)
    error: str | None = None
    missing_instance: str | None = None


@dataclass
class ScaffoldResult:
    path: str
    content: str


def parse_ndjson_output(raw: str) -> list[dict]:
    """NDJSON rows from a results file's contents.

    The results file is the structured channel: a script opts in by writing rows
    to $NDJSON_OUT. owm never parses a script's stdout for structure, so this only
    ever sees the file. Non-JSON lines are skipped rather than fatal — a tolerant
    guardrail, since stdout (odoo-shell noise, human prints) is a separate sink."""
    rows: list[dict] = []
    for line in raw.strip().split("\n"):
        s = line.strip()
        if not s:
            continue
        try:
            rows.append(json.loads(s))
        except json.JSONDecodeError:
            continue
    return rows


def run_script(
    instance: str,
    script_name: str,
    *,
    failure_mode: FailureMode | str = FailureMode.ROW_LEVEL,
    ndjson_output: str | None = None,
    contract: dict | None = None,
) -> ScriptResult:
    all_rows = parse_ndjson_output(ndjson_output or "")
    processed = []
    rows_run = 0

    for row in all_rows:
        if row.get("abort"):
            return ScriptResult(
                status="abort",
                summary=_tally(processed),
                rows=processed,
                rows_run=rows_run,
                abort_reason=row.get("reason"),
            )

        if "status" in row and row["status"] not in VALID_ROW_STATUSES:
            processed.append({**row, "_non_conforming": True})
            rows_run += 1
            continue

        if failure_mode == FailureMode.CONTRACT and contract and row.get("status") == "FAIL":
            blocking = contract.get("blocking_failures", [])
            if row.get("case") in blocking:
                processed.append(row)
                rows_run += 1
                return ScriptResult(
                    status="abort",
                    summary=_tally(processed),
                    rows=processed,
                    rows_run=rows_run,
                    blocker=row.get("case"),
                    contract_violation=True,
                )

        processed.append(row)
        rows_run += 1

    summary = _tally(processed)
    if failure_mode == FailureMode.CONTRACT and contract:
        acceptable = set(contract.get("acceptable_failures", []))
        real_failures = [r for r in processed if r.get("status") == "FAIL" and r.get("case") not in acceptable]
        status = "ok" if not real_failures else "fail"
    else:
        status = "ok" if summary.fail == 0 else "fail"
    return ScriptResult(status=status, summary=summary, rows=processed, rows_run=rows_run)


def _tally(rows: list) -> ScriptSummary:
    counts = {"OK": 0, "FAIL": 0, "WARN": 0, "NONE": 0}
    non_conforming = 0
    for r in rows:
        if r.get("_non_conforming"):
            non_conforming += 1
            continue
        s = r.get("status")
        if s in counts:
            counts[s] += 1
    return ScriptSummary(
        ok=counts["OK"],
        fail=counts["FAIL"],
        warn=counts["WARN"],
        non_conforming=non_conforming,
        none=counts["NONE"],
        total=len(rows),
    )


def compare_instances(
    instance: str,
    *,
    base: str | None = None,
    workspace_root: str = ".",
    workspace_compare_pairs: list | None = None,
    base_rows: list | None = None,
    feat_rows: list | None = None,
    expected_changes: list | None = None,
) -> CompareResult:
    base_instance = base
    feat_instance = instance

    if not base_instance and workspace_compare_pairs:
        for pair in workspace_compare_pairs:
            if instance in pair:
                base_instance = next(p for p in pair if p != instance)
                break

    if base_instance and base_rows is None and not os.path.isdir(
        os.path.join(workspace_root, "instances", base_instance)
    ):
        return CompareResult(
            status="error",
            base_instance=base_instance,
            feat_instance=feat_instance,
            error=f"{base_instance} not found",
            missing_instance=base_instance,
        )

    if base_rows is None or feat_rows is None:
        return CompareResult(
            status="ok",
            base_instance=base_instance,
            feat_instance=feat_instance,
            summary=ScriptSummary(ok=0, fail=0, warn=0, none=0, total=0),
        )

    declared = {
        e["case"]: (e["base"], e["feat"])
        for e in (expected_changes or [])
    }
    base_by_case = {r["case"]: r["status"] for r in base_rows}
    feat_by_case = {r["case"]: r["status"] for r in feat_rows}

    unexpected = []
    for case, feat_status in feat_by_case.items():
        base_status = base_by_case.get(case)
        if base_status == feat_status:
            continue
        if case in declared and declared[case] == (base_status, feat_status):
            continue
        unexpected.append({"case": case, "base": base_status, "feat": feat_status})

    status = "unexpected_changes" if unexpected else "ok"
    summary = ScriptSummary(ok=0, fail=0, warn=0, none=0, total=len(feat_rows), unexpected_changes=len(unexpected))
    return CompareResult(
        status=status,
        base_instance=base_instance,
        feat_instance=feat_instance,
        summary=summary,
        unexpected=unexpected,
    )


def execute_script(instance: str, script_name: str, workspace_root: str,
                   ndjson_out: str | None = None) -> str:
    """Run an instance's declared script runner; return its raw stdout (run log).

    Resolves the runner from instance.toml ([scripts.runners].<name>), honoring
    scripts_dir and the runner's file/type, rather than assuming
    scripts/<instance>/<name>.py. The instance env contract (resolve_env) is set
    on the subprocess so a script reads its target exactly as an external caller
    would after ``owm env <instance> --format shell``. A ``plain`` runner runs as
    bare python; a ``shell`` runner is piped through odoo-bin shell with the ORM
    ``env`` available.

    Structured results are decoupled from stdout: a script opts in by writing
    NDJSON rows to the file at $NDJSON_OUT (``ndjson_out``), which owm consumes at
    completion. stdout is just the run log — odoo-shell noise, human prints,
    whatever — returned for display, never parsed. A missing runner/file or a
    nonzero exit raises rather than reporting a misleading empty success.
    """
    conf = load_instance_config(instance, workspace_root)
    runners = conf.scripts.runners if conf.scripts else {}
    runner = runners.get(script_name)
    if runner is None:
        known = ", ".join(sorted(runners)) or "none"
        raise OwmError(
            f"no script runner {script_name!r} in [scripts.runners] (known: {known})",
            code=SCRIPT_NOT_FOUND,
        )

    instance_dir = os.path.join(workspace_root, "instances", instance)
    scripts_dir = conf.scripts.scripts_dir if conf.scripts else None
    base = os.path.join(instance_dir, scripts_dir) if scripts_dir else instance_dir
    script_path = os.path.join(base, runner.file)
    if not os.path.isfile(script_path):
        raise OwmError(f"script file not found: {script_path}", code=SCRIPT_NOT_FOUND)

    # Only a shell runner needs odoo-bin; resolving it for a plain runner would
    # force an odoo repo on instances that don't have one. Local import: instance.py
    # pulls in a heavier graph that would couple this low-level runner to it.
    odoo_bin = None
    if runner.type == "shell":
        from owm.instance import odoo_bin_path
        odoo_bin = odoo_bin_path(conf, workspace_root, instance)

    env = {**os.environ, **resolve_env(
        instance=instance,
        workspace_root=workspace_root,
        odoo_bin=odoo_bin,
        instance_db_name=conf.database.name,
        instance_pg_port=conf.database.pg_port,
        instance_http_port=conf.server.http_port,
        instance_gevent_port=conf.server.gevent_port,
        instance_scripts_dir=scripts_dir,
    )}
    if ndjson_out is not None:
        # Where the script writes its NDJSON results (opt-in). Per-run, so it
        # layers on top of the instance-level resolve_env contract.
        env["NDJSON_OUT"] = ndjson_out
    venv_python = os.path.join(instance_dir, ".venv", "bin", "python")

    if runner.type == "shell":
        # Pipe the script through odoo-bin shell so it runs with the ORM `env`
        # bound — the same invocation `owm shell` uses.
        conf_path = os.path.join(instance_dir, "instance.conf")
        cmd = [venv_python, odoo_bin, "shell", "-c", conf_path,
               "-d", conf.database.name, "--no-http"]
        with open(script_path) as f:
            stdin = f.read()
    else:  # plain
        cmd = [venv_python, script_path]
        stdin = None

    r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, check=False, env=env)
    if r.returncode != 0:
        detail = (r.stderr or "").strip() or f"exited {r.returncode}"
        raise OwmError(
            f"script {script_name!r} failed: {detail}",
            code=SCRIPT_FAILED, returncode=r.returncode, stderr=(r.stderr or "").strip(),
        )
    return r.stdout


def scaffold_script(instance: str, script_name: str) -> ScaffoldResult:
    path = f"scripts/{instance}/{script_name}.py"
    content = (
        "# Script contract\n"
        "# acceptable_failures: []\n"
        "# blocking_failures: []\n"
        "\n"
        "import json, sys\n"
        "\n"
        "# Emit each row as NDJSON:\n"
        '# print(json.dumps({"case": "...", "status": "OK"}))\n'
        "# Emit abort signal:\n"
        '# print(json.dumps({"abort": True, "reason": "..."}))\n'
    )
    return ScaffoldResult(path=path, content=content)
