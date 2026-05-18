import json
import os
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum


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
    status: str
    summary: ScriptSummary
    rows: list
    rows_run: int | None = None
    abort_reason: str | None = None
    blocker: str | None = None
    contract_violation: bool = False


@dataclass
class CompareResult:
    status: str
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
    lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
    return [json.loads(l) for l in lines]


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


def execute_script(instance: str, script_name: str, workspace_root: str) -> str:
    """Run the script subprocess with the instance venv; return raw stdout (NDJSON lines)."""
    venv_python = os.path.join(workspace_root, "instances", instance, ".venv", "bin", "python")
    script_path = os.path.join(workspace_root, "scripts", instance, f"{script_name}.py")
    r = subprocess.run([venv_python, script_path], capture_output=True, text=True, check=False)
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
